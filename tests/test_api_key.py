"""X-API-Key 인증 테스트.

/v1 아래는 키가 있어야 하고, 상태 확인 엔드포인트는 키 없이도 열려 있어야 한다.
"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

BODY = {"sessionId": 1, "history": [], "content": "안녕"}


def _with_key(key: str | None):
    # HTTP 헤더는 ASCII 만 담을 수 있어 한글 값은 클라이언트 단에서 막힌다.
    return {"X-API-Key": key} if key else {}


def test_health_is_open_without_key():
    """배포 플랫폼이 상태를 확인해야 하므로 인증을 걸지 않는다."""
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_v1_rejects_missing_key():
    original = settings.api_key
    settings.api_key = "test-key"
    try:
        response = client.post("/v1/chat", json=BODY)
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"
    finally:
        settings.api_key = original


def test_v1_rejects_wrong_key():
    original = settings.api_key
    settings.api_key = "test-key"
    try:
        response = client.post("/v1/chat", json=BODY, headers=_with_key("wrong-key"))
        assert response.status_code == 401
    finally:
        settings.api_key = original


def test_v1_passes_auth_with_correct_key():
    """키가 맞으면 인증을 통과한다(그 뒤 DB·LLM 단계에서 실패하는 것과 무관하게 401이 아니다)."""
    original = settings.api_key
    settings.api_key = "test-key"
    try:
        response = client.post("/v1/chat", json=BODY, headers=_with_key("test-key"))
        assert response.status_code != 401
    finally:
        settings.api_key = original


def test_v1_refuses_when_server_key_not_configured():
    """키를 설정하지 않았으면 통과시키지 않는다. 조용히 무방비가 되는 것을 막는다."""
    original = settings.api_key
    settings.api_key = ""
    try:
        response = client.post("/v1/chat", json=BODY, headers=_with_key("anything"))
        assert response.status_code == 500
        assert response.json()["code"] == "API_KEY_NOT_CONFIGURED"
    finally:
        settings.api_key = original
