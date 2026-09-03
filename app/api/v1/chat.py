"""채팅 엔드포인트.

백엔드가 POST /api/chat/sessions/{sessionId}/messages 를 처리하는 도중 프록시로 호출한다.
"""

from fastapi import APIRouter, status

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import generate_chat_response

router = APIRouter()


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="대화 맥락 기반 AI 응답 생성",
)
async def create_chat_response(payload: ChatRequest) -> ChatResponse:
    return await generate_chat_response(payload)
