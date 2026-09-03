"""챗봇의 도구 호출 경로 테스트.

기존 test_chat.py는 run_chat_chain을 통째로 모킹하므로 도구 루프를 거치지 않는다.
여기서는 모델과 DB만 모킹하고 루프 자체를 돌려서, 도구 결과가 모델에게 제대로
전달되는지와 무한 루프 방어가 동작하는지를 확인한다.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.chains.chat_chain import MAX_TOOL_ROUNDS, run_chat_chain
from app.core.exceptions import LLMOutputError
from app.schemas.chat import ChatMessage, Sender


class FakeModel:
    """ainvoke가 불릴 때마다 준비된 응답을 순서대로 돌려준다."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = responses
        self.calls: list[list] = []

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


@pytest.fixture
def patch_model(monkeypatch):
    def _apply(responses: list[AIMessage]) -> FakeModel:
        model = FakeModel(responses)
        monkeypatch.setattr("app.chains.chat_chain.get_chat_model", lambda **_: model)
        return model

    return _apply


@pytest.fixture
def patch_search(monkeypatch):
    def _apply(results: list[dict]) -> AsyncMock:
        mock = AsyncMock(return_value=results)
        monkeypatch.setattr("app.chains.tools.search_certifications", mock)
        return mock

    return _apply


def test_answers_without_tools_when_not_needed(patch_model):
    """도구를 부르지 않는 턴은 모델 호출 한 번으로 끝난다."""
    model = patch_model([AIMessage(content="어떤 분야에 관심이 있으신가요?")])

    answer = asyncio.run(run_chat_chain([], "안녕하세요"))

    assert answer == "어떤 분야에 관심이 있으신가요?"
    assert len(model.calls) == 1


def test_tool_result_is_passed_back_to_model(patch_model, patch_search):
    """검색 결과가 ToolMessage로 모델에게 전달되어야 한다."""
    patch_search([{"rank": 1, "jmCd": "6921", "jmNm": "프로그래밍기능사"}])
    model = patch_model([
        _tool_call("search_certifications", {"keywords": ["프로그래밍"]}),
        AIMessage(content="프로그래밍기능사를 추천드려요."),
    ])

    answer = asyncio.run(run_chat_chain([], "프로그래밍 자격증 알려줘"))

    assert answer == "프로그래밍기능사를 추천드려요."

    # 두 번째 호출에는 도구 호출 메시지와 그 결과가 짝으로 들어있어야 한다.
    second_call = model.calls[1]
    tool_messages = [m for m in second_call if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1

    payload = json.loads(tool_messages[0].content)
    assert payload["results"][0]["jmNm"] == "프로그래밍기능사"


def test_empty_search_tells_model_not_to_invent(patch_model, patch_search):
    """결과가 없으면 지어내지 말라는 안내가 도구 응답에 담긴다."""
    patch_search([])
    model = patch_model([
        _tool_call("search_certifications", {"keywords": ["없는자격증"]}),
        AIMessage(content="조회되지 않습니다."),
    ])

    asyncio.run(run_chat_chain([], "없는자격증 알려줘"))

    tool_message = [m for m in model.calls[1] if isinstance(m, ToolMessage)][0]
    payload = json.loads(tool_message.content)
    assert payload["count"] == 0
    assert "지어내지" in payload["note"]


def test_gives_up_after_too_many_tool_rounds(patch_model, patch_search):
    """모델이 도구만 계속 부르면 무한 루프에 빠지지 않고 실패시킨다."""
    patch_search([])
    model = patch_model([_tool_call("search_certifications", {"keywords": ["x"]})])

    with pytest.raises(LLMOutputError):
        asyncio.run(run_chat_chain([], "반복"))

    assert len(model.calls) == MAX_TOOL_ROUNDS


def test_history_is_sent_to_model(patch_model):
    """백엔드가 준 대화 이력이 모델 메시지로 변환돼 들어가야 한다."""
    model = patch_model([AIMessage(content="네")])
    history = [
        ChatMessage(sender=Sender.USER, content="정보처리기사 준비 중이야"),
        ChatMessage(sender=Sender.AI, content="언제 시험을 보시나요?"),
    ]

    asyncio.run(run_chat_chain(history, "8월이요"))

    contents = [getattr(m, "content", "") for m in model.calls[0]]
    assert "정보처리기사 준비 중이야" in contents
    assert "8월이요" in contents
