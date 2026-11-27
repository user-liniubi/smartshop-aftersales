from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.enums import (
    AfterSalesActorType,
    AfterSalesEligibilityStatus,
    AfterSalesTicketEventType,
    AfterSalesTicketStatus,
    AfterSalesTicketType,
    AgentDecisionStatus,
    RefundExecutionStatus,
)


class AfterSalesEligibilityResponse(BaseModel):
    result: AfterSalesEligibilityStatus
    reason_code: str
    explanation: str
    refund_amount: Decimal | None = None
    currency: str
    rule_version: str


class AgentDecisionResponse(BaseModel):
    scenario_code: str
    rule_version: int
    authorization_min: Decimal
    authorization_max: Decimal
    suggested_amount: Decimal | None
    available_amount: Decimal
    confidence: Decimal | None
    analysis: str
    validation: dict = Field(default_factory=dict)
    decision_status: AgentDecisionStatus

    model_config = ConfigDict(from_attributes=True)


class RefundExecutionResponse(BaseModel):
    id: int
    ticket_id: int
    ticket_no: str
    idempotency_key: str
    amount: Decimal
    currency: str
    status: RefundExecutionStatus
    attempt_count: int
    provider: str
    provider_reference: str | None
    failure_code: str | None
    failure_message: str | None
    requested_at: datetime
    executed_at: datetime | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AfterSalesTicketResponse(BaseModel):
    id: int
    ticket_no: str
    session_id: int
    user_id: int
    order_id: int
    request_type: AfterSalesTicketType
    issue_description: str
    policy_citations: list[dict] = Field(default_factory=list)
    eligibility_result: AfterSalesEligibilityStatus | None
    eligibility_reason: str | None
    refund_amount: Decimal | None
    currency: str
    rule_version: str | None
    status: AfterSalesTicketStatus
    reviewer_id: int | None
    review_note: str | None
    reviewed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by_id: int | None
    agent_decision: AgentDecisionResponse | None = None
    refund_execution: RefundExecutionResponse | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AfterSalesTicketReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    review_note: str = Field(default="", max_length=500)
    refund_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )


class AfterSalesTicketEventResponse(BaseModel):
    id: int
    ticket_id: int
    event_type: AfterSalesTicketEventType
    from_status: AfterSalesTicketStatus | None
    to_status: AfterSalesTicketStatus | None
    actor_type: AfterSalesActorType
    actor_id: int | None
    note: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RefundAuthorizationRuleResponse(BaseModel):
    id: int
    scenario_code: str
    display_name: str
    min_amount: Decimal
    max_amount: Decimal
    is_active: bool
    version: int

    model_config = ConfigDict(from_attributes=True)


class RefundAuthorizationRuleCreate(BaseModel):
    scenario_code: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9_-]+$",
    )
    display_name: str = Field(min_length=2, max_length=120)
    min_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    max_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_range(self):
        if self.max_amount < self.min_amount:
            raise ValueError("max_amount must be greater than or equal to min_amount")
        return self


class RefundAuthorizationRuleUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    min_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    max_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    is_active: bool | None = None


class CompensationDecisionOutput(BaseModel):
    scenario_code: str
    suggested_amount: Decimal = Field(gt=0)
    confidence: Decimal = Field(ge=0, le=1)
    analysis: str = Field(min_length=1, max_length=1000)
