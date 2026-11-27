from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.security import hash_password
from backend.app.db.session import Database
from backend.app.models import (
    DiscountAuthorizationRule,
    Order,
    OrderStatus,
    Product,
    RefundAuthorizationRule,
    User,
    UserRole,
)

DEMO_PASSWORD = "Demo123!"
AGENT_PASSWORD = "Agent123!"


@dataclass(frozen=True)
class DemoUser:
    username: str
    password: str
    role: UserRole


DEMO_USERS = (
    DemoUser("consumer_demo", DEMO_PASSWORD, UserRole.CONSUMER),
    DemoUser("consumer_other", DEMO_PASSWORD, UserRole.CONSUMER),
    DemoUser("agent_demo", AGENT_PASSWORD, UserRole.AGENT),
)

DEMO_PRODUCTS = (
    (
        "SmartShop 降噪耳机 Pro",
        "头戴式无线降噪耳机，演示商品",
        {"颜色": "曜石黑", "续航": "30 小时", "连接": "蓝牙 5.3"},
        Decimal("899.00"),
        35,
    ),
    (
        "SmartShop 机械键盘 K87",
        "87 键热插拔机械键盘，演示商品",
        {"轴体": "红轴", "布局": "87 键", "连接": "USB-C / 蓝牙"},
        Decimal("499.00"),
        24,
    ),
    (
        "SmartShop 27 英寸显示器",
        "2K 分辨率办公显示器，演示商品",
        {"尺寸": "27 英寸", "分辨率": "2560x1440", "接口": "HDMI / DP"},
        Decimal("1599.00"),
        12,
    ),
    (
        "SmartShop 14 英寸笔记本",
        "面向 Python 开发的轻薄笔记本，演示商品",
        {"内存": "16GB", "硬盘": "512GB SSD", "屏幕": "14 英寸 2.8K"},
        Decimal("5299.00"),
        8,
    ),
    (
        "SmartShop 无线鼠标 M2",
        "轻量无线办公鼠标，演示商品",
        {"连接": "2.4G / 蓝牙", "重量": "65g", "续航": "90 天"},
        Decimal("199.00"),
        50,
    ),
)

DEMO_ORDERS = (
    ("A10086", "consumer_demo", "SmartShop 降噪耳机 Pro", OrderStatus.DELIVERED),
    ("A10087", "consumer_demo", "SmartShop 机械键盘 K87", OrderStatus.SHIPPED),
    ("A10088", "consumer_other", "SmartShop 27 英寸显示器", OrderStatus.DELIVERED),
    ("A10089", "consumer_demo", "SmartShop 14 英寸笔记本", OrderStatus.CANCELLED),
    ("A10090", "consumer_other", "SmartShop 无线鼠标 M2", OrderStatus.DELIVERED),
)

DEMO_PRODUCT_PRICES = {
    "SmartShop 降噪耳机 Pro": Decimal("899.00"),
    "SmartShop 机械键盘 K87": Decimal("499.00"),
    "SmartShop 27 英寸显示器": Decimal("1599.00"),
    "SmartShop 14 英寸笔记本": Decimal("5299.00"),
    "SmartShop 无线鼠标 M2": Decimal("199.00"),
}

DEMO_REFUND_RULES = (
    ("cosmetic_minor", "轻微外观瑕疵", Decimal("0.00"), Decimal("50.00")),
    ("missing_accessory", "配件缺失", Decimal("0.00"), Decimal("150.00")),
    ("functional_issue", "功能异常", Decimal("0.00"), Decimal("300.00")),
    ("severe_failure", "严重故障", Decimal("0.00"), Decimal("500.00")),
)

DEMO_DISCOUNT_RULES = (
    (
        "headphones_launch",
        "耳机新品咨询优惠",
        "SmartShop 降噪耳机 Pro",
        Decimal("0.1000"),
        Decimal("80.00"),
    ),
    (
        "keyboard_office",
        "键盘办公场景优惠",
        "SmartShop 机械键盘 K87",
        Decimal("0.0800"),
        Decimal("40.00"),
    ),
    (
        "monitor_display",
        "显示器咨询优惠",
        "SmartShop 27 英寸显示器",
        Decimal("0.0500"),
        Decimal("80.00"),
    ),
    (
        "laptop_dev",
        "笔记本开发者咨询优惠",
        "SmartShop 14 英寸笔记本",
        Decimal("0.0300"),
        Decimal("150.00"),
    ),
    (
        "mouse_accessory",
        "鼠标配件优惠",
        "SmartShop 无线鼠标 M2",
        Decimal("0.0500"),
        Decimal("10.00"),
    ),
)


def seed_demo_data(session: Session) -> dict[str, int]:
    """Insert or reuse demo records and return current table counts."""

    users: dict[str, User] = {}
    for spec in DEMO_USERS:
        user = session.scalar(select(User).where(User.username == spec.username))
        if user is None:
            user = User(
                username=spec.username,
                password_hash=hash_password(spec.password),
                role=spec.role.value,
            )
            session.add(user)
            session.flush()
        users[spec.username] = user

    products: dict[str, Product] = {}
    for name, description, specs, price, stock_quantity in DEMO_PRODUCTS:
        product = session.scalar(select(Product).where(Product.name == name))
        if product is None:
            product = Product(
                name=name,
                description=description,
                specs_json=specs,
                price=price,
                stock_quantity=stock_quantity,
            )
            session.add(product)
            session.flush()
        else:
            product.specs_json = product.specs_json or specs
            product.price = product.price if product.price > 0 else price
            if product.stock_quantity == 0:
                product.stock_quantity = stock_quantity
        products[name] = product

    for order_no, username, product_name, status in DEMO_ORDERS:
        order = session.scalar(select(Order).where(Order.order_no == order_no))
        delivered_at = (
            datetime.now(UTC) - timedelta(days=3) if status == OrderStatus.DELIVERED else None
        )
        if order is None:
            session.add(
                Order(
                    order_no=order_no,
                    user_id=users[username].id,
                    product_id=products[product_name].id,
                    status=status.value,
                    delivered_at=delivered_at,
                    paid_amount=DEMO_PRODUCT_PRICES[product_name],
                    shipping_amount=Decimal("0.00"),
                    currency="CNY",
                    carrier="顺丰速运",
                    tracking_no=f"SF{order_no[-8:]}",
                    logistics_status={
                        "delivered": "delivered",
                        "shipped": "in_transit",
                        "cancelled": "not_shipped",
                    }.get(status.value, "not_shipped"),
                    logistics_updated_at=datetime.now(UTC),
                )
            )
        else:
            if order.delivered_at is None and status == OrderStatus.DELIVERED:
                order.delivered_at = delivered_at
            if order.paid_amount is None or order.paid_amount == Decimal("0.00"):
                order.paid_amount = DEMO_PRODUCT_PRICES[product_name]
            order.currency = order.currency or "CNY"
            if order.logistics_status == "not_shipped" and status in {
                OrderStatus.SHIPPED,
                OrderStatus.DELIVERED,
            }:
                order.carrier = order.carrier or "顺丰速运"
                order.tracking_no = order.tracking_no or f"SF{order_no[-8:]}"
                order.logistics_status = (
                    "delivered" if status == OrderStatus.DELIVERED else "in_transit"
                )
                order.logistics_updated_at = datetime.now(UTC)

    for scenario_code, display_name, min_amount, max_amount in DEMO_REFUND_RULES:
        rule = session.scalar(
            select(RefundAuthorizationRule).where(
                RefundAuthorizationRule.scenario_code == scenario_code
            )
        )
        if rule is None:
            session.add(
                RefundAuthorizationRule(
                    scenario_code=scenario_code,
                    display_name=display_name,
                    min_amount=min_amount,
                    max_amount=max_amount,
                )
            )

    for (
        rule_code,
        display_name,
        product_name,
        max_discount_rate,
        max_discount_amount,
    ) in DEMO_DISCOUNT_RULES:
        rule = session.scalar(
            select(DiscountAuthorizationRule).where(
                DiscountAuthorizationRule.rule_code == rule_code
            )
        )
        if rule is None:
            session.add(
                DiscountAuthorizationRule(
                    rule_code=rule_code,
                    display_name=display_name,
                    product_id=products[product_name].id,
                    max_discount_rate=max_discount_rate,
                    max_discount_amount=max_discount_amount,
                )
            )

    session.commit()
    return {
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "products": session.scalar(select(func.count()).select_from(Product)) or 0,
        "orders": session.scalar(select(func.count()).select_from(Order)) or 0,
    }


def main() -> None:
    settings = get_settings()
    development_database = Database(
        settings.database_url,
        echo=settings.database_echo,
    )
    try:
        with development_database.session_factory() as session:
            counts = seed_demo_data(session)
    finally:
        development_database.dispose()

    print(
        "Demo data ready: "
        f"users={counts['users']}, "
        f"products={counts['products']}, "
        f"orders={counts['orders']}"
    )


if __name__ == "__main__":
    main()
