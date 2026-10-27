"""학습 자료 추천 유스케이스.

네 출처(영상·책·웹·블로그)를 동시에 검색하고, 이미 보여준 자료(excludeUrls)를 뺀 뒤
종류를 번갈아 가며 size 개를 채운다. 출처 하나가 실패해도 나머지로 응답한다.

명세의 "실제 접근 가능한 url만"은 이렇게 지킨다.
  - 영상: 상세 조회에서 공개 상태인 것만 남긴다(resource_sources).
  - 책: 다음 책 상세 페이지라 따로 확인하지 않는다.
  - 웹·블로그: 실제로 요청해 보고 없는 페이지(404 등)나 연결 실패는 뺀다.
"""

import asyncio

import httpx

from app.core.exceptions import AIServerError
from app.core.logging import get_logger
from app.repositories import resource_sources as sources
from app.repositories.certifications import get_certification
from app.schemas.resource import (
    ResourceItem,
    ResourceRequest,
    ResourceResponse,
    ResourceType,
    UnavailableReason,
    UnavailableSource,
)

logger = get_logger(__name__)

# 화면에서 종류가 고루 보이도록 이 순서로 하나씩 번갈아 담는다.
TYPE_ORDER = (ResourceType.VIDEO, ResourceType.BOOK, ResourceType.WEB, ResourceType.BLOG)

LINK_CHECK_TIMEOUT_SECONDS = 4.0
# 봇 요청을 막는 사이트가 있다. 막혔다는 건 페이지가 있다는 뜻이라 살려 둔다.
_BLOCKED_BUT_EXISTS = {401, 403, 405, 429}


class ResourceSourcesUnavailable(AIServerError):
    status_code = 502
    code = "RESOURCE_SOURCES_UNAVAILABLE"
    message = "학습 자료 검색에 실패했습니다."


class ResourceQuotaExceeded(AIServerError):
    """모든 출처가 호출 한도에 걸렸다. 서버 장애가 아니라 잠시 뒤 다시 시도하면 된다."""

    status_code = 503
    code = "RESOURCE_QUOTA_EXCEEDED"
    message = "학습 자료 검색 한도를 모두 사용했습니다. 잠시 후 다시 시도해 주세요."


class CertificateNotFound(AIServerError):
    status_code = 422
    code = "CERTIFICATE_NOT_FOUND"
    message = "자격증 종목코드를 찾지 못했습니다."


def _reason(t: ResourceType, error: BaseException) -> UnavailableReason:
    if isinstance(error, sources.SourceQuotaExceeded):
        return UnavailableReason.QUOTA_EXCEEDED
    if isinstance(error, sources.SourceNotConfigured):
        return UnavailableReason.NOT_CONFIGURED
    if not isinstance(error, sources.SourceUnavailable):
        logger.error("자료 검색 중 예상하지 못한 오류 | type=%s", t.value, exc_info=error)
    return UnavailableReason.ERROR


def detect_stage(roadmap_steps: list[str]) -> str | None:
    """로드맵이 실기만 다루면 실기, 필기만 다루면 필기 자료를 찾는다. 섞여 있으면 구분하지 않는다."""
    text = " ".join(roadmap_steps)
    has_written, has_practical = "필기" in text, "실기" in text
    if has_practical and not has_written:
        return "실기"
    if has_written and not has_practical:
        return "필기"
    return None


async def _is_reachable(client: httpx.AsyncClient, url: str) -> bool:
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return False
    return response.status_code < 400 or response.status_code in _BLOCKED_BUT_EXISTS


async def _drop_unreachable(items: list[ResourceItem], limit: int) -> list[ResourceItem]:
    """앞에서부터 limit 개까지만 확인한다. 뒤쪽 후보는 어차피 쓰이지 않는다."""
    head = items[:limit]
    async with httpx.AsyncClient(
        timeout=LINK_CHECK_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LI-ON link check)"},
    ) as client:
        ok = await asyncio.gather(*(_is_reachable(client, item.url) for item in head))
    dropped = [item.url for item, good in zip(head, ok) if not good]
    if dropped:
        logger.info("열리지 않는 링크를 뺐습니다. | %s", dropped)
    return [item for item, good in zip(head, ok) if good]


def interleave(by_type: dict[ResourceType, list[ResourceItem]], order, size: int) -> list[ResourceItem]:
    """종류를 번갈아 가며 size 개까지 담는다. 한 종류가 바닥나면 남은 종류로 채운다."""
    queues = {t: list(by_type.get(t, [])) for t in order}
    picked: list[ResourceItem] = []
    while len(picked) < size and any(queues.values()):
        for t in order:
            if queues[t] and len(picked) < size:
                picked.append(queues[t].pop(0))
    return picked


async def recommend_resources(payload: ResourceRequest) -> ResourceResponse:
    cert = payload.certificate
    name = (cert.name or "").strip()
    if not name:
        found = await get_certification(cert.jm_cd)
        if found is None:
            raise CertificateNotFound()
        name = found["jmNm"]

    stage = detect_stage(payload.context.roadmap_steps if payload.context else [])
    order = [t for t in TYPE_ORDER if payload.types is None or t in payload.types]
    logger.info(
        "자료 추천 시작 | userId=%s jmCd=%s name=%s stage=%s size=%d types=%s exclude=%d",
        payload.user_id, cert.jm_cd, name, stage, payload.size,
        [t.value for t in order], len(payload.exclude_urls),
    )

    searches = {
        ResourceType.VIDEO: lambda: sources.search_videos(name, stage),
        ResourceType.BOOK: lambda: sources.search_books(name),
        ResourceType.WEB: lambda: sources.search_web(name),
        ResourceType.BLOG: lambda: sources.search_blogs(name, stage),
    }
    results = await asyncio.gather(*(searches[t]() for t in order), return_exceptions=True)

    excluded = set(payload.exclude_urls)
    by_type: dict[ResourceType, list[ResourceItem]] = {}
    unavailable: list[UnavailableSource] = []
    for t, result in zip(order, results):
        if isinstance(result, BaseException):
            unavailable.append(UnavailableSource(type=t, reason=_reason(t, result)))
            continue
        by_type[t] = [item for item in result if item.url not in excluded]

    if order and len(unavailable) == len(order):
        if all(u.reason == UnavailableReason.QUOTA_EXCEEDED for u in unavailable):
            raise ResourceQuotaExceeded()
        raise ResourceSourcesUnavailable()

    # 웹·블로그는 링크를 실제로 열어 본다. 한 종류가 최대 size 개까지 쓰일 수 있으니 그만큼만.
    for t in (ResourceType.WEB, ResourceType.BLOG):
        if by_type.get(t):
            by_type[t] = await _drop_unreachable(by_type[t], payload.size)

    items = interleave(by_type, order, payload.size)
    logger.info(
        "자료 추천 완료 | userId=%s items=%d %s failed=%s",
        payload.user_id, len(items),
        {t.value: sum(1 for i in items if i.type == t) for t in order},
        [f"{u.type.value}:{u.reason.value}" for u in unavailable],
    )
    return ResourceResponse(items=items, unavailable=unavailable)
