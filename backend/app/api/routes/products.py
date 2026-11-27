from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies import CurrentUser
from backend.app.db.session import get_db
from backend.app.schemas.product import ProductResponse
from backend.app.services.products import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
def list_products(
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_db)],
    query: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[ProductResponse]:
    products = ProductService(session).search(query=query, limit=limit)
    return [ProductResponse.model_validate(product) for product in products]


@router.get("/compare", response_model=list[ProductResponse])
def compare_products(
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_db)],
    ids: Annotated[list[int], Query(min_length=2, max_length=4)],
) -> list[ProductResponse]:
    products = ProductService(session).compare(product_ids=ids)
    return [ProductResponse.model_validate(product) for product in products]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: Annotated[int, Path(gt=0)],
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_db)],
) -> ProductResponse:
    product = ProductService(session).get(product_id=product_id)
    return ProductResponse.model_validate(product)
