"""채팅 유스케이스."""

from app.chains.chat_chain import run_chat_chain
from app.core.logging import get_logger
from app.schemas.chat import ChatRequest, ChatResponse

logger = get_logger(__name__)


async def generate_chat_response(payload: ChatRequest) -> ChatResponse:
    logger.info(
        "채팅 응답 생성 시작 | sessionId=%s jmCd=%s historyLen=%d",
        payload.session_id,
        payload.jm_cd,
        len(payload.history),
    )
    content = await run_chat_chain(payload.history, payload.content, payload.jm_cd)
    logger.info("채팅 응답 생성 완료 | sessionId=%s length=%d", payload.session_id, len(content))
    return ChatResponse(content=content)
