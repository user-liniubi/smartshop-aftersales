from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DiscountAuthorizationRuleResponse(BaseModel):
    id: int
    rule_code: str
    display_name: str
    product_id: int | None
    product_name: str | None = None
    max_discount_rate: Decimal
    max_discount_amount: Decimal
    is_active: bool
    version: int

    model_config = ConfigDict(from_attributes=True)


class DiscountAuthorizationRuleCreate(BaseModel):
    rule_code: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(min_length=2, max_length=120)
    product_id: int | None = Field(default=None, gt=0)
    max_discount_rate: Decimal = Field(gt=0, le=1, decimal_places=4)
    max_discount_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    is_active: bool = True


class DiscountAuthorizationRuleUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    product_id: int | None = Field(default=None, gt=0)
    max_discount_rate: Decimal | None = Field(
        default=None,
        gt=0,
        le=1,
        decimal_places=4,
    )
    max_discount_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    is_active: bool | None = None


class DiscountQuoteResponse(BaseModel):
    id: int
    quote_no: str
    session_id: int
    user_id: int
    product_id: int
    rule_id: int
    unit_price: Decimal
    discount_rate: Decimal
    discount_amount: Decimal
    final_price: Decimal
    currency: str
    policy_citations: list[dict] = Field(default_factory=list)
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
