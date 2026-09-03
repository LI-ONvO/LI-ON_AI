"""헬스체크 엔드포인트.

- /health  : 프로세스가 살아 있는지만 본다. 배포 헬스체크용이라 LLM을 호출하지 않는다.
- /ready   : 요청을 처리할 준비가 됐는지(설정 완비 여부) 본다.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="라이브니스 체크")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "model": settings.model_name,
    }


@router.get("/ready", summary="레디니스 체크")
async def ready() -> JSONResponse:
    missing = []
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")

    if missing:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "missing": missing},
        )
    return JSONResponse(status_code=200, content={"status": "ready"})
