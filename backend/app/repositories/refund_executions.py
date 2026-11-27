from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.models import RefundExecution, RefundExecutionStatus


def get_refund_execution_by_ticket(
    session: Session,
    *,
    ticket_id: int,
) -> RefundExecution | None:
    return session.scalar(
        select(RefundExecution)
        .options(joinedload(RefundExecution.ticket))
        .where(RefundExecution.ticket_id == ticket_id)
        .execution_options(populate_existing=True)
    )


def list_failed_refund_executions(session: Session) -> list[RefundExecution]:
    statement = (
        select(RefundExecution)
        .options(joinedload(RefundExecution.ticket))
        .where(RefundExecution.status == RefundExecutionStatus.FAILED.value)
        .order_by(RefundExecution.updated_at.desc(), RefundExecution.id.desc())
    )
    return list(session.scalars(statement))
