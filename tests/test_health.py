from app.core.config import settings


def test_health_returns_ok(client):
    res = client.get("/health")
    assert res.status_code == 200

    body = res.json()
    assert body["status"] == "ok"
    assert "model" in body


def test_ready_reports_missing_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")

    res = client.get("/ready")

    assert res.status_code == 503
    assert res.json()["missing"] == ["OPENAI_API_KEY"]


def test_ready_ok_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    res = client.get("/ready")

    assert res.status_code == 200
    assert res.json()["status"] == "ready"
