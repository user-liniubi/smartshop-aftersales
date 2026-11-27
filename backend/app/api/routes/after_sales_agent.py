from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from backend.app.api.dependencies import AgentUser
from backend.app.db.session import get_db
from backend.app.repositories.refund_decisions import list_active_refund_rules
from backend.app.repositories.refund_executions import list_failed_refund_executions
from backend.app.schemas.after_sales import (
    AfterSalesTicketResponse,
    AfterSalesTicketReviewRequest,
    RefundAuthorizationRuleCreate,
    RefundAuthorizationRuleResponse,
    RefundAuthorizationRuleUpdate,
    RefundExecutionResponse,
)
from backend.app.services.after_sales_tickets import AfterSalesTicketService
from backend.app.services.refund_decisions import RefundRuleService
from backend.app.services.refund_executions import RefundExecutionService

router = APIRouter(prefix="/agent/after-sales", tags=["agent"])


@router.get(
    "/refund-authorization-rules",
    response_model=list[RefundAuthorizationRuleResponse],
)
def list_refund_authorization_rules(
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> list[RefundAuthorizationRuleResponse]:
    return [
        RefundAuthorizationRuleResponse.model_validate(rule)
        for rule in list_active_refund_rules(session)
    ]


@router.post(
    "/refund-authorization-rules",
    response_model=RefundAuthorizationRuleResponse,
)
def create_refund_authorization_rule(
    request: RefundAuthorizationRuleCreate,
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> RefundAuthorizationRuleResponse:
    rule = RefundRuleService(session).create_rule(
        actor_id=current_agent.id,
        payload=request.model_dump(),
    )
    return RefundAuthorizationRuleResponse.model_validate(rule)


@router.patch(
    "/refund-authorization-rules/{rule_id}",
    response_model=RefundAuthorizationRuleResponse,
)
def update_refund_authorization_rule(
    rule_id: Annotated[int, Path(gt=0)],
    request: RefundAuthorizationRuleUpdate,
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> RefundAuthorizationRuleResponse:
    rule = RefundRuleService(session).update_rule(
        rule_id=rule_id,
        actor_id=current_agent.id,
        updates=request.model_dump(exclude_unset=True),
    )
    return RefundAuthorizationRuleResponse.model_validate(rule)


@router.get("/tickets", response_model=list[AfterSalesTicketResponse])
def list_pending_after_sales_tickets(
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> list[AfterSalesTicketResponse]:
    tickets = AfterSalesTicketService(session).list_pending()
    return [AfterSalesTicketResponse.model_validate(ticket) for ticket in tickets]


@router.post(
    "/tickets/{ticket_id}/review",
    response_model=AfterSalesTicketResponse,
)
def review_after_sales_ticket(
    ticket_id: Annotated[int, Path(gt=0)],
    request: AfterSalesTicketReviewRequest,
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> AfterSalesTicketResponse:
    ticket = AfterSalesTicketService(session).review(
        ticket_id=ticket_id,
        reviewer_id=current_agent.id,
        decision=request.decision,
        review_note=request.review_note,
        refund_amount=request.refund_amount,
    )
    return AfterSalesTicketResponse.model_validate(ticket)


@router.get(
    "/refund-executions/failed",
    response_model=list[RefundExecutionResponse],
)
def list_failed_refund_executions_endpoint(
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> list[RefundExecutionResponse]:
    return [
        RefundExecutionResponse.model_validate(execution)
        for execution in list_failed_refund_executions(session)
    ]


@router.post(
    "/tickets/{ticket_id}/refund-execution/retry",
    response_model=RefundExecutionResponse,
)
def retry_refund_execution(
    ticket_id: Annotated[int, Path(gt=0)],
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> RefundExecutionResponse:
    execution = RefundExecutionService(session).execute_for_ticket(
        ticket_id=ticket_id,
        retry_failed=True,
    )
    return RefundExecutionResponse.model_validate(execution)
