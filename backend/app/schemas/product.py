from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductResponse(BaseModel):
    id: int
    name: str
    description: str
    specs_json: dict
    price: Decimal
    stock_quantity: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ProductUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=5000)
    specs_json: dict[str, str] | None = None
    price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    stock_quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None
