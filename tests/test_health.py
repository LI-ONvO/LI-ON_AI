from app.core.config import settings


def test_health_returns_ok(client):
    res = client.get("/health")
    assert res.status_code == 200

    body = res.json()
    assert body["status"] == "ok"
    assert "model" in body


def _configure(monkeypatch, *, openai="sk-test", backend_url="http://backend.test", backend_key="k"):
    monkeypatch.setattr(settings, "openai_api_key", openai)
    monkeypatch.setattr(settings, "backend_api_base_url", backend_url)
    monkeypatch.setattr(settings, "backend_api_key", backend_key)


def test_ready_reports_missing_api_key(client, monkeypatch):
    _configure(monkeypatch, openai="")

    res = client.get("/ready")

    assert res.status_code == 503
    assert res.json()["missing"] == ["OPENAI_API_KEY"]


def test_ready_reports_missing_backend_config(client, monkeypatch):
    """자격증 조회를 백엔드 API 로 하므로, 없으면 거의 모든 답변이 실패한다."""
    _configure(monkeypatch, backend_url="", backend_key="")

    res = client.get("/ready")

    assert res.status_code == 503
    assert res.json()["missing"] == ["BACKEND_API_BASE_URL", "BACKEND_API_KEY"]


def test_ready_ok_when_configured(client, monkeypatch):
    _configure(monkeypatch)

    res = client.get("/ready")

    assert res.status_code == 200
    assert res.json()["status"] == "ready"
