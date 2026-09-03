"""테스트 공통 픽스처.

모든 테스트는 LLM을 모킹한다. 네트워크나 API 키 없이도 전부 통과해야 한다.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_history() -> list[dict]:
    return [
        {"sender": "USER", "content": "정보처리기능사 준비하려고 해"},
        {"sender": "AI", "content": "언제까지 취득하는 게 목표인가요?"},
    ]
