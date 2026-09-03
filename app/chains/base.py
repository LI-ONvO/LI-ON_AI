"""체인 공통 유틸."""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.schemas.chat import ChatMessage, Sender


def trim_history(history: Sequence[ChatMessage]) -> list[ChatMessage]:
    """최근 N개만 남긴다.

    히스토리는 백엔드가 통째로 보내주므로 대화가 길어질수록 토큰 비용이 선형으로 늘어난다.
    가장 최근 대화가 답변 품질에 가장 큰 영향을 주므로 뒤에서부터 자른다.
    """
    limit = settings.max_history_messages
    if limit <= 0 or len(history) <= limit:
        return list(history)
    return list(history[-limit:])


def build_messages(
    system_prompt: str,
    history: Sequence[ChatMessage],
    user_content: str | None = None,
) -> list[BaseMessage]:
    """시스템 프롬프트 + 대화 이력 + (선택) 신규 사용자 메시지를 LangChain 메시지로 변환한다."""
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]

    for message in trim_history(history):
        if message.sender == Sender.USER:
            messages.append(HumanMessage(content=message.content))
        else:
            messages.append(AIMessage(content=message.content))

    if user_content:
        messages.append(HumanMessage(content=user_content))

    return messages


def extract_text(content: object) -> str:
    """AIMessage.content에서 순수 텍스트를 뽑는다.

    모델에 따라 content가 문자열이 아니라 블록 리스트로 오는 경우가 있어 둘 다 처리한다.
    """
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts).strip()

    return ""
