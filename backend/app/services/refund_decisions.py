import json
from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import AppError
from backend.app.models import (
    AgentDecisionStatus,
    Order,
    RefundAuthorizationRule,
)
from backend.app.repositories.refund_decisions import (
    approved_refund_total,
    list_active_refund_rules,
)
from backend.app.schemas.after_sales import CompensationDecisionOutput
from backend.app.services.config_audit import record_config_change
from backend.app.services.llm import DeepSeekClient
from backend.app.services.rag import RAGContext

AUTO_APPROVAL_CONFIDENCE = Decimal("0.80")


@dataclass(frozen=True)
class RefundDecision:
    scenario_code: str
    rule_version: int
    authorization_min: Decimal
    authorization_max: Decimal
    suggested_amount: Decimal | None
    available_amount: Decimal
    confidence: Decimal | None
    analysis: str
    validation: dict
    decision_status: AgentDecisionStatus


class RefundDecisionService:
    def __init__(self, *, session: Session, llm: DeepSeekClient) -> None:
        self.session = session
        self.llm = llm

    async def evaluate(
        self,
        *,
        order: Order,
        issue_description: str,
        rag_context: RAGContext,
    ) -> RefundDecision:
        rules = list_active_refund_rules(self.session)
        available = max(
            Decimal("0.00"),
            order.paid_amount - approved_refund_total(self.session, order_id=order.id),
        )
        if not rules:
            return self._manual(
                analysis="商家尚未配置可用的退款授权规则。",
                available=available,
            )

        raw = await self.llm.propose_compensation(
            issue_description=issue_description,
            order_facts={
                "order_no": order.order_no,
                "product_name": order.product.name,
                "order_status": order.status,
                "paid_amount": str(order.paid_amount),
                "available_amount": str(available),
            },
            evidence=rag_context.evidence,
            rules=[
                {
                    "scenario_code": rule.scenario_code,
                    "display_name": rule.display_name,
                    "min_amount": str(rule.min_amount),
                    "max_amount": str(rule.max_amount),
                    "version": rule.version,
                }
                for rule in rules
            ],
        )
        try:
            payload = _load_json_object(raw)
            output = CompensationDecisionOutput.model_validate(payload)
            rule = next(
                (item for item in rules if item.scenario_code == output.scenario_code),
                None,
            )
        except (json.JSONDecodeError, ValidationError, ValueError):
            return self._manual(
                analysis="Agent 返回的补偿建议无法通过结构化校验。",
                available=available,
            )

        if rule is None:
            return self._manual(
                analysis="Agent 选择了不存在的授权场景。",
                available=available,
            )

        checks = {
            "scenario_allowed": True,
            "within_authorization": rule.min_amount <= output.suggested_amount <= rule.max_amount,
            "within_available_balance": output.suggested_amount <= available,
            "positive_amount": output.suggested_amount > 0,
            "confidence_reached": output.confidence >= AUTO_APPROVAL_CONFIDENCE,
            "policy_evidence_present": rag_context.grounded and bool(rag_context.evidence),
        }
        approved = all(checks.values())
        return RefundDecision(
            scenario_code=rule.scenario_code,
            rule_version=rule.version,
            authorization_min=rule.min_amount,
            authorization_max=rule.max_amount,
            suggested_amount=output.suggested_amount,
            available_amount=available,
            confidence=output.confidence,
            analysis=output.analysis,
            validation=checks,
            decision_status=(
                AgentDecisionStatus.AUTO_APPROVED if approved else AgentDecisionStatus.MANUAL_REVIEW
            ),
        )

    @staticmethod
    def _manual(*, analysis: str, available: Decimal) -> RefundDecision:
        return RefundDecision(
            scenario_code="empty",
            rule_version=0,
            authorization_min=Decimal("0.00"),
            authorization_max=Decimal("0.00"),
            suggested_amount=None,
            available_amount=available,
            confidence=None,
            analysis=analysis,
            validation={"agent_output_valid": False},
            decision_status=AgentDecisionStatus.MANUAL_REVIEW,
        )


class RefundRuleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_rule(self, *, actor_id: int, payload: dict):
        existing = self.session.scalar(
            select(RefundAuthorizationRule).where(
                RefundAuthorizationRule.scenario_code == payload["scenario_code"]
            )
        )
        if existing is not None:
            raise AppError(
                status_code=409,
                code="refund_rule_code_exists",
                message="退款授权场景编码已存在",
            )
        rule = RefundAuthorizationRule(**payload)
        self.session.add(rule)
        self.session.flush()
        record_config_change(
            self.session,
            actor_id=actor_id,
            entity_type="refund_authorization_rule",
            entity_id=rule.id,
            action="create",
            before=None,
            after=self._snapshot(rule),
        )
        self.session.commit()
        self.session.refresh(rule)
        return rule

    def update_rule(self, *, rule_id: int, actor_id: int, updates: dict):
        rule = self.session.get(RefundAuthorizationRule, rule_id)
        if rule is None:
            raise AppError(
                status_code=404,
                code="refund_rule_not_found",
                message="退款授权规则不存在",
            )
        before = self._snapshot(rule)
        for field_name, value in updates.items():
            if value is not None and getattr(rule, field_name) != value:
                setattr(rule, field_name, value)
        if rule.max_amount < rule.min_amount:
            self.session.rollback()
            raise AppError(
                status_code=422,
                code="invalid_refund_rule_range",
                message="最高金额不得低于最低金额",
            )
        if before == self._snapshot(rule):
            return rule
        rule.version += 1
        record_config_change(
            self.session,
            actor_id=actor_id,
            entity_type="refund_authorization_rule",
            entity_id=rule.id,
            action="update",
            before=before,
            after=self._snapshot(rule),
        )
        self.session.commit()
        self.session.refresh(rule)
        return rule

    @staticmethod
    def _snapshot(rule: RefundAuthorizationRule) -> dict:
        return {
            "scenario_code": rule.scenario_code,
            "display_name": rule.display_name,
            "min_amount": str(rule.min_amount),
            "max_amount": str(rule.max_amount),
            "is_active": rule.is_active,
            "version": rule.version,
        }


def _load_json_object(raw: str) -> dict:
    stripped = raw.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Compensation decision must be an object")
    return payload
