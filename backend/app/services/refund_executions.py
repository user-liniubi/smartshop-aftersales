from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import AppError
from backend.app.models import (
    AfterSalesActorType,
    AfterSalesTicket,
    AfterSalesTicketEvent,
    AfterSalesTicketEventType,
    AfterSalesTicketStatus,
    ChatMessage,
    RefundExecution,
    RefundExecutionStatus,
    SenderType,
)
from backend.app.repositories.refund_executions import get_refund_execution_by_ticket

MAX_REFUND_EXECUTION_ATTEMPTS = 3


@dataclass(frozen=True)
class RefundGatewayResult:
    success: bool
    provider_reference: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class RefundGateway(Protocol):
    name: str

    def execute(
        self,
        *,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
    ) -> RefundGatewayResult: ...


class SimulatedRefundGateway:
    """Deterministic local gateway used only for development and testing."""

    name = "simulation"

    def execute(
        self,
        *,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
    ) -> RefundGatewayResult:
        if currency != "CNY":
            return RefundGatewayResult(
                success=False,
                failure_code="unsupported_currency",
                failure_message="模拟退款服务当前仅支持 CNY。",
            )
        reference = sha256(idempotency_key.encode("utf-8")).hexdigest()[:16].upper()
        return RefundGatewayResult(
            success=True,
            provider_reference=f"SIM-{reference}",
        )


class RefundExecutionService:
    def __init__(
        self,
        session: Session,
        *,
        gateway: RefundGateway | None = None,
        max_attempts: int = MAX_REFUND_EXECUTION_ATTEMPTS,
    ) -> None:
        self.session = session
        self.gateway = gateway or SimulatedRefundGateway()
        self.max_attempts = max_attempts

    def execute_for_ticket(
        self,
        *,
        ticket_id: int,
        retry_failed: bool = False,
    ) -> RefundExecution:
        ticket = self.session.scalar(
            select(AfterSalesTicket).where(AfterSalesTicket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            raise AppError(
                status_code=404,
                code="after_sales_ticket_not_found",
                message="售后工单不存在",
            )
        if ticket.status != AfterSalesTicketStatus.APPROVED.value:
            raise AppError(
                status_code=409,
                code="refund_ticket_not_approved",
                message="只有审批通过的工单才能进入退款执行",
            )
        if ticket.refund_amount is None or ticket.refund_amount <= 0:
            raise AppError(
                status_code=409,
                code="refund_amount_missing",
                message="工单没有可执行的正数退款金额",
            )

        execution = get_refund_execution_by_ticket(self.session, ticket_id=ticket_id)
        if execution is not None:
            if execution.status == RefundExecutionStatus.SUCCESS.value:
                return execution
            if not retry_failed:
                return execution
            execution = self._claim_retry(execution)
            if execution.status == RefundExecutionStatus.SUCCESS.value:
                return execution

        if execution is None:
            execution = self._create_pending(ticket)

        try:
            result = self.gateway.execute(
                idempotency_key=execution.idempotency_key,
                amount=execution.amount,
                currency=execution.currency,
            )
        except Exception:
            result = RefundGatewayResult(
                success=False,
                failure_code="gateway_exception",
                failure_message="退款服务调用失败，可安全重试。",
            )

        execution.provider = self.gateway.name
        if result.success:
            execution.status = RefundExecutionStatus.SUCCESS.value
            execution.provider_reference = result.provider_reference
            execution.failure_code = None
            execution.failure_message = None
            execution.executed_at = datetime.now(UTC)
            event_note = "模拟退款执行成功"
            message = (
                f"售后工单 {ticket.ticket_no} 的模拟退款已执行成功，"
                f"金额 {execution.amount} {execution.currency}。"
            )
        else:
            execution.status = RefundExecutionStatus.FAILED.value
            execution.provider_reference = None
            execution.failure_code = result.failure_code or "refund_execution_failed"
            execution.failure_message = result.failure_message or "退款执行失败"
            execution.executed_at = None
            event_note = (
                f"退款执行失败（第 {execution.attempt_count} 次）：{execution.failure_message}"
            )
            message = (
                f"售后工单 {ticket.ticket_no} 已审批通过，但模拟退款执行失败，"
                "系统已保留记录并支持有限重试。"
            )

        self.session.add(
            AfterSalesTicketEvent(
                ticket_id=ticket.id,
                event_type=AfterSalesTicketEventType.SYSTEM_NOTE.value,
                from_status=AfterSalesTicketStatus.APPROVED.value,
                to_status=AfterSalesTicketStatus.APPROVED.value,
                actor_type=AfterSalesActorType.SYSTEM.value,
                actor_id=None,
                note=event_note,
            )
        )
        self.session.add(
            ChatMessage(
                session_id=ticket.session_id,
                sender_type=SenderType.SYSTEM.value,
                content=message,
                citations_json=[],
            )
        )
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def _create_pending(self, ticket: AfterSalesTicket) -> RefundExecution:
        execution = RefundExecution(
            ticket_id=ticket.id,
            idempotency_key=f"after-sales:{ticket.ticket_no}:refund:v1",
            amount=ticket.refund_amount,
            currency=ticket.currency,
            status=RefundExecutionStatus.PENDING.value,
            attempt_count=1,
            provider=self.gateway.name,
        )
        self.session.add(execution)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = get_refund_execution_by_ticket(
                self.session,
                ticket_id=ticket.id,
            )
            if existing is None:
                raise
            return existing
        self.session.refresh(execution)
        return execution

    def _claim_retry(self, execution: RefundExecution) -> RefundExecution:
        if execution.attempt_count >= self.max_attempts:
            raise AppError(
                status_code=409,
                code="refund_retry_exhausted",
                message=f"退款执行已达到 {self.max_attempts} 次尝试上限，请人工核查",
            )
        result = self.session.execute(
            update(RefundExecution)
            .where(
                RefundExecution.id == execution.id,
                RefundExecution.status.in_(
                    [
                        RefundExecutionStatus.PENDING.value,
                        RefundExecutionStatus.FAILED.value,
                    ]
                ),
                RefundExecution.attempt_count < self.max_attempts,
            )
            .values(
                status=RefundExecutionStatus.PENDING.value,
                attempt_count=RefundExecution.attempt_count + 1,
                failure_code=None,
                failure_message=None,
                provider=self.gateway.name,
                updated_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )
        self.session.commit()
        if result.rowcount != 1:
            current = get_refund_execution_by_ticket(
                self.session,
                ticket_id=execution.ticket_id,
            )
            if current is not None and current.status == RefundExecutionStatus.SUCCESS.value:
                return current
            raise AppError(
                status_code=409,
                code="refund_retry_conflict",
                message="退款执行状态已变化，请刷新后重试",
            )
        refreshed = get_refund_execution_by_ticket(
            self.session,
            ticket_id=execution.ticket_id,
        )
        if refreshed is None:
            raise AppError(
                status_code=409,
                code="refund_execution_missing",
                message="退款执行记录不存在",
            )
        return refreshed
