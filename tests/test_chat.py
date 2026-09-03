from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import LLMTimeoutError, LLMUpstreamError


@pytest.fixture
def mock_chain(monkeypatch):
    """chat_service가 호출하는 체인을 교체한다."""

    def _apply(**kwargs) -> AsyncMock:
        mock = AsyncMock(**kwargs)
        monkeypatch.setattr("app.services.chat_service.run_chat_chain", mock)
        return mock

    return _apply


def test_chat_returns_ai_message(client, mock_chain, sample_history):
    mock_chain(return_value="주당 15시간이면 3개월 안에 가능합니다.")

    res = client.post(
        "/v1/chat",
        json={"sessionId": 1, "history": sample_history, "content": "3개월 안에 가능해?"},
    )

    assert res.status_code == 200
    assert res.json() == {"content": "주당 15시간이면 3개월 안에 가능합니다."}


def test_chat_passes_history_and_content_to_chain(client, mock_chain, sample_history):
    mock = mock_chain(return_value="응답")

    client.post(
        "/v1/chat",
        json={"sessionId": 7, "history": sample_history, "content": "언제부터 시작할까?"},
    )

    history_arg, content_arg, _jm_cd = mock.await_args.args
    assert content_arg == "언제부터 시작할까?"
    assert len(history_arg) == 2
    assert history_arg[0].content == "정보처리기능사 준비하려고 해"


def test_chat_accepts_empty_history(client, mock_chain):
    mock_chain(return_value="어떤 자격증을 준비하시나요?")

    res = client.post("/v1/chat", json={"sessionId": 1, "content": "안녕"})

    assert res.status_code == 200


def test_chat_timeout_maps_to_504(client, mock_chain):
    mock_chain(side_effect=LLMTimeoutError())

    res = client.post("/v1/chat", json={"sessionId": 1, "content": "질문"})

    assert res.status_code == 504
    assert res.json()["code"] == "LLM_TIMEOUT"


def test_chat_upstream_failure_maps_to_502(client, mock_chain):
    mock_chain(side_effect=LLMUpstreamError())

    res = client.post("/v1/chat", json={"sessionId": 1, "content": "질문"})

    assert res.status_code == 502
    assert res.json()["code"] == "LLM_UPSTREAM_ERROR"


def test_chat_rejects_empty_content(client):
    res = client.post("/v1/chat", json={"sessionId": 1, "content": ""})

    assert res.status_code == 422
    assert res.json()["code"] == "INVALID_REQUEST"


def test_chat_rejects_missing_session_id(client):
    res = client.post("/v1/chat", json={"content": "질문"})

    assert res.status_code == 422


def test_chat_rejects_unknown_sender(client):
    res = client.post(
        "/v1/chat",
        json={
            "sessionId": 1,
            "history": [{"sender": "SYSTEM", "content": "..."}],
            "content": "질문",
        },
    )

    assert res.status_code == 422
