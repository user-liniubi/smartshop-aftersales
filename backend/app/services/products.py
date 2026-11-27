import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import AppError
from backend.app.models import Product
from backend.app.services.config_audit import record_config_change

_CHINESE_BIGRAM = re.compile(r"[\u4e00-\u9fff]{2}")


class ProductService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active(self, *, limit: int = 20) -> list[Product]:
        statement = (
            select(Product).where(Product.is_active.is_(True)).order_by(Product.id).limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_all(self, *, limit: int = 100) -> list[Product]:
        statement = select(Product).order_by(Product.id).limit(limit)
        return list(self.session.scalars(statement))

    def get(self, *, product_id: int) -> Product:
        product = self.session.get(Product, product_id)
        if product is None or not product.is_active:
            raise AppError(
                status_code=404,
                code="product_not_found",
                message="商品不存在",
            )
        return product

    def search(self, *, query: str, limit: int = 5) -> list[Product]:
        products = self.list_active()
        normalized = query.strip().lower()
        if not normalized:
            return products[:limit]
        tokens = set(_CHINESE_BIGRAM.findall(query)) | {
            token for token in re.split(r"\W+", normalized) if len(token) >= 2
        }
        scored: list[tuple[int, Product]] = []
        for product in products:
            haystack = (
                f"{product.name} {product.description} "
                + " ".join(f"{key} {value}" for key, value in product.specs_json.items())
            ).lower()
            score = sum(1 for token in tokens if token in haystack)
            if product.name.lower() in normalized:
                score += 5
            if score:
                scored.append((score, product))
        if not scored:
            return products[:limit]
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [product for _, product in scored[:limit]]

    def compare(self, *, product_ids: list[int]) -> list[Product]:
        unique_ids = list(dict.fromkeys(product_ids))
        if len(unique_ids) < 2:
            raise AppError(
                status_code=422,
                code="product_compare_requires_two",
                message="商品对比至少需要两个商品",
            )
        if len(unique_ids) > 4:
            raise AppError(
                status_code=422,
                code="product_compare_too_many",
                message="一次最多对比四个商品",
            )
        products = [self.get(product_id=product_id) for product_id in unique_ids]
        by_id = {product.id: product for product in products}
        return [by_id[product_id] for product_id in unique_ids]

    def update(self, *, product_id: int, actor_id: int, updates: dict) -> Product:
        product = self.session.get(Product, product_id)
        if product is None:
            raise AppError(
                status_code=404,
                code="product_not_found",
                message="商品不存在",
            )
        before = self._snapshot(product)
        for field_name, value in updates.items():
            if value is not None and getattr(product, field_name) != value:
                setattr(product, field_name, value)
        if before == self._snapshot(product):
            return product
        record_config_change(
            self.session,
            actor_id=actor_id,
            entity_type="product",
            entity_id=product.id,
            action="update",
            before=before,
            after=self._snapshot(product),
        )
        self.session.commit()
        self.session.refresh(product)
        return product

    @staticmethod
    def _snapshot(product: Product) -> dict:
        return {
            "name": product.name,
            "description": product.description,
            "specs_json": product.specs_json,
            "price": str(product.price),
            "stock_quantity": product.stock_quantity,
            "is_active": product.is_active,
        }
