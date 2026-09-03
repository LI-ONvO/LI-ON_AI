"""LLM 클라이언트 생성과 예외 변환.

체인/서비스 계층은 이 모듈을 통해서만 모델을 얻는다. 모델 교체(OpenAI → 다른 제공자)는
이 파일만 수정하면 되도록 격리해 둔다.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from openai import APITimeoutError, OpenAIError
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import (
    ConfigurationError,
    LLMOutputError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=8)
def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    """공용 LLM 클라이언트.

    temperature별로 캐싱한다. 클라이언트는 내부에 HTTP 커넥션 풀을 들고 있어서
    요청마다 새로 만들면 커넥션이 계속 늘어난다.
    """
    if not settings.openai_api_key:
        raise ConfigurationError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        temperature=settings.temperature if temperature is None else temperature,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
    )


@asynccontextmanager
async def llm_call_guard(operation: str) -> AsyncIterator[None]:
    """LLM 호출부를 감싸 제공자별 예외를 도메인 예외로 변환한다.

    변환 규칙
      - 타임아웃            → 504 LLM_TIMEOUT
      - 출력 형식 불일치    → 502 LLM_OUTPUT_INVALID
      - 그 외 제공자 오류   → 502 LLM_UPSTREAM_ERROR
    """
    try:
        yield
    # Python 3.11부터 asyncio.TimeoutError는 내장 TimeoutError의 별칭이지만,
    # 3.10에서는 별개 타입이라 둘 다 명시한다.
    except (APITimeoutError, asyncio.TimeoutError, TimeoutError) as exc:
        logger.warning("[%s] LLM 타임아웃: %s", operation, exc)
        raise LLMTimeoutError() from exc
    except (OutputParserException, ValidationError) as exc:
        logger.warning("[%s] LLM 출력 형식 오류: %s", operation, exc)
        raise LLMOutputError() from exc
    except OpenAIError as exc:
        logger.error("[%s] LLM 호출 실패: %s", operation, exc)
        raise LLMUpstreamError() from exc
