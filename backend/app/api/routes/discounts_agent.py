from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from backend.app.api.dependencies import AgentUser
from backend.app.db.session import get_db
from backend.app.schemas.discount import (
    DiscountAuthorizationRuleCreate,
    DiscountAuthorizationRuleResponse,
    DiscountAuthorizationRuleUpdate,
)
from backend.app.services.discounts import DiscountRuleService

router = APIRouter(prefix="/agent/discounts", tags=["agent"])


def _response(rule) -> DiscountAuthorizationRuleResponse:
    return DiscountAuthorizationRuleResponse.model_validate(rule).model_copy(
        update={
            "product_name": rule.product.name if rule.product is not None else None,
        }
    )


@router.get(
    "/rules",
    response_model=list[DiscountAuthorizationRuleResponse],
)
def list_discount_rules(
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> list[DiscountAuthorizationRuleResponse]:
    return [_response(rule) for rule in DiscountRuleService(session).list_rules()]


@router.post(
    "/rules",
    response_model=DiscountAuthorizationRuleResponse,
)
def create_discount_rule(
    request: DiscountAuthorizationRuleCreate,
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> DiscountAuthorizationRuleResponse:
    rule = DiscountRuleService(session).create_rule(
        actor_id=current_agent.id,
        payload=request.model_dump(),
    )
    return _response(rule)


@router.patch(
    "/rules/{rule_id}",
    response_model=DiscountAuthorizationRuleResponse,
)
def update_discount_rule(
    rule_id: Annotated[int, Path(gt=0)],
    request: DiscountAuthorizationRuleUpdate,
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> DiscountAuthorizationRuleResponse:
    rule = DiscountRuleService(session).update_rule(
        rule_id=rule_id,
        actor_id=current_agent.id,
        updates=request.model_dump(exclude_unset=True),
    )
    return _response(rule)
