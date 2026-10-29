"""학습 자료 외부 검색 (YouTube, 카카오 책, NAVER 웹문서·블로그).

각 함수는 검색 → 규칙으로 거르기 → 순서 정하기까지 하고 후보 목록(ResourceItem)을 돌려준다.

AI 를 쓰지 않는 이유 (2026-10 확인):
  - 카카오: "검색 데이터를 외부 LLM API 로 전송하여 활용하는 것은 제한" (데브톡 공식 답변)
  - NAVER: 검색 API 데이터는 가공 없이 독립적으로 노출 (2026-09-07 개정 약관)
그래서 고르는 기준은 전부 코드 규칙이고, reason 도 API 가 준 값(출처·날짜·조회수)으로 만든다.
제목·설명은 API 가 준 그대로 쓴다(검색어 강조 태그 <b> 만 벗긴다).

저장 기간 상한: YouTube 30일, NAVER 21일, 카카오는 임시 캐시만. 이 모듈의 메모리 캐시는
그보다 훨씬 짧다(RESOURCE_CACHE_SECONDS).
"""

import html
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.resource import BlogInfo, BookInfo, ResourceItem, ResourceType, VideoInfo

logger = get_logger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
KAKAO_BOOK_URL = "https://dapi.kakao.com/v3/search/book"
NAVER_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/{kind}"


class SourceUnavailable(Exception):
    """한 출처의 검색이 실패했다. 다른 출처 결과는 그대로 쓴다."""


class SourceNotConfigured(SourceUnavailable):
    """이 출처의 API 키가 설정되지 않았다."""


class SourceQuotaExceeded(SourceUnavailable):
    """호출 한도를 다 썼다. 풀릴 때까지 그 출처는 부르지 않는다."""


# 한도가 찬 출처를 다시 부르지 않을 시각(time.time 기준). 한도가 찬 뒤에도 매 요청마다 부르면
# 실패할 줄 알면서 응답만 늦어진다. 인스턴스 메모리라 Vercel 인스턴스가 바뀌면 한 번 더 부르고
# 다시 막힌 것을 알게 된다(그 한 번은 감수한다).
_blocked_until: dict[str, float] = {}

# 초당 호출 제한(429)은 잠깐 기다리면 풀린다.
RATE_LIMIT_COOLDOWN_SECONDS = 60
# 월 한도처럼 언제 풀릴지 알 수 없는 경우. 너무 길면 풀린 뒤에도 안 쓰고, 짧으면 헛호출이 는다.
UNKNOWN_QUOTA_COOLDOWN_SECONDS = 60 * 60


def _next_youtube_reset() -> float:
    """YouTube 할당량은 매일 태평양 시간 자정에 초기화된다.

    서버에 시간대 DB 가 없을 수 있어 태평양 표준시(UTC-8)로 계산한다. 서머타임 기간에는 실제
    초기화(UTC 07:00)보다 한 시간 늦게(UTC 08:00) 다시 시도하게 된다. 한 시간 손해는 감수한다.
    """
    now = datetime.now(timezone.utc)
    reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return reset.timestamp()


def is_blocked(source: str) -> bool:
    return time.time() < _blocked_until.get(source, 0)


def _block(source: str, until: float, reason: str) -> None:
    _blocked_until[source] = until
    logger.warning(
        "%s 호출 한도 초과로 %s 까지 부르지 않습니다. | %s",
        source, datetime.fromtimestamp(until, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), reason,
    )


def _youtube_error_reasons(response: httpx.Response) -> set[str]:
    try:
        return {e.get("reason", "") for e in response.json()["error"]["errors"]}
    except (ValueError, KeyError, TypeError):
        return set()


def _check_quota(source: str, response: httpx.Response) -> None:
    """한도 초과 응답이면 막아 두고 SourceQuotaExceeded 를 낸다. 아니면 아무것도 하지 않는다."""
    status = response.status_code
    if source == "YOUTUBE" and status == 403:
        reasons = _youtube_error_reasons(response)
        if reasons & {"quotaExceeded", "dailyLimitExceeded"}:
            _block(source, _next_youtube_reset(), ",".join(sorted(reasons)))
            raise SourceQuotaExceeded(source)
        if reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
            _block(source, time.time() + RATE_LIMIT_COOLDOWN_SECONDS, ",".join(sorted(reasons)))
            raise SourceQuotaExceeded(source)
    if status == 429:
        # NAVER API HUB 는 초당 한도(50 RPS)와 월 한도 모두 429 로 막는다. 카카오도 429.
        # 본문으로 둘을 구분할 수 있으면 좋겠지만 형식이 정해져 있지 않아 문구로 본다.
        body = response.text.lower()
        monthly = any(word in body for word in ("month", "quota", "월", "한도"))
        cooldown = UNKNOWN_QUOTA_COOLDOWN_SECONDS if monthly else RATE_LIMIT_COOLDOWN_SECONDS
        _block(source, time.time() + cooldown, f"status=429 {response.text[:100]}")
        raise SourceQuotaExceeded(source)


# --------------------------------------------------------------------- 공통

# 같은 검색을 짧은 시간에 반복하지 않는다. 특히 YouTube 는 검색이 하루 100번 남짓이다.
# Vercel 인스턴스가 살아 있는 동안만 유효하다. 오래 쓰는 저장은 백엔드 저장소가 맡는다.
RESOURCE_CACHE_SECONDS = 6 * 60 * 60
_cache: dict[tuple, tuple[float, list[ResourceItem]]] = {}


def _cached(key: tuple) -> list[ResourceItem] | None:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < RESOURCE_CACHE_SECONDS:
        return hit[1]
    return None


def _store(key: tuple, items: list[ResourceItem]) -> list[ResourceItem]:
    _cache[key] = (time.monotonic(), items)
    return items


_TAG = re.compile(r"<[^>]+>")


def _plain(text: str | None) -> str:
    """검색어 강조 태그(<b>)와 HTML 엔티티만 벗긴다. 문장은 건드리지 않는다."""
    return html.unescape(_TAG.sub("", text or "")).strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _mentions(title: str, cert_name: str) -> bool:
    """제목에 자격증 이름이 들어 있는지. 띄어쓰기는 무시한다(프로그래밍 기능사)."""
    return _compact(cert_name) in _compact(title)


async def _get(url: str, *, params: dict, headers: dict, label: str, source: str) -> dict:
    """source 는 한도를 함께 쓰는 단위다. NAVER 웹문서·블로그는 한도를 같이 쓴다."""
    if is_blocked(source):
        raise SourceQuotaExceeded(source)
    try:
        async with httpx.AsyncClient(timeout=settings.resource_timeout_seconds) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("%s 검색 실패 | %s", label, type(exc).__name__)
        raise SourceUnavailable(label) from exc
    _check_quota(source, response)
    if response.status_code != 200:
        # 본문에 키가 들어 있지 않지만, 길게 찍지 않는다.
        logger.warning("%s 검색 실패 | status=%s body=%s", label, response.status_code, response.text[:200])
        raise SourceUnavailable(label)
    return response.json()


# ------------------------------------------------------------------ YouTube

# 3분 미만은 대부분 쇼츠·예고편이다.
MIN_VIDEO_SECONDS = 180
# 출제기준이 바뀌는 자격증이 많아 오래된 강의는 뺀다(프로그래밍기능사는 2025년에 과목이 바뀌었다).
MAX_VIDEO_AGE_DAYS = 3 * 365

_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _iso_duration(raw: str | None) -> int | None:
    match = _DURATION.fullmatch(raw or "")
    if not match:
        return None
    d, h, m, s = (int(g) if g else 0 for g in match.groups())
    return ((d * 24 + h) * 60 + m) * 60 + s


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_duration(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m = rest // 60
    return f"{h}시간 {m}분" if h else f"{m}분"


async def search_videos(cert_name: str, stage: str | None) -> list[ResourceItem]:
    if not settings.youtube_api_key:
        raise SourceNotConfigured("YOUTUBE")

    query = f"{cert_name} {stage or ''} 강의".replace("  ", " ")
    key = ("VIDEO", query)
    if (hit := _cached(key)) is not None:
        return hit

    # 키를 쿼리스트링(?key=)에 넣으면 httpx 요청 로그에 그대로 찍힌다. 헤더로 보낸다.
    headers = {"X-goog-api-key": settings.youtube_api_key}
    found = await _get(
        YOUTUBE_SEARCH_URL,
        params={
            "part": "snippet", "q": query, "type": "video", "maxResults": 25,
            "regionCode": "KR", "relevanceLanguage": "ko", "safeSearch": "strict",
        },
        headers=headers,
        label="YouTube",
        source="YOUTUBE",
    )
    ids = [it["id"]["videoId"] for it in found.get("items", []) if it.get("id", {}).get("videoId")]
    if not ids:
        return _store(key, [])

    # 검색 결과에는 길이·조회수·공개 상태가 없다. 상세 조회는 1점이라 한도 걱정이 없다.
    details = await _get(
        YOUTUBE_VIDEOS_URL,
        params={"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids)},
        headers=headers,
        label="YouTube",
        source="YOUTUBE",
    )
    by_id = {v["id"]: v for v in details.get("items", [])}

    cutoff = datetime.now().astimezone() - timedelta(days=MAX_VIDEO_AGE_DAYS)
    items: list[ResourceItem] = []
    for video_id in ids:  # 검색 관련도 순서를 유지한다.
        v = by_id.get(video_id)
        if v is None:  # 삭제됐거나 비공개로 바뀐 영상은 상세 조회에서 빠진다.
            continue
        snippet, stats, status = v["snippet"], v.get("statistics", {}), v.get("status", {})
        title = snippet.get("title", "")
        seconds = _iso_duration(v.get("contentDetails", {}).get("duration"))
        published = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))

        if status.get("privacyStatus") != "public":
            continue
        if not seconds or seconds < MIN_VIDEO_SECONDS:
            continue
        if published < cutoff or not _mentions(title, cert_name):
            continue

        views = _to_int(stats.get("viewCount"))
        channel = snippet.get("channelTitle")
        parts = ["YouTube", channel, _format_duration(seconds)]
        if views is not None:
            parts.append(f"조회수 {views:,}회")
        parts.append(f"{published:%Y-%m-%d} 업로드")
        thumbs = snippet.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")

        items.append(ResourceItem(
            type=ResourceType.VIDEO,
            title=title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            reason=" · ".join(p for p in parts if p),
            description=snippet.get("description") or None,
            source=f"YouTube · {channel}" if channel else "YouTube",
            thumbnail_url=thumb,
            published_at=published,
            video=VideoInfo(
                video_id=video_id,
                channel_id=snippet.get("channelId"),
                channel_title=channel,
                duration_seconds=seconds,
                view_count=views,
                like_count=_to_int(stats.get("likeCount")),
                comment_count=_to_int(stats.get("commentCount")),
                tags=snippet.get("tags", []),
                embeddable=status.get("embeddable"),
            ),
        ))
    return _store(key, items)


# ------------------------------------------------------------------- 책

# 판매 중인 책만. 절판·품절 책은 링크를 눌러도 살 수 없다.
_ON_SALE = {"정상판매", ""}
_EDITION = re.compile(r"(20\d{2})")
MAX_BOOK_AGE_DAYS = 3 * 365


async def search_books(cert_name: str) -> list[ResourceItem]:
    if not settings.kakao_rest_api_key:
        raise SourceNotConfigured("KAKAO")

    key = ("BOOK", cert_name)
    if (hit := _cached(key)) is not None:
        return hit

    found = await _get(
        KAKAO_BOOK_URL,
        params={"query": cert_name, "target": "title", "size": 30, "sort": "accuracy"},
        headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
        label="카카오 책",
        source="KAKAO",
    )

    today = date.today()
    seen_isbn: set[str] = set()
    ranked: list[tuple[tuple, ResourceItem]] = []
    for doc in found.get("documents", []):
        title = doc.get("title", "")
        if not _mentions(title, cert_name) or (doc.get("status") or "") not in _ON_SALE:
            continue
        published = date.fromisoformat(doc["datetime"][:10]) if doc.get("datetime") else None
        if published and (today - published).days > MAX_BOOK_AGE_DAYS:
            continue
        isbn = doc.get("isbn") or ""
        if isbn and isbn in seen_isbn:
            continue
        seen_isbn.add(isbn)

        # 수험서는 "2027 이기적 프로그래밍기능사"처럼 판 연도를 제목 앞에 단다. 이 연도가 최신판 기준이다.
        edition = _EDITION.search(title)
        edition_year = int(edition.group(1)) if edition else None
        sale = _to_int(doc.get("sale_price"))
        publisher = doc.get("publisher") or None

        parts = ["다음 책", publisher]
        if edition_year:
            parts.append(f"{edition_year}년 판")
        if published:
            parts.append(f"{published:%Y-%m} 출간")

        item = ResourceItem(
            type=ResourceType.BOOK,
            title=title,
            url=doc.get("url", ""),
            reason=" · ".join(p for p in parts if p),
            description=doc.get("contents") or None,
            source="다음 책",
            thumbnail_url=doc.get("thumbnail") or None,
            published_at=published,
            book=BookInfo(
                authors=doc.get("authors", []),
                translators=doc.get("translators", []),
                publisher=publisher,
                isbn=isbn or None,
                price=_to_int(doc.get("price")),
                sale_price=sale if sale and sale > 0 else None,  # 판매가가 없으면 -1 로 온다
                status=doc.get("status") or None,
                edition_year=edition_year,
            ),
        )
        # 최신 판 → 최근 출간 → 원래 검색 순서
        ranked.append(((-(edition_year or 0), -(published.toordinal() if published else 0)), item))

    ranked.sort(key=lambda pair: pair[0])
    return _store(key, [item for _, item in ranked if item.url])


# ------------------------------------------------------------- NAVER 웹·블로그

# 시행처·공공기관. 웹문서 검색에서 맨 앞에 둔다.
TRUSTED_DOMAINS = ("q-net.or.kr", "hrdkorea.or.kr", "korea.kr", "kca.kr", "kisa.or.kr")
# 블로그 중 학원·교육기관 홍보 글. 제목이나 블로그 이름에 이런 말이 있으면 뺀다.
_PROMO_WORDS = ("학원", "교육원", "아카데미", "수강", "모집", "할인", "국비", "상담")
MAX_BLOG_AGE_DAYS = 2 * 365


def _naver_headers() -> dict:
    if not settings.naver_client_id or not settings.naver_client_secret:
        raise SourceNotConfigured("NAVER")
    # NAVER API HUB 는 예전 개발자센터(X-Naver-Client-Id)와 헤더 이름이 다르다.
    return {
        "X-NCP-APIGW-API-KEY-ID": settings.naver_client_id,
        "X-NCP-APIGW-API-KEY": settings.naver_client_secret,
    }


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


async def search_web(cert_name: str) -> list[ResourceItem]:
    key = ("WEB", cert_name)
    if (hit := _cached(key)) is not None:
        return hit

    found = await _get(
        NAVER_SEARCH_URL.format(kind="webkr"),
        params={"query": cert_name, "display": 30},
        headers=_naver_headers(),
        label="NAVER 웹문서",
        source="NAVER",
    )

    seen_domains: set[str] = set()
    trusted: list[ResourceItem] = []
    others: list[ResourceItem] = []
    for it in found.get("items", []):
        title, url = _plain(it.get("title")), it.get("link", "")
        domain = _domain(url)
        if not url or not _mentions(title, cert_name) or domain in seen_domains:
            continue
        # 한 사이트가 목록을 채우지 않게 사이트당 하나만.
        seen_domains.add(domain)

        is_trusted = any(domain == d or domain.endswith("." + d) for d in TRUSTED_DOMAINS)
        item = ResourceItem(
            type=ResourceType.WEB,
            title=title,
            url=url,
            reason=f"NAVER 웹문서 · {domain}" + (" · 공식 기관" if is_trusted else ""),
            description=_plain(it.get("description")) or None,
            source="NAVER 웹문서",
        )
        (trusted if is_trusted else others).append(item)
    return _store(key, trusted + others)


async def search_blogs(cert_name: str, stage: str | None) -> list[ResourceItem]:
    query = f"{cert_name} {stage or ''} 공부법".replace("  ", " ")
    key = ("BLOG", query)
    if (hit := _cached(key)) is not None:
        return hit

    found = await _get(
        NAVER_SEARCH_URL.format(kind="blog"),
        params={"query": query, "display": 30, "sort": "sim"},
        headers=_naver_headers(),
        label="NAVER 블로그",
        source="NAVER",
    )

    today = date.today()
    seen_bloggers: set[str] = set()
    items: list[ResourceItem] = []
    for it in found.get("items", []):
        title, url = _plain(it.get("title")), it.get("link", "")
        blogger = _plain(it.get("bloggername"))
        if not url or not _mentions(title, cert_name):
            continue
        if any(word in title or word in blogger for word in _PROMO_WORDS):
            continue
        posted = None
        if (raw := it.get("postdate")) and len(raw) == 8:
            posted = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            if (today - posted).days > MAX_BLOG_AGE_DAYS:
                continue
        blogger_link = it.get("bloggerlink") or None
        if (blogger_link or blogger) in seen_bloggers:
            continue
        seen_bloggers.add(blogger_link or blogger)

        parts = ["NAVER 블로그", blogger]
        if posted:
            parts.append(f"{posted:%Y-%m-%d} 작성")
        items.append(ResourceItem(
            type=ResourceType.BLOG,
            title=title,
            url=url,
            reason=" · ".join(p for p in parts if p),
            description=_plain(it.get("description")) or None,
            source="NAVER 블로그",
            published_at=posted,
            blog=BlogInfo(blogger_name=blogger or None, blogger_link=blogger_link),
        ))
    return _store(key, items)
