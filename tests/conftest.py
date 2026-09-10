"""테스트 공통 픽스처.

모든 테스트는 LLM을 모킹한다. 네트워크나 API 키 없이도 전부 통과해야 한다.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

# /v1 은 X-API-Key 를 요구한다. 인증 자체를 검증하는 tests/test_api_key.py 를 빼면
# 나머지 테스트의 관심사가 아니므로, 여기서 고정 키를 심고 클라이언트가 항상 붙여 보내게 한다.
TEST_API_KEY = "test-api-key"


@pytest.fixture(autouse=True)
def _api_key() -> Iterator[None]:
    original = settings.api_key
    settings.api_key = TEST_API_KEY
    yield
    settings.api_key = original


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, headers={"X-API-Key": TEST_API_KEY}) as test_client:
        yield test_client


@pytest.fixture
def sample_history() -> list[dict]:
    return [
        {"sender": "USER", "content": "정보처리기능사 준비하려고 해"},
        {"sender": "AI", "content": "언제까지 취득하는 게 목표인가요?"},
    ]
