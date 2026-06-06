def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_platform_configs(client):
    response = client.get("/api/accounts/platforms")
    assert response.status_code == 200
    platforms = response.json()
    assert len(platforms) == 4
    names = {p["platform"] for p in platforms}
    assert names == {"COCOS", "IOL", "MERCADO_PAGO", "PROMETEO"}
