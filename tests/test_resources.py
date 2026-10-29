"""학습 자료 추천 테스트. 외부 검색 API 는 전부 가짜 응답으로 바꾼다."""

import asyncio
import time
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.repositories import resource_sources as sources
from app.schemas.resource import ResourceItem, ResourceType
from app.services import resource_service
from app.services.resource_service import detect_stage, interleave

CERT = "프로그래밍기능사"


@pytest.fixture(autouse=True)
def _keys_and_cache(monkeypatch):
    for name in ("youtube_api_key", "kakao_rest_api_key", "naver_client_id", "naver_client_secret"):
        monkeypatch.setattr(settings, name, "test")
    sources._cache.clear()
    sources._blocked_until.clear()
    yield
    sources._cache.clear()
    sources._blocked_until.clear()


def _fake_get(responses: dict):
    """URL 에 들어 있는 조각으로 가짜 응답을 고른다."""

    async def _get(url, *, params, headers, label, source):
        for fragment, body in responses.items():
            if fragment in url:
                return body
        raise AssertionError(f"예상하지 못한 호출: {url}")

    return _get


def _item(t: ResourceType, n: int) -> ResourceItem:
    return ResourceItem(type=t, title=f"{t.value}{n}", url=f"https://x/{t.value}/{n}", reason="r", source="s")


# ------------------------------------------------------------------ 규칙

def test_detect_stage():
    assert detect_stage(["실기 코드 작성 연습", "실기 기출"]) == "실기"
    assert detect_stage(["필기 이론 1회독"]) == "필기"
    assert detect_stage(["필기 이론", "실기 연습"]) is None
    assert detect_stage([]) is None


def test_interleave_alternates_and_backfills():
    """종류를 번갈아 담고, 한 종류가 모자라면 남은 종류로 채운다."""
    by_type = {
        ResourceType.VIDEO: [_item(ResourceType.VIDEO, i) for i in range(3)],
        ResourceType.BOOK: [_item(ResourceType.BOOK, 0)],
    }
    picked = interleave(by_type, [ResourceType.VIDEO, ResourceType.BOOK], 4)
    assert [i.title for i in picked] == ["VIDEO0", "BOOK0", "VIDEO1", "VIDEO2"]


def test_videos_drop_shorts_private_old_and_unrelated(monkeypatch):
    recent = (date.today() - timedelta(days=30)).isoformat() + "T00:00:00Z"
    old = (date.today() - timedelta(days=4 * 365)).isoformat() + "T00:00:00Z"

    def video(vid, title, duration="PT30M", published=recent, privacy="public"):
        return {
            "id": vid,
            "snippet": {"title": title, "publishedAt": published, "channelTitle": "채널", "thumbnails": {}},
            "contentDetails": {"duration": duration},
            "statistics": {"viewCount": "1000"},
            "status": {"privacyStatus": privacy, "embeddable": True},
        }

    ids = ["ok", "short", "private", "old", "other", "deleted"]
    monkeypatch.setattr(sources, "_get", _fake_get({
        "/search": {"items": [{"id": {"videoId": v}} for v in ids]},
        "/videos": {"items": [
            video("ok", f"{CERT} 필기 강의", duration="PT1H2M3S"),
            video("short", f"{CERT} 1분 요약", duration="PT45S"),
            video("private", f"{CERT} 강의", privacy="unlisted"),
            video("old", f"{CERT} 강의", published=old),
            video("other", "정보처리기사 강의"),
            # "deleted" 는 상세 조회 결과에 없다(삭제·비공개 전환)
        ]},
    }))

    items = asyncio.run(sources.search_videos(CERT, None))

    assert [i.video.video_id for i in items] == ["ok"]
    assert items[0].video.duration_seconds == 3723
    assert "1시간 2분" in items[0].reason and "조회수 1,000회" in items[0].reason


def test_books_prefer_latest_edition_and_on_sale(monkeypatch):
    this_year = date.today().year

    def book(title, status="정상판매", published=f"{this_year}-01-01", isbn=None):
        return {"title": title, "status": status, "datetime": f"{published}T00:00:00.000+09:00",
                "isbn": isbn or title, "url": f"https://book/{title}", "sale_price": -1, "price": 20000}

    monkeypatch.setattr(sources, "_get", _fake_get({"dapi.kakao.com": {"documents": [
        book(f"{this_year} {CERT} 필기"),
        book(f"{this_year + 1} {CERT} 필기"),
        book(f"{this_year + 1} {CERT} 실기", status="절판"),
        book("정보처리기사 필기"),
    ]}}))

    items = asyncio.run(sources.search_books(CERT))

    assert [i.book.edition_year for i in items] == [this_year + 1, this_year]
    assert items[0].book.sale_price is None  # 판매가가 없으면 -1 로 온다


def test_web_puts_official_sites_first_one_per_domain(monkeypatch):
    monkeypatch.setattr(sources, "_get", _fake_get({"webkr": {"items": [
        {"title": f"<b>{CERT}</b> 정리", "link": "https://namu.wiki/w/a"},
        {"title": f"{CERT} 정리 2", "link": "https://namu.wiki/w/b"},
        {"title": f"{CERT} - 국가자격 종목별 상세정보", "link": "https://www.q-net.or.kr/crf005.do"},
    ]}}))

    items = asyncio.run(sources.search_web(CERT))

    assert [i.url for i in items] == ["https://www.q-net.or.kr/crf005.do", "https://namu.wiki/w/a"]
    assert items[1].title == f"{CERT} 정리"  # <b> 태그만 벗긴다
    assert "공식 기관" in items[0].reason


def test_blogs_drop_promotions_and_old_posts(monkeypatch):
    recent = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
    old = (date.today() - timedelta(days=3 * 365)).strftime("%Y%m%d")
    monkeypatch.setattr(sources, "_get", _fake_get({"blog": {"items": [
        {"title": f"{CERT} 합격 후기", "link": "https://blog/1", "bloggername": "학생", "postdate": recent},
        {"title": f"{CERT} 국비 수강생 모집", "link": "https://blog/2", "bloggername": "OO학원", "postdate": recent},
        {"title": f"{CERT} 예전 후기", "link": "https://blog/3", "bloggername": "옛날", "postdate": old},
    ]}}))

    items = asyncio.run(sources.search_blogs(CERT, None))

    assert [i.url for i in items] == ["https://blog/1"]


# ------------------------------------------------------------- 엔드포인트

PAYLOAD = {
    "userId": 1,
    "size": 4,
    "certificate": {"jmCd": "6921", "name": CERT},
    "context": {"sessionId": 1, "roadmapSteps": ["필기 이론 1회독"]},
    "excludeUrls": ["https://x/VIDEO/0"],
}


def _patch_sources(monkeypatch, **overrides):
    defaults = {
        "search_videos": AsyncMock(return_value=[_item(ResourceType.VIDEO, i) for i in range(3)]),
        "search_books": AsyncMock(return_value=[_item(ResourceType.BOOK, 0)]),
        "search_web": AsyncMock(return_value=[_item(ResourceType.WEB, 0)]),
        "search_blogs": AsyncMock(return_value=[_item(ResourceType.BLOG, 0)]),
    }
    defaults.update(overrides)
    for name, mock in defaults.items():
        monkeypatch.setattr(sources, name, mock)
    # 링크 확인은 네트워크를 쓰므로 통과시킨다.
    monkeypatch.setattr(resource_service, "_drop_unreachable", AsyncMock(side_effect=lambda items, limit: items))
    return defaults


def test_endpoint_mixes_types_and_excludes_seen_urls(client, monkeypatch):
    mocks = _patch_sources(monkeypatch)

    res = client.post("/resources/recommendations", json=PAYLOAD)

    assert res.status_code == 200
    items = res.json()["items"]
    # 가짜 자료의 제목은 "종류+번호"다. 종류를 번갈아 담고, 이미 본 VIDEO0 은 뺀다.
    assert [i["title"] for i in items] == ["VIDEO1", "BOOK0", "WEB0", "BLOG0"]
    # 명세의 네 필드만 보낸다(백엔드 요청).
    assert all(set(i) == {"title", "url", "reason", "expiration_date"} for i in items)
    mocks["search_videos"].assert_awaited_once_with(CERT, "필기")


def test_one_source_failing_does_not_fail_request(client, monkeypatch):
    _patch_sources(monkeypatch, search_videos=AsyncMock(side_effect=sources.SourceUnavailable("YouTube")))

    res = client.post("/resources/recommendations", json=PAYLOAD)

    assert res.status_code == 200
    assert not any(i["title"].startswith("VIDEO") for i in res.json()["items"])


def test_all_sources_failing_maps_to_502(client, monkeypatch):
    fail = AsyncMock(side_effect=sources.SourceUnavailable("x"))
    _patch_sources(monkeypatch, search_videos=fail, search_books=fail, search_web=fail, search_blogs=fail)

    res = client.post("/resources/recommendations", json=PAYLOAD)

    assert res.status_code == 502
    assert res.json()["code"] == "RESOURCE_SOURCES_UNAVAILABLE"


def test_looks_up_name_when_missing(client, monkeypatch):
    mocks = _patch_sources(monkeypatch)
    monkeypatch.setattr(resource_service, "get_certification", AsyncMock(return_value={"jmNm": CERT}))

    res = client.post("/resources/recommendations", json={**PAYLOAD, "certificate": {"jmCd": "6921"}})

    assert res.status_code == 200
    assert mocks["search_books"].await_args.args == (CERT,)


def test_types_filter(client, monkeypatch):
    _patch_sources(monkeypatch)

    res = client.post("/resources/recommendations", json={**PAYLOAD, "types": ["BOOK"]})

    assert all(i["title"].startswith("BOOK") for i in res.json()["items"])


# ------------------------------------------------------------ 보관 기한

def test_expiration_is_days_until_expiry(client, monkeypatch):
    """expiration_date 는 날짜가 아니라 며칠 뒤 만료되는지(일)다. 키 이름은 명세대로 snake_case."""
    _patch_sources(monkeypatch)

    items = client.post("/resources/recommendations", json=PAYLOAD).json()["items"]

    assert {i["expiration_date"] for i in items} == {7}
