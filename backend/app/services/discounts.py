from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import AppError
from backend.app.models import (
    DiscountAuthorizationRule,
    DiscountQuote,
    Product,
)
from backend.app.schemas.rag import CitationResponse
from backend.app.services.config_audit import record_config_change

QUOTE_VALIDITY = timedelta(minutes=30)


@dataclass(frozen=True)
class DiscountQuoteResult:
    quote: DiscountQuote
    authorized_discount_amount: Decimal
    requested_discount_amount: Decimal | None
    exceeds_authorization: bool
    rule: DiscountAuthorizationRule


class DiscountService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_rule_for_product(
        self,
        *,
        product_id: int,
    ) -> DiscountAuthorizationRule | None:
        statement = (
            select(DiscountAuthorizationRule)
            .where(
                DiscountAuthorizationRule.is_active.is_(True),
                (
                    (DiscountAuthorizationRule.product_id == product_id)
                    | DiscountAuthorizationRule.product_id.is_(None)
                ),
            )
            .order_by(
                DiscountAuthorizationRule.product_id.is_(None),
                DiscountAuthorizationRule.id,
            )
        )
        return self.session.scalar(statement)

    def create_quote(
        self,
        *,
        session_id: int,
        user_id: int,
        product: Product,
        citations: list[CitationResponse],
        requested_discount_amount: Decimal | None = None,
    ) -> DiscountQuoteResult:
        if not product.is_active or product.stock_quantity <= 0:
            raise AppError(
                status_code=409,
                code="discount_product_unavailable",
                message="商品当前不可售或库存不足，不能生成优惠报价",
            )
        if not citations:
            raise AppError(
                status_code=409,
                code="discount_policy_unavailable",
                message="没有可引用的优惠政策，不能生成授权报价",
            )
        rule = self.get_rule_for_product(product_id=product.id)
        if rule is None:
            raise AppError(
                status_code=409,
                code="discount_rule_unavailable",
                message="该商品没有可用的商家优惠授权",
            )

        rate_amount = (product.price * rule.max_discount_rate).quantize(Decimal("0.01"))
        authorized = min(
            rate_amount,
            rule.max_discount_amount,
            product.price,
        ).quantize(Decimal("0.01"))
        if authorized <= 0:
            raise AppError(
                status_code=409,
                code="discount_amount_unavailable",
                message="当前授权规则不能产生有效优惠金额",
            )

        requested = (
            requested_discount_amount.quantize(Decimal("0.01"))
            if requested_discount_amount is not None
            else None
        )
        if requested is not None and requested <= 0:
            raise AppError(
                status_code=422,
                code="invalid_discount_amount",
                message="期望优惠金额必须大于 0",
            )
        applied = min(requested, authorized) if requested is not None else authorized
        applied_rate = (applied / product.price).quantize(Decimal("0.0001"))
        final_price = (product.price - applied).quantize(Decimal("0.01"))

        quote = DiscountQuote(
            quote_no=f"DQ-{uuid4().hex[:12].upper()}",
            session_id=session_id,
            user_id=user_id,
            product_id=product.id,
            rule_id=rule.id,
            unit_price=product.price,
            discount_rate=applied_rate,
            discount_amount=applied,
            final_price=final_price,
            currency="CNY",
            policy_citations_json=[citation.model_dump(mode="json") for citation in citations],
            expires_at=datetime.now(UTC) + QUOTE_VALIDITY,
        )
        self.session.add(quote)
        self.session.commit()
        self.session.refresh(quote)
        return DiscountQuoteResult(
            quote=quote,
            authorized_discount_amount=authorized,
            requested_discount_amount=requested,
            exceeds_authorization=requested is not None and requested > authorized,
            rule=rule,
        )


class DiscountRuleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_rules(self) -> list[DiscountAuthorizationRule]:
        return list(
            self.session.scalars(
                select(DiscountAuthorizationRule).order_by(
                    DiscountAuthorizationRule.product_id,
                    DiscountAuthorizationRule.id,
                )
            )
        )

    def create_rule(
        self,
        *,
        actor_id: int,
        payload: dict,
    ) -> DiscountAuthorizationRule:
        product_id = payload.get("product_id")
        if product_id is not None and self.session.get(Product, product_id) is None:
            raise AppError(
                status_code=404,
                code="product_not_found",
                message="关联商品不存在",
            )
        if self.session.scalar(
            select(DiscountAuthorizationRule).where(
                DiscountAuthorizationRule.rule_code == payload["rule_code"]
            )
        ):
            raise AppError(
                status_code=409,
                code="discount_rule_code_exists",
                message="优惠规则编码已存在",
            )
        rule = DiscountAuthorizationRule(**payload)
        self.session.add(rule)
        self.session.flush()
        record_config_change(
            self.session,
            actor_id=actor_id,
            entity_type="discount_authorization_rule",
            entity_id=rule.id,
            action="create",
            before=None,
            after=self._snapshot(rule),
        )
        self.session.commit()
        self.session.refresh(rule)
        return rule

    def update_rule(
        self,
        *,
        rule_id: int,
        actor_id: int,
        updates: dict,
    ) -> DiscountAuthorizationRule:
        rule = self.session.get(DiscountAuthorizationRule, rule_id)
        if rule is None:
            raise AppError(
                status_code=404,
                code="discount_rule_not_found",
                message="优惠授权规则不存在",
            )
        before = self._snapshot(rule)
        changed = False
        for field_name, value in updates.items():
            if field_name == "product_id":
                if value is not None and self.session.get(Product, value) is None:
                    raise AppError(
                        status_code=404,
                        code="product_not_found",
                        message="关联商品不存在",
                    )
                if getattr(rule, field_name) != value:
                    setattr(rule, field_name, value)
                    changed = True
            elif value is not None and getattr(rule, field_name) != value:
                setattr(rule, field_name, value)
                changed = True
        if not changed:
            return rule
        rule.version += 1
        record_config_change(
            self.session,
            actor_id=actor_id,
            entity_type="discount_authorization_rule",
            entity_id=rule.id,
            action="update",
            before=before,
            after=self._snapshot(rule),
        )
        self.session.commit()
        self.session.refresh(rule)
        return rule

    @staticmethod
    def _snapshot(rule: DiscountAuthorizationRule) -> dict:
        return {
            "rule_code": rule.rule_code,
            "display_name": rule.display_name,
            "product_id": rule.product_id,
            "max_discount_rate": str(rule.max_discount_rate),
            "max_discount_amount": str(rule.max_discount_amount),
            "is_active": rule.is_active,
            "version": rule.version,
        }
