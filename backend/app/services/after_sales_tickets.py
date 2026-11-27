from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import AppError
from backend.app.models import (
    AfterSalesActorType,
    AfterSalesTicket,
    AfterSalesTicketEvent,
    AfterSalesTicketEventType,
    AfterSalesTicketStatus,
    AfterSalesTicketType,
    AgentDecision,
    AgentDecisionStatus,
    ChatMessage,
    ChatSession,
    Order,
    SenderType,
)
from backend.app.repositories.after_sales_tickets import (
    cancel_ticket_atomic,
    get_active_ticket_for_request,
    get_ticket_by_session,
    get_ticket_owned_by_user,
    list_pending_tickets,
    list_ticket_events,
    list_user_tickets,
    review_ticket_atomic,
)
from backend.app.repositories.refund_decisions import (
    approved_refund_total,
    get_agent_decision,
)
from backend.app.schemas.rag import CitationResponse
from backend.app.services.after_sales_eligibility import (
    AfterSalesEligibility,
    AfterSalesEligibilityService,
)
from backend.app.services.refund_decisions import RefundDecision
from backend.app.services.refund_executions import RefundExecutionService


class AfterSalesTicketService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_for_session(
        self,
        *,
        chat_session: ChatSession,
        order: Order,
        request_type: AfterSalesTicketType,
        issue_description: str,
        citations: list[CitationResponse],
        eligibility: AfterSalesEligibility | None = None,
    ) -> tuple[AfterSalesTicket, bool]:
        existing = get_ticket_by_session(
            self.session,
            session_id=chat_session.id,
        )
        if existing is not None:
            if existing.order_id != order.id or existing.request_type != request_type.value:
                raise AppError(
                    status_code=409,
                    code="after_sales_ticket_conflict",
                    message="当前会话已经提交了不同的售后工单",
                )
            return existing, False

        active_ticket = get_active_ticket_for_request(
            self.session,
            user_id=chat_session.user_id,
            order_id=order.id,
            request_type=request_type.value,
        )
        if active_ticket is not None:
            raise self._duplicate_request_error(active_ticket)

        eligibility = eligibility or AfterSalesEligibilityService().evaluate(
            order=order,
            request_type=request_type.value,
            issue_description=issue_description,
        )
        if eligibility.result.value == "need_human_review":
            raise AppError(
                status_code=409,
                code="after_sales_requires_manual_review",
                message=eligibility.explanation,
            )
        if eligibility.result.value == "not_eligible":
            raise AppError(
                status_code=409,
                code="after_sales_not_eligible",
                message=eligibility.explanation,
            )

        ticket = AfterSalesTicket(
            ticket_no=f"AS-{uuid4().hex[:12].upper()}",
            session_id=chat_session.id,
            user_id=chat_session.user_id,
            order_id=order.id,
            request_type=request_type.value,
            issue_description=issue_description,
            policy_citations_json=[citation.model_dump(mode="json") for citation in citations],
            eligibility_result=eligibility.result.value,
            eligibility_reason=eligibility.reason_code,
            refund_amount=eligibility.refund_amount,
            currency=eligibility.currency,
            rule_version=eligibility.rule_version,
            active_dedup_key=self._active_dedup_key(
                user_id=chat_session.user_id,
                order_id=order.id,
                request_type=request_type.value,
            ),
        )
        self.session.add(ticket)
        self.session.flush()
        self.session.add(
            AfterSalesTicketEvent(
                ticket_id=ticket.id,
                event_type=AfterSalesTicketEventType.CREATED.value,
                from_status=None,
                to_status=AfterSalesTicketStatus.PENDING_APPROVAL.value,
                actor_type=AfterSalesActorType.CONSUMER.value,
                actor_id=chat_session.user_id,
                note="消费者提交售后申请，系统完成订单和政策核验",
            )
        )
        self.session.add(
            ChatMessage(
                session_id=chat_session.id,
                sender_type=SenderType.SYSTEM.value,
                content=f"售后工单 {ticket.ticket_no} 已创建，当前等待人工审批。",
                citations_json=[],
            )
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = get_ticket_by_session(
                self.session,
                session_id=chat_session.id,
            )
            if existing is not None:
                return existing, False
            active_ticket = get_active_ticket_for_request(
                self.session,
                user_id=chat_session.user_id,
                order_id=order.id,
                request_type=request_type.value,
            )
            if active_ticket is not None:
                raise self._duplicate_request_error(active_ticket) from None
            raise
        self.session.refresh(ticket)
        return ticket, True

    def list_for_user(self, *, user_id: int) -> list[AfterSalesTicket]:
        return list_user_tickets(self.session, user_id=user_id)

    def create_compensation_for_session(
        self,
        *,
        chat_session: ChatSession,
        order: Order,
        issue_description: str,
        citations: list[CitationResponse],
        eligibility: AfterSalesEligibility,
        decision: RefundDecision,
    ) -> tuple[AfterSalesTicket, AgentDecision, bool]:
        existing = get_ticket_by_session(self.session, session_id=chat_session.id)
        if existing is not None:
            raise self._duplicate_request_error(existing)
        active_ticket = get_active_ticket_for_request(
            self.session,
            user_id=chat_session.user_id,
            order_id=order.id,
            request_type=AfterSalesTicketType.COMPENSATION.value,
        )
        if active_ticket is not None:
            raise self._duplicate_request_error(active_ticket)

        auto_approved = decision.decision_status == AgentDecisionStatus.AUTO_APPROVED
        ticket = AfterSalesTicket(
            ticket_no=f"AS-{uuid4().hex[:12].upper()}",
            session_id=chat_session.id,
            user_id=chat_session.user_id,
            order_id=order.id,
            request_type=AfterSalesTicketType.COMPENSATION.value,
            issue_description=issue_description,
            policy_citations_json=[citation.model_dump(mode="json") for citation in citations],
            eligibility_result=eligibility.result.value,
            eligibility_reason=eligibility.reason_code,
            refund_amount=decision.suggested_amount if auto_approved else None,
            currency=eligibility.currency,
            rule_version=eligibility.rule_version,
            active_dedup_key=self._active_dedup_key(
                user_id=chat_session.user_id,
                order_id=order.id,
                request_type=AfterSalesTicketType.COMPENSATION.value,
            ),
            status=(
                AfterSalesTicketStatus.APPROVED.value
                if auto_approved
                else AfterSalesTicketStatus.PENDING_APPROVAL.value
            ),
            review_note="Agent 授权范围内自动通过" if auto_approved else None,
            reviewed_at=datetime.now(UTC) if auto_approved else None,
        )
        self.session.add(ticket)
        self.session.flush()
        agent_decision = AgentDecision(
            ticket_id=ticket.id,
            scenario_code=decision.scenario_code,
            rule_version=decision.rule_version,
            authorization_min=decision.authorization_min,
            authorization_max=decision.authorization_max,
            suggested_amount=decision.suggested_amount,
            available_amount=decision.available_amount,
            confidence=decision.confidence,
            analysis=decision.analysis,
            policy_citations_json=[citation.model_dump(mode="json") for citation in citations],
            validation_json=decision.validation,
            decision_status=decision.decision_status.value,
        )
        self.session.add(agent_decision)
        self.session.add(
            AfterSalesTicketEvent(
                ticket_id=ticket.id,
                event_type=AfterSalesTicketEventType.CREATED.value,
                from_status=None,
                to_status=AfterSalesTicketStatus.PENDING_APPROVAL.value,
                actor_type=AfterSalesActorType.CONSUMER.value,
                actor_id=chat_session.user_id,
                note="消费者提交部分退款补偿申请",
            )
        )
        if auto_approved:
            self.session.add(
                AfterSalesTicketEvent(
                    ticket_id=ticket.id,
                    event_type=AfterSalesTicketEventType.APPROVED.value,
                    from_status=AfterSalesTicketStatus.PENDING_APPROVAL.value,
                    to_status=AfterSalesTicketStatus.APPROVED.value,
                    actor_type=AfterSalesActorType.AI.value,
                    actor_id=None,
                    note="Agent 建议金额通过商家授权范围和余额校验",
                )
            )
        message = (
            f"售后工单 {ticket.ticket_no} 已在商家授权范围内自动通过，"
            f"建议补偿金额 {decision.suggested_amount} {eligibility.currency}。"
            if auto_approved
            else f"售后工单 {ticket.ticket_no} 已创建，Agent 建议需人工审核。"
        )
        self.session.add(
            ChatMessage(
                session_id=chat_session.id,
                sender_type=SenderType.SYSTEM.value,
                content=message,
                citations_json=[],
            )
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = get_ticket_by_session(self.session, session_id=chat_session.id)
            if existing is not None:
                raise self._duplicate_request_error(existing) from None
            raise
        self.session.refresh(ticket)
        self.session.refresh(agent_decision)
        if auto_approved and ticket.refund_amount is not None and ticket.refund_amount > 0:
            RefundExecutionService(self.session).execute_for_ticket(ticket_id=ticket.id)
            self.session.refresh(ticket)
        return ticket, agent_decision, auto_approved

    def list_pending(self) -> list[AfterSalesTicket]:
        return list_pending_tickets(self.session)

    def get_for_user(self, *, ticket_id: int, user_id: int) -> AfterSalesTicket:
        ticket = get_ticket_owned_by_user(
            self.session,
            ticket_id=ticket_id,
            user_id=user_id,
        )
        if ticket is None:
            raise AppError(
                status_code=404,
                code="after_sales_ticket_not_found",
                message="售后工单不存在",
            )
        return ticket

    def list_events(
        self,
        *,
        ticket_id: int,
        user_id: int,
    ) -> list[AfterSalesTicketEvent]:
        self.get_for_user(ticket_id=ticket_id, user_id=user_id)
        return list_ticket_events(self.session, ticket_id=ticket_id)

    def cancel(self, *, ticket_id: int, user_id: int) -> AfterSalesTicket:
        ticket = self.get_for_user(ticket_id=ticket_id, user_id=user_id)
        if ticket.status != AfterSalesTicketStatus.PENDING_APPROVAL.value:
            raise AppError(
                status_code=409,
                code="after_sales_ticket_not_cancellable",
                message="只有待审批工单可以由消费者取消",
            )
        cancelled = cancel_ticket_atomic(
            self.session,
            ticket_id=ticket_id,
            user_id=user_id,
        )
        if cancelled is None:
            raise AppError(
                status_code=409,
                code="after_sales_ticket_cancel_conflict",
                message="工单状态已发生变化，请刷新后重试",
            )
        self.session.add(
            AfterSalesTicketEvent(
                ticket_id=ticket_id,
                event_type=AfterSalesTicketEventType.CANCELLED.value,
                from_status=AfterSalesTicketStatus.PENDING_APPROVAL.value,
                to_status=AfterSalesTicketStatus.CANCELLED.value,
                actor_type=AfterSalesActorType.CONSUMER.value,
                actor_id=user_id,
                note="消费者取消待审批售后申请",
            )
        )
        self.session.add(
            ChatMessage(
                session_id=ticket.session_id,
                sender_type=SenderType.SYSTEM.value,
                content=f"售后工单 {ticket.ticket_no} 已由消费者取消。",
                citations_json=[],
            )
        )
        self.session.commit()
        self.session.refresh(cancelled)
        return cancelled

    def review(
        self,
        *,
        ticket_id: int,
        reviewer_id: int,
        decision: str,
        review_note: str,
        refund_amount: Decimal | None = None,
    ) -> AfterSalesTicket:
        if decision == AfterSalesTicketStatus.REJECTED.value and not review_note.strip():
            raise AppError(
                status_code=422,
                code="review_note_required",
                message="拒绝工单时必须填写审批意见",
            )
        ticket = self.session.scalar(
            select(AfterSalesTicket).where(AfterSalesTicket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            raise AppError(
                status_code=404,
                code="after_sales_ticket_not_found",
                message="售后工单不存在",
            )
        if ticket.status != AfterSalesTicketStatus.PENDING_APPROVAL.value:
            self.session.rollback()
            raise AppError(
                status_code=409,
                code="after_sales_ticket_already_reviewed",
                message="该售后工单已被处理",
            )

        final_refund_amount: Decimal | None = None
        agent_decision = get_agent_decision(self.session, ticket_id=ticket.id)
        if ticket.request_type == AfterSalesTicketType.COMPENSATION.value:
            if agent_decision is None:
                raise AppError(
                    status_code=409,
                    code="agent_decision_missing",
                    message="补偿工单缺少 Agent 决策记录，不能审批",
                )
            if decision == AfterSalesTicketStatus.APPROVED.value:
                try:
                    final_refund_amount = self._resolve_manual_compensation_amount(
                        ticket=ticket,
                        agent_decision=agent_decision,
                        requested_amount=refund_amount,
                    )
                except AppError:
                    self.session.rollback()
                    raise
                agent_decision.decision_status = AgentDecisionStatus.MANUALLY_APPROVED.value
            else:
                agent_decision.decision_status = AgentDecisionStatus.REJECTED.value

        reviewed = review_ticket_atomic(
            self.session,
            ticket_id=ticket_id,
            reviewer_id=reviewer_id,
            decision=AfterSalesTicketStatus(decision),
            review_note=review_note.strip(),
            refund_amount=final_refund_amount,
        )
        if reviewed is None:
            self.session.rollback()
            existing = self.session.get(AfterSalesTicket, ticket_id)
            if existing is None:
                raise AppError(
                    status_code=404,
                    code="after_sales_ticket_not_found",
                    message="售后工单不存在",
                )
            raise AppError(
                status_code=409,
                code="after_sales_ticket_already_reviewed",
                message="该售后工单已被处理",
            )
        ticket = reviewed

        event_type = (
            AfterSalesTicketEventType.APPROVED
            if ticket.status == AfterSalesTicketStatus.APPROVED.value
            else AfterSalesTicketEventType.REJECTED
        )
        self.session.add(
            AfterSalesTicketEvent(
                ticket_id=ticket.id,
                event_type=event_type.value,
                from_status=AfterSalesTicketStatus.PENDING_APPROVAL.value,
                to_status=ticket.status,
                actor_type=AfterSalesActorType.AGENT.value,
                actor_id=reviewer_id,
                note=review_note.strip(),
            )
        )
        decision_label = (
            "通过审批" if event_type == AfterSalesTicketEventType.APPROVED else "被驳回"
        )
        note_suffix = f"审批意见：{review_note.strip()}" if review_note.strip() else ""
        self.session.add(
            ChatMessage(
                session_id=ticket.session_id,
                sender_type=SenderType.SYSTEM.value,
                content=(f"售后工单 {ticket.ticket_no} 已{decision_label}。{note_suffix}"),
                citations_json=[],
            )
        )
        self.session.commit()
        self.session.refresh(ticket)
        if (
            ticket.status == AfterSalesTicketStatus.APPROVED.value
            and ticket.refund_amount is not None
            and ticket.refund_amount > 0
        ):
            RefundExecutionService(self.session).execute_for_ticket(ticket_id=ticket.id)
            self.session.refresh(ticket)
        return ticket

    def _resolve_manual_compensation_amount(
        self,
        *,
        ticket: AfterSalesTicket,
        agent_decision: AgentDecision,
        requested_amount: Decimal | None,
    ) -> Decimal:
        amount = (
            requested_amount if requested_amount is not None else agent_decision.suggested_amount
        )
        if amount is None:
            raise AppError(
                status_code=422,
                code="refund_amount_required",
                message="人工通过补偿工单时必须填写最终退款金额",
            )
        amount = amount.quantize(Decimal("0.01"))
        if amount <= 0:
            raise AppError(
                status_code=422,
                code="invalid_refund_amount",
                message="最终退款金额必须大于 0",
            )

        order = self.session.scalar(
            select(Order).where(Order.id == ticket.order_id).with_for_update()
        )
        if order is None:
            raise AppError(
                status_code=404,
                code="order_not_found",
                message="售后工单关联订单不存在",
            )
        approved_total = approved_refund_total(
            self.session,
            order_id=order.id,
            exclude_ticket_id=ticket.id,
        )
        available = max(Decimal("0.00"), order.paid_amount - approved_total)
        if amount > available:
            raise AppError(
                status_code=409,
                code="refund_exceeds_available_balance",
                message="最终退款金额超过当前订单可退余额",
                details={
                    "requested_amount": str(amount),
                    "available_amount": str(available),
                    "currency": ticket.currency,
                },
            )
        return amount

    @staticmethod
    def _active_dedup_key(
        *,
        user_id: int,
        order_id: int,
        request_type: str,
    ) -> str:
        return f"{user_id}:{order_id}:{request_type}"

    @staticmethod
    def _duplicate_request_error(ticket: AfterSalesTicket) -> AppError:
        return AppError(
            status_code=409,
            code="duplicate_active_after_sales_request",
            message=(f"该订单已存在处理中或已审批的售后工单 {ticket.ticket_no}，请勿重复提交"),
        )
