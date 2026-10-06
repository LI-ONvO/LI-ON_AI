"""백엔드 조회 API 클라이언트.

AI 서버는 Vercel 에서 돌고 자격증 DB 는 백엔드 서버 안쪽에 있어 직접 읽을 수 없다.
그래서 자격증 조회를 백엔드가 열어준 API 로 대신한다. 명세는 docs/BACKEND_API.md.

인증은 X-Internal-Key 헤더다. AI 서버에는 로그인한 사용자가 없어 accessToken 을 쓸 수 없다.
"""

from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AIServerError, ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class BackendUnavailableError(AIServerError):
    """백엔드 조회 API 가 응답하지 않거나 오류를 낸 경우."""

    status_code = 502
    code = "BACKEND_UNAVAILABLE"
    message = "자격증 정보를 가져오지 못했습니다."


async def get_json(path: str, params: dict[str, Any] | None = None) -> dict | None:
    """백엔드에 GET 요청을 보내 JSON 을 돌려준다. 404 면 None.

    404 를 예외로 보지 않는 이유: 상세 조회에서 "그런 종목 없음"은 정상적인 결과다.
    """
    if not settings.backend_api_base_url or not settings.backend_api_key:
        raise ConfigurationError(
            "백엔드 조회 API 설정(BACKEND_API_BASE_URL, BACKEND_API_KEY)이 없습니다."
        )

    url = settings.backend_api_base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=settings.backend_timeout_seconds) as client:
            response = await client.get(
                url,
                params=params,
                headers={"X-Internal-Key": settings.backend_api_key},
            )
    except httpx.TimeoutException as exc:
        logger.warning("백엔드 조회 시간 초과 | %s", path)
        raise BackendUnavailableError("자격증 정보 조회가 지연되고 있습니다.") from exc
    except httpx.HTTPError as exc:
        logger.warning("백엔드 연결 실패 | %s | %s", path, exc)
        raise BackendUnavailableError() from exc

    if response.status_code == 404:
        return None
    if response.status_code == 401:
        # 키가 틀렸거나 바뀌었다. 재시도해도 소용없으니 설정 문제로 알린다.
        logger.error("백엔드가 인증을 거절했습니다. BACKEND_API_KEY 를 확인하세요.")
        raise ConfigurationError("백엔드 조회 API 인증에 실패했습니다.")
    if response.status_code >= 400:
        logger.warning("백엔드 오류 | %s | HTTP %s | %s", path, response.status_code, response.text[:200])
        raise BackendUnavailableError()

    return response.json()
