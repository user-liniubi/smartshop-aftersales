from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies import AgentUser
from backend.app.db.session import get_db
from backend.app.schemas.product import ProductResponse, ProductUpdate
from backend.app.services.products import ProductService

router = APIRouter(prefix="/agent/catalog", tags=["agent"])


@router.get("/products", response_model=list[ProductResponse])
def list_products_for_management(
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[ProductResponse]:
    return [
        ProductResponse.model_validate(product)
        for product in ProductService(session).list_all(limit=limit)
    ]


@router.patch("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: Annotated[int, Path(gt=0)],
    request: ProductUpdate,
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
) -> ProductResponse:
    product = ProductService(session).update(
        product_id=product_id,
        actor_id=current_agent.id,
        updates=request.model_dump(exclude_unset=True),
    )
    return ProductResponse.model_validate(product)
