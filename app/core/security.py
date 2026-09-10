"""API 키 인증.

이 서버는 백엔드만 호출한다. 인터넷에 올라가 있으므로 주소를 아는 누구나 요청을 보낼 수 있고,
그 비용은 우리 OpenAI 키에서 나간다. 그래서 약속된 키가 헤더에 없으면 거절한다.

키가 설정되지 않았으면 요청을 통과시키지 않는다. 설정을 빠뜨렸을 때 조용히 무방비가 되는 것보다,
눈에 띄게 실패하는 편이 안전하다.
"""

import secrets

from fastapi import Header

from app.core.config import settings
from app.core.exceptions import AIServerError
from app.core.logging import get_logger

logger = get_logger(__name__)

API_KEY_HEADER = "X-API-Key"


class MissingAPIKeyConfig(AIServerError):
    status_code = 500
    code = "API_KEY_NOT_CONFIGURED"


class InvalidAPIKey(AIServerError):
    status_code = 401
    code = "UNAUTHORIZED"


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """X-API-Key 헤더를 검사한다. FastAPI가 헤더명을 x_api_key 로 변환해 넘긴다."""
    if not settings.api_key:
        logger.error("API_KEY가 설정되지 않았습니다. .env 또는 배포 환경변수를 확인하세요.")
        raise MissingAPIKeyConfig("서버에 인증키가 설정되지 않았습니다.")

    # 문자열을 == 로 비교하면 앞에서부터 틀린 지점까지의 시간이 달라져 키를 한 글자씩 알아낼 수 있다.
    # compare_digest 는 길이가 같으면 항상 같은 시간이 걸린다.
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise InvalidAPIKey("인증에 실패했습니다. X-API-Key 헤더를 확인하세요.")
