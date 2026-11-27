from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    AfterSalesTicket,
    AfterSalesTicketStatus,
    AgentDecision,
    RefundAuthorizationRule,
)


def list_active_refund_rules(session: Session) -> list[RefundAuthorizationRule]:
    statement = (
        select(RefundAuthorizationRule)
        .where(RefundAuthorizationRule.is_active.is_(True))
        .order_by(RefundAuthorizationRule.id)
    )
    return list(session.scalars(statement))


def approved_refund_total(
    session: Session,
    *,
    order_id: int,
    exclude_ticket_id: int | None = None,
) -> Decimal:
    statement = select(func.coalesce(func.sum(AfterSalesTicket.refund_amount), 0)).where(
        AfterSalesTicket.order_id == order_id,
        AfterSalesTicket.status == AfterSalesTicketStatus.APPROVED.value,
    )
    if exclude_ticket_id is not None:
        statement = statement.where(AfterSalesTicket.id != exclude_ticket_id)
    total = session.scalar(statement)
    return Decimal(total or 0)


def get_agent_decision(session: Session, *, ticket_id: int) -> AgentDecision | None:
    return session.scalar(select(AgentDecision).where(AgentDecision.ticket_id == ticket_id))
