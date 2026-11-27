import asyncio
import logging
import re
import time
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.agent.intent import IntentService
from backend.app.agent.orchestrator import AfterSalesOrchestrator
from backend.app.agent.schemas import (
    AfterSalesIntent,
    ConversationAction,
    GetMyOrderArguments,
    IntentResult,
    IssueType,
    SearchProductsArguments,
    ToolCallPlan,
    ToolResultSummary,
)
from backend.app.agent.tools import (
    GET_MY_ORDER,
    SEARCH_PRODUCTS,
    ToolContext,
    ToolRegistry,
)
from backend.app.core.config import Settings
from backend.app.core.exceptions import AppError
from backend.app.models import (
    AfterSalesTicket,
    AfterSalesTicketType,
    ChatSession,
    HandoffSource,
    KnowledgeCategory,
    Order,
    Product,
    RefundExecutionStatus,
    SenderType,
    SessionStatus,
    WorkflowState,
)
from backend.app.repositories.after_sales_tickets import get_ticket_by_session
from backend.app.repositories.chat import (
    add_message,
    get_session_owned_by_user,
    list_messages,
)
from backend.app.repositories.handoffs import get_handoff_by_session
from backend.app.schemas.after_sales import AfterSalesTicketResponse
from backend.app.schemas.chat import ChatMessageResponse, ChatTurnResponse
from backend.app.schemas.handoff import HandoffResponse
from backend.app.schemas.rag import CitationResponse
from backend.app.services.after_sales_eligibility import (
    AfterSalesEligibility,
    AfterSalesEligibilityService,
)
from backend.app.services.after_sales_tickets import AfterSalesTicketService
from backend.app.services.answers import AnswerService
from backend.app.services.discounts import DiscountService
from backend.app.services.handoffs import HandoffService
from backend.app.services.llm import DeepSeekClient, json_dumps
from backend.app.services.order_context import OrderContextService
from backend.app.services.rag import NO_EVIDENCE_ANSWER, RAGContext, RAGService
from backend.app.services.refund_decisions import RefundDecisionService
from backend.app.services.rules import AfterSalesRuleService

logger = logging.getLogger(__name__)

_POLICY_INTENTS = {
    AfterSalesIntent.AFTER_SALES_POLICY,
    AfterSalesIntent.LOGISTICS_QUERY,
    AfterSalesIntent.RETURN_REQUEST,
    AfterSalesIntent.EXCHANGE_REQUEST,
    AfterSalesIntent.REPAIR_REQUEST,
    AfterSalesIntent.COMPENSATION_REQUEST,
    AfterSalesIntent.WARRANTY_QUESTION,
    AfterSalesIntent.DISCOUNT_QUERY,
}
_REQUESTED_DISCOUNT = re.compile(r"(?:便宜|优惠|少|减|省)(?:多少)?\s*(\d+(?:\.\d{1,2})?)\s*元")


class AfterSalesAgentService:
    """Coordinate intent, tools, RAG, deterministic rules and persistence."""

    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        llm: DeepSeekClient,
        rag_service: RAGService,
        intent_service: IntentService | None = None,
        orchestrator: AfterSalesOrchestrator | None = None,
        tools: ToolRegistry | None = None,
        rules: AfterSalesRuleService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.llm = llm
        self.rag_service = rag_service
        self.intent_service = intent_service or IntentService(llm)
        self.orchestrator = orchestrator or AfterSalesOrchestrator()
        self.tools = tools or ToolRegistry()
        self.rules = rules or AfterSalesRuleService()
        self.order_context = OrderContextService(session)
        self.eligibility = AfterSalesEligibilityService()
        self.refund_decisions = RefundDecisionService(session=session, llm=llm)
        self.answer_service = AnswerService(llm)

    async def handle_message(
        self,
        *,
        session_id: int,
        user_id: int,
        content: str,
    ) -> ChatTurnResponse:
        started_at = time.perf_counter()
        chat_session = self._require_owned_session(
            session_id=session_id,
            user_id=user_id,
        )
        expected_control_version = chat_session.control_version
        user_message = add_message(
            self.session,
            session_id=chat_session.id,
            sender_type=SenderType.CONSUMER.value,
            content=content,
        )

        if chat_session.status in {
            SessionStatus.NEED_HUMAN.value,
            SessionStatus.HUMAN_ACTIVE.value,
            SessionStatus.CLOSED.value,
        }:
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )

        existing_slots = dict(chat_session.slots_json or {})
        intent_started_at = time.perf_counter()
        try:
            async with asyncio.timeout(self.settings.agent_total_timeout_seconds):
                intent_result = await self.intent_service.extract(
                    content=content,
                    existing_slots=existing_slots,
                )
            logger.info(
                "agent intent completed duration_ms=%.2f",
                (time.perf_counter() - intent_started_at) * 1000,
            )
        except TimeoutError:
            logger.warning("Intent request timeout session_id=%s", session_id)
            return self._fail_to_handoff(
                chat_session=chat_session,
                user_message=user_message,
                reason="意图识别超时，需要人工客服继续处理",
                expected_control_version=expected_control_version,
            )
        except AppError as exc:
            logger.warning(
                "Intent dependency failure session_id=%s error=%s",
                session_id,
                exc.code,
            )
            return self._fail_to_handoff(
                chat_session=chat_session,
                user_message=user_message,
                reason=f"意图识别失败（{exc.code}），需要人工客服继续处理",
                expected_control_version=expected_control_version,
            )
        if not self._control_allowed(
            chat_session,
            expected_control_version=expected_control_version,
        ):
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )
        intent_result = self._preserve_active_task(intent_result)
        order_resolution = self.order_context.resolve_for_turn(
            chat_session=chat_session,
            intent_result=intent_result,
            content=content,
        )
        chat_session, decision = self.orchestrator.apply(
            session=self.session,
            session_id=session_id,
            user_id=user_id,
            result=intent_result,
            order_selection_required=order_resolution.awaiting_selection,
            order_selection_prompt=order_resolution.prompt,
        )
        logger.info(
            "agent orchestration action=%s workflow=%s duration_ms=%.2f",
            decision.action.value,
            decision.workflow_state.value,
            (time.perf_counter() - started_at) * 1000,
        )

        if decision.reply_text:
            return self._save_turn(
                chat_session=chat_session,
                user_message=user_message,
                answer=decision.reply_text,
                action=(
                    ConversationAction.SELECT_ORDER
                    if decision.action.value == "select_order"
                    else ConversationAction.ASK_MORE_INFO
                ),
                missing_slots=decision.missing_slots,
                expected_control_version=expected_control_version,
            )

        if decision.action.value == "handoff":
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason="用户主动申请人工客服",
                source=HandoffSource.USER,
                expected_control_version=expected_control_version,
            )

        try:
            async with asyncio.timeout(self.settings.agent_total_timeout_seconds):
                if decision.action.value == "product_query":
                    return await self._handle_product_task(
                        chat_session=chat_session,
                        user_message=user_message,
                        content=content,
                        intent_result=intent_result,
                        expected_control_version=expected_control_version,
                    )
                if decision.action.value == "after_sales_progress":
                    return self._handle_after_sales_progress_task(
                        chat_session=chat_session,
                        user_message=user_message,
                        expected_control_version=expected_control_version,
                    )
                if decision.action.value == "query_order":
                    return await self._handle_order_task(
                        chat_session=chat_session,
                        user_message=user_message,
                        content=content,
                        intent_result=intent_result,
                        expected_control_version=expected_control_version,
                    )
                return await self._handle_policy_task(
                    chat_session=chat_session,
                    user_message=user_message,
                    content=content,
                    intent_result=intent_result,
                    expected_control_version=expected_control_version,
                )
        except TimeoutError:
            logger.warning("Agent request timeout session_id=%s", session_id)
            return self._fail_to_handoff(
                chat_session=chat_session,
                user_message=user_message,
                reason="AI 服务超时，需要人工客服继续处理",
                expected_control_version=expected_control_version,
            )
        except AppError as exc:
            logger.warning(
                "Agent dependency failure session_id=%s error=%s",
                session_id,
                exc.code,
            )
            return self._fail_to_handoff(
                chat_session=chat_session,
                user_message=user_message,
                reason=f"AI 处理失败（{exc.code}），需要人工客服继续处理",
                expected_control_version=expected_control_version,
            )
        except Exception:
            logger.exception("Unexpected agent failure session_id=%s", session_id)
            return self._fail_to_handoff(
                chat_session=chat_session,
                user_message=user_message,
                reason="AI 处理出现异常，需要人工客服继续处理",
                expected_control_version=expected_control_version,
            )

    async def _handle_product_task(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        content: str,
        intent_result: IntentResult,
        expected_control_version: int,
    ) -> ChatTurnResponse:
        context = ToolContext(
            session=self.session,
            session_id=chat_session.id,
            user_id=chat_session.user_id,
            rag_service=self.rag_service,
        )
        arguments = SearchProductsArguments(query=content, limit=4)
        tool_result = self.tools.execute(
            context=context,
            tool_name=SEARCH_PRODUCTS,
            arguments=arguments.model_dump(mode="json"),
        )
        products = tool_result.result.get("products", [])
        if not products:
            return self._finish_with_answer(
                chat_session=chat_session,
                user_message=user_message,
                answer="当前商品目录中没有找到与问题匹配的商品。",
                rag_context=RAGContext(
                    evidence="",
                    citations=[],
                    chunks=(),
                    grounded=False,
                ),
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=tool_result.result,
                    )
                ],
            )

        if intent_result.intent == AfterSalesIntent.DISCOUNT_QUERY:
            return await self._handle_discount_task(
                chat_session=chat_session,
                user_message=user_message,
                content=content,
                products=products,
                expected_control_version=expected_control_version,
                search_tool_name=tool_result.tool_name,
                search_result=tool_result.result,
            )

        evidence_parts = [f"商品实时事实：{json_dumps(products)}"]
        citations: list[CitationResponse] = []
        seen_citations: set[str] = set()
        for product in products:
            rag_context = await self.rag_service.retrieve(
                question=f"{content} {product['name']} 商品说明",
                product_id=product["id"],
                category=KnowledgeCategory.PRODUCT,
            )
            if rag_context.evidence:
                evidence_parts.append(
                    f"商品 {product['name']} 的知识证据：\n{rag_context.evidence}"
                )
            for citation in rag_context.citations:
                if citation.chunk_id not in seen_citations:
                    citations.append(citation)
                    seen_citations.add(citation.chunk_id)

        answer = await self.llm.generate_answer(
            question=content,
            evidence="\n\n".join(evidence_parts),
        )
        if not self._control_allowed(
            chat_session,
            expected_control_version=expected_control_version,
        ):
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )
        return self._finish_with_answer(
            chat_session=chat_session,
            user_message=user_message,
            answer=answer,
            rag_context=RAGContext(
                evidence="\n\n".join(evidence_parts),
                citations=citations,
                chunks=(),
                grounded=True,
            ),
            expected_control_version=expected_control_version,
            tool_results=[
                ToolResultSummary(
                    tool_name=tool_result.tool_name,
                    status="success",
                    result=tool_result.result,
                )
            ],
        )

    async def _handle_discount_task(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        content: str,
        products: list[dict],
        expected_control_version: int,
        search_tool_name: str,
        search_result: dict,
    ) -> ChatTurnResponse:
        if len(products) != 1:
            names = "、".join(product["name"] for product in products[:4])
            answer = (
                f"请明确要咨询优惠的商品。当前匹配到：{names}。"
                if products
                else "当前商品目录中没有找到匹配商品。"
            )
            return self._finish_with_answer(
                chat_session=chat_session,
                user_message=user_message,
                answer=answer,
                rag_context=RAGContext(
                    evidence="",
                    citations=[],
                    chunks=(),
                    grounded=False,
                ),
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=search_tool_name,
                        status="success",
                        result=search_result,
                    )
                ],
            )

        product_facts = products[0]
        product_id = int(product_facts["id"])
        product = self.session.get(Product, product_id)
        if product is None:
            raise AppError(
                status_code=404,
                code="product_not_found",
                message="商品不存在",
            )
        rag_context = await self.rag_service.retrieve(
            question=f"{content} 优惠授权 报价政策",
            product_id=product_id,
            category=KnowledgeCategory.BUSINESS_POLICY,
        )
        if not rag_context.grounded:
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason="没有可引用的优惠政策，无法生成授权报价",
                source=HandoffSource.RULE,
                answer="当前没有足够优惠政策依据生成报价，已申请人工客服核实。",
                expected_control_version=expected_control_version,
                rag_context=rag_context,
                tool_results=[
                    ToolResultSummary(
                        tool_name=search_tool_name,
                        status="success",
                        result=search_result,
                    )
                ],
            )
        match = _REQUESTED_DISCOUNT.search(content)
        requested = Decimal(match.group(1)) if match else None
        try:
            result = DiscountService(self.session).create_quote(
                session_id=chat_session.id,
                user_id=chat_session.user_id,
                product=product,
                citations=rag_context.citations,
                requested_discount_amount=requested,
            )
        except AppError as exc:
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=exc.message,
                source=HandoffSource.RULE,
                answer=f"{exc.message}，已申请人工客服继续协商。",
                expected_control_version=expected_control_version,
                rag_context=rag_context,
                tool_results=[
                    ToolResultSummary(
                        tool_name=search_tool_name,
                        status="success",
                        result=search_result,
                    )
                ],
            )

        quote = result.quote
        answer = (
            f"{product.name} 当前库存 {product.stock_quantity} 件，标价 "
            f"{quote.unit_price} {quote.currency}。系统在商家授权范围内给出的"
            f"模拟优惠为 {quote.discount_amount} 元，报价 "
            f"{quote.final_price} {quote.currency}。优惠报价单号 "
            f"{quote.quote_no}，30 分钟内有效。该报价不创建订单，也不锁定库存。"
        )
        if result.exceeds_authorization:
            answer += (
                f" 你希望的优惠金额为 {result.requested_discount_amount} 元，"
                f"超过当前授权上限 {result.authorized_discount_amount} 元，"
                "已转人工进一步协商。"
            )
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason="消费者期望优惠超过商家授权上限",
                source=HandoffSource.RULE,
                answer=answer,
                expected_control_version=expected_control_version,
                rag_context=rag_context,
                tool_results=[
                    ToolResultSummary(
                        tool_name=search_tool_name,
                        status="success",
                        result=search_result,
                    )
                ],
            )
        return self._finish_with_answer(
            chat_session=chat_session,
            user_message=user_message,
            answer=answer,
            rag_context=rag_context,
            expected_control_version=expected_control_version,
            tool_results=[
                ToolResultSummary(
                    tool_name=search_tool_name,
                    status="success",
                    result=search_result,
                )
            ],
        )

    def _handle_after_sales_progress_task(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        expected_control_version: int,
    ) -> ChatTurnResponse:
        tickets = AfterSalesTicketService(self.session).list_for_user(
            user_id=chat_session.user_id,
        )
        if not tickets:
            answer = "当前账号还没有售后工单。"
        else:
            lines = ["你当前的售后工单："]
            for ticket in tickets[:5]:
                lines.append(
                    f"- {ticket.ticket_no}｜{ticket.request_type}｜{ticket.status}"
                    f"｜创建时间：{ticket.created_at.isoformat(timespec='minutes')}"
                )
            answer = "\n".join(lines)
        return self._finish_with_answer(
            chat_session=chat_session,
            user_message=user_message,
            answer=answer,
            rag_context=RAGContext(
                evidence="",
                citations=[],
                chunks=(),
                grounded=False,
            ),
            expected_control_version=expected_control_version,
        )

    async def _handle_order_task(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        content: str,
        intent_result: IntentResult,
        expected_control_version: int,
    ) -> ChatTurnResponse:
        order_no = intent_result.slots.order_no
        if order_no is None:
            return self._save_turn(
                chat_session=chat_session,
                user_message=user_message,
                answer="请提供需要查询的订单号。",
                action=ConversationAction.ASK_MORE_INFO,
                missing_slots=["order_no"],
                expected_control_version=expected_control_version,
            )

        plan = await self._plan_order_tool(content=content, order_no=order_no)
        context = ToolContext(
            session=self.session,
            session_id=chat_session.id,
            user_id=chat_session.user_id,
            rag_service=self.rag_service,
        )
        try:
            tool_result = self.tools.execute(
                context=context,
                tool_name=plan.name,
                arguments=plan.arguments,
            )
        except AppError as exc:
            if exc.code == "order_not_found":
                self.order_context.on_order_lookup_failed(chat_session)
            self.orchestrator.transition(
                session=self.session,
                chat_session=chat_session,
                target=WorkflowState.COLLECTING_INFO,
            )
            answer = (
                "未找到属于当前账号的有效订单，请检查订单号后重试。"
                if exc.code == "order_not_found"
                else "订单查询暂时失败，请稍后重试或申请人工客服。"
            )
            return self._save_turn(
                chat_session=chat_session,
                user_message=user_message,
                answer=answer,
                action=ConversationAction.ASK_MORE_INFO,
                missing_slots=["order_no"] if exc.code == "order_not_found" else [],
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=plan.name,
                        status="error",
                        result={"error": exc.code},
                        error_code=exc.code,
                    )
                ],
            )

        order_facts = tool_result.result
        if not self._control_allowed(
            chat_session,
            expected_control_version=expected_control_version,
        ):
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )
        order_id = int(order_facts["order_id"])
        order = self.session.get(Order, order_id)
        if order is None:
            raise AppError(
                status_code=404,
                code="order_not_found",
                message="订单不存在",
            )
        self.order_context.on_order_verified(chat_session, order)
        product_id = int(order_facts["product_id"])
        chat_session.slots_json = {
            **chat_session.slots_json,
            "product_id": product_id,
        }
        self.session.commit()
        self.session.refresh(chat_session)
        chat_session = self.orchestrator.transition(
            session=self.session,
            chat_session=chat_session,
            target=WorkflowState.CHECKING_POLICY,
        )

        if intent_result.intent == AfterSalesIntent.LOGISTICS_QUERY:
            rag_context = await self._retrieve_policy(
                content=content,
                intent_result=intent_result,
                product_id=product_id,
            )
            answer = await self.answer_service.generate(
                question=content,
                intent=intent_result.intent.value,
                order_facts=order_facts,
                rag_context=rag_context,
                history=self._history_for_model(chat_session.id),
                eligibility=None,
            )
            return self._finish_with_answer(
                chat_session=chat_session,
                user_message=user_message,
                answer=answer,
                rag_context=rag_context,
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=order_facts,
                    )
                ],
            )

        eligibility: AfterSalesEligibility | None = None
        request_type: AfterSalesTicketType | None = None
        if intent_result.intent in {
            AfterSalesIntent.RETURN_REQUEST,
            AfterSalesIntent.EXCHANGE_REQUEST,
            AfterSalesIntent.REPAIR_REQUEST,
            AfterSalesIntent.COMPENSATION_REQUEST,
        }:
            request_type = (
                AfterSalesTicketType.RETURN
                if intent_result.intent == AfterSalesIntent.RETURN_REQUEST
                else (
                    AfterSalesTicketType.EXCHANGE
                    if intent_result.intent == AfterSalesIntent.EXCHANGE_REQUEST
                    else (
                        AfterSalesTicketType.REPAIR
                        if intent_result.intent == AfterSalesIntent.REPAIR_REQUEST
                        else AfterSalesTicketType.COMPENSATION
                    )
                )
            )
            eligibility = self.eligibility.evaluate(
                order=order,
                request_type=request_type.value,
                issue_description=intent_result.slots.issue_description or "",
            )
        elif intent_result.intent == AfterSalesIntent.WARRANTY_QUESTION:
            eligibility = self.eligibility.evaluate(
                order=order,
                request_type="warranty",
                issue_description=intent_result.slots.issue_description or "",
            )

        rag_context = await self._retrieve_policy(
            content=content,
            intent_result=intent_result,
            product_id=product_id,
        )
        decision = self.rules.enforce(
            answer="",
            intent=intent_result.intent,
            order_facts=order_facts,
            policy_grounded=rag_context.grounded,
        )
        if decision.handoff_required:
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=decision.handoff_reason or "售后规则要求人工复核",
                source=HandoffSource.RULE,
                answer=decision.answer,
                eligibility=eligibility,
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=order_facts,
                    )
                ],
            )

        if eligibility is not None and eligibility.result.value == "need_human_review":
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=eligibility.explanation,
                source=HandoffSource.RULE,
                answer=eligibility.explanation,
                eligibility=eligibility,
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=order_facts,
                    )
                ],
            )
        if eligibility is not None and eligibility.result.value == "not_eligible":
            return self._finish_with_answer(
                chat_session=chat_session,
                user_message=user_message,
                answer=eligibility.explanation,
                rag_context=rag_context,
                eligibility=eligibility,
                expected_control_version=expected_control_version,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=order_facts,
                    )
                ],
            )

        if (
            intent_result.intent == AfterSalesIntent.COMPENSATION_REQUEST
            and intent_result.slots.submit_requested is True
        ):
            issue_description = intent_result.slots.issue_description
            if eligibility is None or not issue_description:
                raise AppError(
                    status_code=500,
                    code="compensation_context_missing",
                    message="补偿申请缺少资格或问题信息",
                )
            refund_decision = await self.refund_decisions.evaluate(
                order=order,
                issue_description=issue_description,
                rag_context=rag_context,
            )
            compensation_ticket, agent_decision, auto_approved = AfterSalesTicketService(
                self.session
            ).create_compensation_for_session(
                chat_session=chat_session,
                order=order,
                issue_description=issue_description,
                citations=rag_context.citations,
                eligibility=eligibility,
                decision=refund_decision,
            )
            if auto_approved:
                execution = compensation_ticket.refund_execution
                if (
                    execution is not None
                    and execution.status == RefundExecutionStatus.SUCCESS.value
                ):
                    answer = (
                        f"系统已在商家授权范围内通过部分补偿 "
                        f"{refund_decision.suggested_amount} {eligibility.currency}。"
                        f"模拟退款执行成功，流水号 {execution.provider_reference}。"
                    )
                elif execution is not None:
                    answer = (
                        f"系统已在商家授权范围内通过部分补偿 "
                        f"{refund_decision.suggested_amount} {eligibility.currency}，"
                        "但模拟退款执行失败，已进入客服重试队列。"
                    )
                else:
                    answer = (
                        f"系统已在商家授权范围内通过部分补偿 "
                        f"{refund_decision.suggested_amount} {eligibility.currency}，"
                        "退款执行记录正在生成。"
                    )
                return self._finish_with_answer(
                    chat_session=chat_session,
                    user_message=user_message,
                    answer=answer,
                    rag_context=rag_context,
                    eligibility=eligibility,
                    expected_control_version=expected_control_version,
                    after_sales_ticket=compensation_ticket,
                    ticket_created=True,
                    tool_results=[
                        ToolResultSummary(
                            tool_name=tool_result.tool_name,
                            status="success",
                            result=order_facts,
                        )
                    ],
                )
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=refund_decision.analysis,
                source=HandoffSource.RULE,
                answer="补偿建议未满足自动审批条件，已生成待人工审核工单。",
                eligibility=eligibility,
                expected_control_version=expected_control_version,
                after_sales_ticket=compensation_ticket,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=order_facts,
                    )
                ],
            )

        ticket: AfterSalesTicket | None = None
        ticket_created = False
        if (
            intent_result.intent
            in {
                AfterSalesIntent.RETURN_REQUEST,
                AfterSalesIntent.EXCHANGE_REQUEST,
                AfterSalesIntent.REPAIR_REQUEST,
            }
            and intent_result.slots.submit_requested is True
        ):
            issue_description = intent_result.slots.issue_description
            if not issue_description:
                raise AppError(
                    status_code=500,
                    code="after_sales_ticket_context_missing",
                    message="售后工单缺少问题信息",
                )
            if request_type is None or eligibility is None:
                raise AppError(
                    status_code=500,
                    code="after_sales_eligibility_missing",
                    message="售后资格校验结果缺失",
                )
            if not self._control_allowed(
                chat_session,
                expected_control_version=expected_control_version,
            ):
                return self._waiting_for_agent_response(
                    chat_session=chat_session,
                    user_message=user_message,
                )
            ticket, ticket_created = AfterSalesTicketService(self.session).create_for_session(
                chat_session=chat_session,
                order=order,
                request_type=request_type,
                issue_description=issue_description,
                citations=rag_context.citations,
                eligibility=eligibility,
            )

        history = self._history_for_model(chat_session.id)
        answer = await self.answer_service.generate(
            question=content,
            intent=intent_result.intent.value,
            order_facts=order_facts,
            rag_context=rag_context,
            history=history,
            eligibility=eligibility,
        )
        rule_decision = self.rules.enforce(
            answer=answer,
            intent=intent_result.intent,
            order_facts=order_facts,
            policy_grounded=rag_context.grounded,
        )
        if rule_decision.handoff_required:
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=rule_decision.handoff_reason or "售后安全规则触发",
                source=HandoffSource.RULE,
                answer=rule_decision.answer,
                eligibility=eligibility,
                expected_control_version=expected_control_version,
                after_sales_ticket=ticket,
                tool_results=[
                    ToolResultSummary(
                        tool_name=tool_result.tool_name,
                        status="success",
                        result=order_facts,
                    )
                ],
            )

        return self._finish_with_answer(
            chat_session=chat_session,
            user_message=user_message,
            answer=rule_decision.answer,
            rag_context=rag_context,
            eligibility=eligibility,
            expected_control_version=expected_control_version,
            after_sales_ticket=ticket,
            ticket_created=ticket_created,
            tool_results=[
                ToolResultSummary(
                    tool_name=tool_result.tool_name,
                    status="success",
                    result=order_facts,
                )
            ],
        )

    async def _handle_policy_task(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        content: str,
        intent_result: IntentResult,
        expected_control_version: int,
    ) -> ChatTurnResponse:
        rag_context = await self._retrieve_policy(
            content=content,
            intent_result=intent_result,
            product_id=self._product_id_from_slots(chat_session),
        )
        rule_decision = self.rules.enforce(
            answer="",
            intent=intent_result.intent,
            order_facts=None,
            policy_grounded=rag_context.grounded,
        )
        if rule_decision.handoff_required:
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=rule_decision.handoff_reason or "缺少政策依据",
                source=HandoffSource.RULE,
                answer=rule_decision.answer,
                expected_control_version=expected_control_version,
            )

        answer = await self.answer_service.generate(
            question=content,
            intent=intent_result.intent.value,
            order_facts=None,
            rag_context=rag_context,
            history=self._history_for_model(chat_session.id),
            eligibility=None,
        )
        rule_decision = self.rules.enforce(
            answer=answer,
            intent=intent_result.intent,
            order_facts=None,
            policy_grounded=rag_context.grounded,
        )
        if rule_decision.handoff_required:
            return self._create_handoff_turn(
                chat_session=chat_session,
                user_message=user_message,
                reason=rule_decision.handoff_reason or "售后安全规则触发",
                source=HandoffSource.RULE,
                answer=rule_decision.answer,
                expected_control_version=expected_control_version,
            )
        return self._finish_with_answer(
            chat_session=chat_session,
            user_message=user_message,
            answer=rule_decision.answer or NO_EVIDENCE_ANSWER,
            rag_context=rag_context,
            expected_control_version=expected_control_version,
        )

    async def _plan_order_tool(self, *, content: str, order_no: str) -> ToolCallPlan:
        tools = [
            schema
            for schema in self.tools.model_schemas()
            if schema["function"]["name"] == GET_MY_ORDER
        ]
        try:
            raw_plan = await self.llm.plan_tool_call(message=content, tools=tools)
        except AppError:
            logger.warning("Tool planning degraded to deterministic order lookup")
            raw_plan = None

        if raw_plan is None:
            return ToolCallPlan(
                name=GET_MY_ORDER,
                arguments={"order_no": order_no},
            )

        try:
            plan = ToolCallPlan.model_validate(raw_plan)
        except ValidationError:
            raise AppError(
                status_code=422,
                code="tool_call_invalid",
                message="模型返回的工具参数不合法",
            ) from None
        if plan.name != GET_MY_ORDER:
            raise AppError(
                status_code=400,
                code="tool_not_allowed",
                message="工具调用不被允许",
            )
        arguments = GetMyOrderArguments.model_validate(plan.arguments)
        return ToolCallPlan(
            name=plan.name,
            arguments=arguments.model_dump(mode="json"),
        )

    async def _retrieve_policy(
        self,
        *,
        content: str,
        intent_result: IntentResult,
        product_id: int | None,
    ) -> RAGContext:
        if intent_result.intent not in _POLICY_INTENTS:
            return RAGContext(
                evidence="",
                citations=[],
                chunks=(),
                grounded=False,
            )
        issue_type = intent_result.slots.issue_type
        issue_description = intent_result.slots.issue_description or ""
        query = f"{content} {issue_type or ''} {issue_description} 售后政策"
        return await self.rag_service.retrieve(
            question=query.strip(),
            product_id=product_id,
            categories=(
                KnowledgeCategory.BUSINESS_POLICY,
                KnowledgeCategory.SUPPORT_SOP,
                KnowledgeCategory.PRODUCT,
            ),
        )

    def _finish_with_answer(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        answer: str,
        rag_context: RAGContext,
        expected_control_version: int,
        tool_results: list[ToolResultSummary] | None = None,
        eligibility: AfterSalesEligibility | None = None,
        after_sales_ticket: AfterSalesTicket | None = None,
        ticket_created: bool = False,
    ) -> ChatTurnResponse:
        if not self._control_allowed(
            chat_session,
            expected_control_version=expected_control_version,
        ):
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )
        if chat_session.workflow_state == WorkflowState.CHECKING_POLICY.value:
            chat_session = self.orchestrator.transition(
                session=self.session,
                chat_session=chat_session,
                target=WorkflowState.ANSWER_READY,
            )
        assistant_message = add_message(
            self.session,
            session_id=chat_session.id,
            sender_type=SenderType.ASSISTANT.value,
            content=answer,
            citations=[citation.model_dump(mode="json") for citation in rag_context.citations],
        )
        if chat_session.workflow_state == WorkflowState.ANSWER_READY.value:
            chat_session = self.orchestrator.transition(
                session=self.session,
                chat_session=chat_session,
                target=WorkflowState.RESOLVED,
            )
        return ChatTurnResponse(
            user_message=ChatMessageResponse.model_validate(user_message),
            assistant_message=ChatMessageResponse.model_validate(assistant_message),
            action=(
                ConversationAction.TICKET_CREATED if ticket_created else ConversationAction.ANSWER
            ),
            workflow_state=WorkflowState(chat_session.workflow_state),
            tool_results=tool_results or [],
            eligibility=(eligibility.to_response() if eligibility is not None else None),
            after_sales_ticket=(
                AfterSalesTicketResponse.model_validate(after_sales_ticket)
                if after_sales_ticket is not None
                else None
            ),
        )

    def _create_handoff_turn(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        reason: str,
        source: HandoffSource,
        answer: str | None = None,
        eligibility: AfterSalesEligibility | None = None,
        expected_control_version: int | None = None,
        after_sales_ticket: AfterSalesTicket | None = None,
        tool_results: list[ToolResultSummary] | None = None,
        rag_context: RAGContext | None = None,
    ) -> ChatTurnResponse:
        if expected_control_version is not None and not self._control_allowed(
            chat_session,
            expected_control_version=expected_control_version,
        ):
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )
        handoff, created = HandoffService(self.session).ensure_handoff(
            chat_session=chat_session,
            reason=reason,
            source=source,
        )
        assistant_message = None
        if answer:
            assistant_message = add_message(
                self.session,
                session_id=chat_session.id,
                sender_type=SenderType.ASSISTANT.value,
                content=answer,
                citations=(
                    [citation.model_dump(mode="json") for citation in rag_context.citations]
                    if rag_context is not None
                    else []
                ),
            )
        return ChatTurnResponse(
            user_message=ChatMessageResponse.model_validate(user_message),
            assistant_message=(
                ChatMessageResponse.model_validate(assistant_message) if assistant_message else None
            ),
            action=(
                ConversationAction.HANDOFF_CREATED
                if created
                else ConversationAction.WAITING_FOR_AGENT
            ),
            workflow_state=WorkflowState.NEED_HUMAN,
            tool_results=tool_results or [],
            eligibility=(eligibility.to_response() if eligibility is not None else None),
            after_sales_ticket=(
                AfterSalesTicketResponse.model_validate(after_sales_ticket)
                if after_sales_ticket is not None
                else None
            ),
            handoff=HandoffResponse.model_validate(handoff),
        )

    def _fail_to_handoff(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        reason: str,
        expected_control_version: int | None = None,
    ) -> ChatTurnResponse:
        ticket = get_ticket_by_session(
            self.session,
            session_id=chat_session.id,
        )
        return self._create_handoff_turn(
            chat_session=chat_session,
            user_message=user_message,
            reason=reason,
            source=HandoffSource.AI,
            answer=("当前 AI 服务暂时无法稳定处理这个问题。你的消息已保存，并已为你转接人工客服。"),
            expected_control_version=expected_control_version,
            after_sales_ticket=ticket,
        )

    def _save_turn(
        self,
        *,
        chat_session: ChatSession,
        user_message,
        answer: str,
        action: ConversationAction,
        missing_slots: list[str],
        expected_control_version: int,
        tool_results: list[ToolResultSummary] | None = None,
    ) -> ChatTurnResponse:
        if not self._control_allowed(
            chat_session,
            expected_control_version=expected_control_version,
        ):
            return self._waiting_for_agent_response(
                chat_session=chat_session,
                user_message=user_message,
            )
        assistant_message = add_message(
            self.session,
            session_id=chat_session.id,
            sender_type=SenderType.ASSISTANT.value,
            content=answer,
        )
        return ChatTurnResponse(
            user_message=ChatMessageResponse.model_validate(user_message),
            assistant_message=ChatMessageResponse.model_validate(assistant_message),
            action=action,
            workflow_state=WorkflowState(chat_session.workflow_state),
            missing_slots=missing_slots,
            tool_results=tool_results or [],
        )

    def _waiting_for_agent_response(
        self,
        *,
        chat_session: ChatSession,
        user_message,
    ) -> ChatTurnResponse:
        handoff = get_handoff_by_session(
            self.session,
            session_id=chat_session.id,
        )
        if handoff is None:
            handoff = HandoffService(self.session).ensure_handoff(
                chat_session=chat_session,
                reason="等待人工客服处理",
                source=HandoffSource.USER,
            )[0]
        return ChatTurnResponse(
            user_message=ChatMessageResponse.model_validate(user_message),
            assistant_message=None,
            action=ConversationAction.WAITING_FOR_AGENT,
            workflow_state=WorkflowState.NEED_HUMAN,
            handoff=HandoffResponse.model_validate(handoff),
        )

    def _control_allowed(
        self,
        chat_session: ChatSession,
        *,
        expected_control_version: int,
    ) -> bool:
        self.session.refresh(chat_session)
        return (
            chat_session.status == SessionStatus.OPEN.value
            and chat_session.control_version == expected_control_version
        )

    def _preserve_active_task(self, result: IntentResult) -> IntentResult:
        issue_type = result.slots.issue_type
        if issue_type == IssueType.RETURN and result.intent != AfterSalesIntent.HUMAN_REQUEST:
            result.intent = AfterSalesIntent.RETURN_REQUEST
        elif issue_type == IssueType.EXCHANGE and result.intent != AfterSalesIntent.HUMAN_REQUEST:
            result.intent = AfterSalesIntent.EXCHANGE_REQUEST
        return result

    def _history_for_model(self, session_id: int) -> list[dict[str, str]]:
        return [
            {
                "role": message.sender_type,
                "content": message.content,
            }
            for message in list_messages(self.session, session_id=session_id)
            if message.sender_type != SenderType.SYSTEM.value
        ]

    @staticmethod
    def _product_id_from_slots(chat_session: ChatSession) -> int | None:
        product_id = (chat_session.slots_json or {}).get("product_id")
        return product_id if isinstance(product_id, int) else None

    def _require_owned_session(self, *, session_id: int, user_id: int) -> ChatSession:
        chat_session = get_session_owned_by_user(
            self.session,
            session_id=session_id,
            user_id=user_id,
        )
        if chat_session is None:
            raise AppError(
                status_code=404,
                code="chat_session_not_found",
                message="会话不存在",
            )
        return chat_session
