"""예외 → HTTP 응답 변환.

성공/실패 응답 형태를 통일해서 백엔드가 분기하기 쉽게 만든다.
모든 오류 응답은 {"code": ..., "message": ..., "detail": ...} 형태다.
"""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AIServerError
from app.core.logging import get_logger
from app.schemas.error import ErrorResponse

logger = get_logger(__name__)


def _error_response(status_code: int, code: str, message: str, detail: object = None) -> JSONResponse:
    payload = ErrorResponse(code=code, message=message, detail=detail)
    # pydantic의 유효성 오류 목록에는 예외 객체가 섞여 있어 json.dumps로 바로 직렬화되지 않는다.
    # jsonable_encoder를 거쳐야 안전하다.
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload, by_alias=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AIServerError)
    async def handle_ai_server_error(_: Request, exc: AIServerError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422,
            "INVALID_REQUEST",
            "요청 형식이 올바르지 않습니다.",
            detail=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 예상하지 못한 예외는 스택트레이스를 남기되, 응답 본문에는 내부 정보를 노출하지 않는다.
        logger.exception("처리되지 않은 예외 | %s %s", request.method, request.url.path)
        return _error_response(500, "AI_INTERNAL_ERROR", "AI 처리 중 오류가 발생했습니다.")
