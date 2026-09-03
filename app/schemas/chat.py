"""채팅 요청/응답 스키마.

대응 백엔드 API: POST /api/chat/sessions/{sessionId}/messages
"""

from enum import Enum

from pydantic import Field

from app.schemas.base import CamelModel


class Sender(str, Enum):
    """메시지 작성 주체. 백엔드 Message 엔티티의 sender와 동일한 값."""

    USER = "USER"
    AI = "AI"


class ChatMessage(CamelModel):
    sender: Sender = Field(description="메시지 작성 주체")
    content: str = Field(description="메시지 본문")


class ChatRequest(CamelModel):
    session_id: int = Field(description="대화 세션 ID. 추적/로깅 용도로만 쓰인다.")
    jm_cd: str | None = Field(
        default=None,
        description=(
            "사용자가 선택한 자격증 종목코드. 대화는 이 자격증을 놓고 시작하므로 "
            "값이 있으면 AI에게 대상 자격증으로 알려준다."
        ),
    )
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="이전 대화 목록. 오래된 메시지가 앞에 오도록 정렬해서 보낸다.",
    )
    content: str = Field(min_length=1, description="사용자가 이번에 보낸 메시지")


class ChatResponse(CamelModel):
    content: str = Field(description="AI 응답 본문")
