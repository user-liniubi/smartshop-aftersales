from decimal import Decimal

from sqlalchemy import select

from backend.app.models import ConfigAuditLog, DiscountAuthorizationRule
from sample_data.seed import AGENT_PASSWORD, DEMO_PASSWORD


def _login_headers(client, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_agent_manages_product_and_audit_is_recorded(
    seeded_client,
    test_database,
):
    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    consumer_headers = _login_headers(
        seeded_client,
        "consumer_demo",
        DEMO_PASSWORD,
    )

    denied = seeded_client.patch(
        "/agent/catalog/products/1",
        headers=consumer_headers,
        json={"stock_quantity": 10},
    )
    updated = seeded_client.patch(
        "/agent/catalog/products/1",
        headers=agent_headers,
        json={
            "description": "用于售前咨询演示的头戴式降噪耳机",
            "price": "879.00",
            "stock_quantity": 28,
            "is_active": True,
        },
    )
    audit_logs = seeded_client.get(
        "/agent/config/audit-logs",
        headers=agent_headers,
    )

    assert denied.status_code == 403
    assert updated.status_code == 200
    assert updated.json()["price"] == "879.00"
    assert updated.json()["stock_quantity"] == 28
    assert any(
        log["entity_type"] == "product" and log["entity_id"] == "1" and log["action"] == "update"
        for log in audit_logs.json()
    )


def test_agent_manages_discount_authorization_rules(
    seeded_client,
    test_database,
):
    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    created = seeded_client.post(
        "/agent/discounts/rules",
        headers=agent_headers,
        json={
            "rule_code": "headphones_test_campaign",
            "display_name": "耳机测试优惠",
            "product_id": 1,
            "max_discount_rate": "0.1200",
            "max_discount_amount": "90.00",
            "is_active": True,
        },
    )

    assert created.status_code == 200
    rule_id = created.json()["id"]
    updated = seeded_client.patch(
        f"/agent/discounts/rules/{rule_id}",
        headers=agent_headers,
        json={
            "max_discount_amount": "95.00",
            "is_active": False,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["max_discount_amount"] == "95.00"
    assert updated.json()["is_active"] is False
    assert updated.json()["version"] == 2
    with test_database.session_factory() as session:
        rule = session.scalar(
            select(DiscountAuthorizationRule).where(
                DiscountAuthorizationRule.rule_code == "headphones_test_campaign"
            )
        )
        audit_count = len(
            list(
                session.scalars(
                    select(ConfigAuditLog).where(
                        ConfigAuditLog.entity_type == "discount_authorization_rule"
                    )
                )
            )
        )
    assert rule is not None
    assert rule.max_discount_rate == Decimal("0.1200")
    assert audit_count == 2


def test_agent_manages_refund_authorization_rules(
    seeded_client,
    test_database,
):
    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    created = seeded_client.post(
        "/agent/after-sales/refund-authorization-rules",
        headers=agent_headers,
        json={
            "scenario_code": "packaging_damage",
            "display_name": "包装破损补偿",
            "min_amount": "0.00",
            "max_amount": "60.00",
            "is_active": True,
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    invalid = seeded_client.patch(
        f"/agent/after-sales/refund-authorization-rules/{rule_id}",
        headers=agent_headers,
        json={"max_amount": "20.00", "min_amount": "30.00"},
    )
    valid = seeded_client.patch(
        f"/agent/after-sales/refund-authorization-rules/{rule_id}",
        headers=agent_headers,
        json={"max_amount": "70.00"},
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_refund_rule_range"
    assert valid.status_code == 200
    assert valid.json()["max_amount"] == "70.00"
    assert valid.json()["version"] == 2
