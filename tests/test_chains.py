"""체인 계층 유닛 테스트 (LLM 호출 없음)."""

import asyncio

import pytest
from openai import OpenAIError
from pydantic import BaseModel

from app.chains.base import build_messages, extract_text, trim_history
from app.core.config import settings
from app.core.exceptions import LLMOutputError, LLMTimeoutError, LLMUpstreamError
from app.core.llm import llm_call_guard
from app.prompts import load_prompt, render_prompt
from app.schemas.chat import ChatMessage, Sender


def msg(sender: str, content: str) -> ChatMessage:
    return ChatMessage(sender=Sender(sender), content=content)


# --------------------------------------------------------------------------
# 메시지 변환
# --------------------------------------------------------------------------


def test_build_messages_maps_sender_to_role():
    messages = build_messages("시스템", [msg("USER", "안녕"), msg("AI", "반가워요")], "질문")

    assert [type(m).__name__ for m in messages] == [
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
        "HumanMessage",
    ]
    assert messages[-1].content == "질문"


def test_build_messages_without_new_user_content():
    messages = build_messages("시스템", [msg("USER", "안녕")])

    assert len(messages) == 2


def test_trim_history_keeps_most_recent(monkeypatch):
    monkeypatch.setattr(settings, "max_history_messages", 3)
    history = [msg("USER", str(i)) for i in range(10)]

    trimmed = trim_history(history)

    assert [m.content for m in trimmed] == ["7", "8", "9"]


def test_trim_history_keeps_all_when_under_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_history_messages", 30)
    history = [msg("USER", str(i)) for i in range(5)]

    assert len(trim_history(history)) == 5


# --------------------------------------------------------------------------
# 응답 텍스트 추출
# --------------------------------------------------------------------------


def test_extract_text_from_plain_string():
    assert extract_text("  응답  ") == "응답"


def test_extract_text_from_content_blocks():
    blocks = [{"type": "text", "text": "앞"}, {"type": "text", "text": "뒤"}]
    assert extract_text(blocks) == "앞뒤"


def test_extract_text_ignores_non_text_blocks():
    blocks = [{"type": "image", "url": "..."}, {"type": "text", "text": "본문"}]
    assert extract_text(blocks) == "본문"


def test_extract_text_from_unexpected_type():
    assert extract_text(None) == ""


# --------------------------------------------------------------------------
# 프롬프트 로딩
# --------------------------------------------------------------------------


def test_prompts_exist():
    assert load_prompt("chat_system")
    assert load_prompt("roadmap_system")


def test_missing_prompt_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("존재하지_않는_프롬프트")


def test_render_prompt_substitutes_placeholders():
    rendered = render_prompt("roadmap_system", today="2026-08-06", min_steps="3", max_steps="8")

    assert "2026-08-06" in rendered
    assert "{today}" not in rendered
    assert "{min_steps}" not in rendered
    assert "{max_steps}" not in rendered


def test_chat_prompt_has_today_placeholder():
    rendered = render_prompt("chat_system", today="2026-08-06")

    assert "2026-08-06" in rendered
    assert "{today}" not in rendered


# --------------------------------------------------------------------------
# 예외 변환
# --------------------------------------------------------------------------


def run_in_guard(raise_exc: Exception | None = None, action=None) -> None:
    """llm_call_guard 안에서 예외를 발생시킨다. (플러그인 없이 async 테스트)"""

    async def scenario() -> None:
        async with llm_call_guard("test"):
            if action is not None:
                action()
            if raise_exc is not None:
                raise raise_exc

    asyncio.run(scenario())


def test_guard_converts_timeout():
    with pytest.raises(LLMTimeoutError):
        run_in_guard(TimeoutError())


def test_guard_converts_validation_error():
    class Model(BaseModel):
        value: int

    with pytest.raises(LLMOutputError):
        run_in_guard(action=lambda: Model(value="숫자아님"))


def test_guard_converts_openai_error():
    with pytest.raises(LLMUpstreamError):
        run_in_guard(OpenAIError("boom"))


def test_guard_passes_through_unknown_error():
    with pytest.raises(ZeroDivisionError):
        run_in_guard(ZeroDivisionError())
