from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import OrderStatus


class OrderProductResponse(BaseModel):
    id: int
    name: str
    description: str
    specs_json: dict
    price: Decimal
    stock_quantity: int

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    order_no: str
    status: OrderStatus
    product: OrderProductResponse
    delivered_at: datetime | None
    paid_amount: Decimal
    shipping_amount: Decimal
    currency: str
    carrier: str | None
    tracking_no: str | None
    logistics_status: str
    logistics_updated_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
