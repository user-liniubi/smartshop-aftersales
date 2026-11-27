from sample_data.seed import DEMO_PASSWORD


def _login_headers(client) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "consumer_demo", "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_product_list_supports_search_and_realtime_facts(seeded_client):
    headers = _login_headers(seeded_client)

    response = seeded_client.get(
        "/products",
        headers=headers,
        params={"query": "降噪耳机"},
    )

    assert response.status_code == 200
    product = response.json()[0]
    assert product["name"] == "SmartShop 降噪耳机 Pro"
    assert product["price"] == "899.00"
    assert product["stock_quantity"] == 35
    assert product["specs_json"]["连接"] == "蓝牙 5.3"


def test_product_compare_returns_requested_products(seeded_client):
    headers = _login_headers(seeded_client)

    response = seeded_client.get(
        "/products/compare",
        headers=headers,
        params=[("ids", 1), ("ids", 2)],
    )

    assert response.status_code == 200
    assert [product["id"] for product in response.json()] == [1, 2]


def test_product_list_requires_authentication(client):
    response = client.get("/products")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
