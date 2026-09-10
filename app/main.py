"""FastAPI 애플리케이션 진입점.

실행: uvicorn app.main:app --reload

엔드포인트
  GET  /health       라이브니스 체크
  GET  /ready        레디니스 체크 (설정 완비 여부)
  POST /v1/chat      대화 맥락 기반 AI 응답 생성
  POST /v1/roadmap   대화 맥락 기반 구조화 로드맵 생성

/v1 아래는 X-API-Key 헤더가 있어야 한다. 상태 확인용 엔드포인트는 인증 없이 연다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.middleware import register_middleware
from app.api.v1.router import api_router
from app.core.security import require_api_key
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    logger.info(
        "%s v%s 시작 | model=%s timeout=%ss",
        settings.app_name,
        settings.app_version,
        settings.model_name,
        settings.request_timeout_seconds,
    )
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY가 비어 있습니다. .env 파일을 확인하세요. LLM 호출은 실패합니다.")
    yield
    logger.info("%s 종료", settings.app_name)


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="LI-ON 자격증 학습 서비스의 AI 서버. 백엔드가 프록시로 호출한다.",
        lifespan=lifespan,
    )

    register_middleware(app)
    register_exception_handlers(app)

    # /health 와 /ready 는 인증 없이 둔다. 배포 플랫폼과 백엔드가 서버 상태를 확인하는 통로다.
    app.include_router(health.router)
    app.include_router(api_router, prefix="/v1", dependencies=[Depends(require_api_key)])

    return app


app = create_app()
