"""학습 자료 외부 API 호출 한도 처리."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.repositories import resource_sources as sources
from tests.test_resources import CERT, PAYLOAD, _patch_sources


@pytest.fixture(autouse=True)
def _keys_and_state(monkeypatch):
    for name in ("youtube_api_key", "kakao_rest_api_key", "naver_client_id", "naver_client_secret"):
        monkeypatch.setattr(settings, name, "test")
    sources._cache.clear()
    sources._blocked_until.clear()
    yield
    sources._cache.clear()
    sources._blocked_until.clear()


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = str(body)

    def json(self):
        return self._body


def _patch_http(monkeypatch, response):
    calls = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            calls.append(url)
            return response

    monkeypatch.setattr(sources.httpx, "AsyncClient", _Client)
    return calls


def test_youtube_quota_blocks_until_reset(monkeypatch):
    """한도가 차면 그 뒤 요청은 YouTube 를 부르지 않는다(실패할 줄 알면서 응답만 늦어진다)."""
    calls = _patch_http(monkeypatch, _FakeResponse(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}))

    with pytest.raises(sources.SourceQuotaExceeded):
        asyncio.run(sources.search_videos(CERT, None))
    with pytest.raises(sources.SourceQuotaExceeded):
        asyncio.run(sources.search_videos(f"{CERT}2", None))

    assert len(calls) == 1
    # 다음 초기화(태평양 자정) 전까지만 막는다.
    assert 0 < sources._blocked_until["YOUTUBE"] - time.time() <= 24 * 3600


def test_naver_429_blocks_both_web_and_blog(monkeypatch):
    """NAVER 웹문서·블로그는 한도를 함께 쓴다. 하나가 막히면 둘 다 막는다."""
    calls = _patch_http(monkeypatch, _FakeResponse(429, {"message": "Too Many Requests"}))

    with pytest.raises(sources.SourceQuotaExceeded):
        asyncio.run(sources.search_web(CERT))
    with pytest.raises(sources.SourceQuotaExceeded):
        asyncio.run(sources.search_blogs(CERT, None))

    assert len(calls) == 1
    assert sources._blocked_until["NAVER"] - time.time() <= sources.RATE_LIMIT_COOLDOWN_SECONDS


def test_other_youtube_403_is_not_treated_as_quota(monkeypatch):
    """키가 잘못된 403 등은 한도 초과가 아니다. 막아 두지 않는다."""
    _patch_http(monkeypatch, _FakeResponse(403, {"error": {"errors": [{"reason": "forbidden"}]}}))

    with pytest.raises(sources.SourceUnavailable) as info:
        asyncio.run(sources.search_videos(CERT, None))

    assert not isinstance(info.value, sources.SourceQuotaExceeded)
    assert "YOUTUBE" not in sources._blocked_until


def test_quota_on_some_sources_still_returns_the_rest(client, monkeypatch):
    """한도가 찬 종류만 빠지고 나머지로 응답한다."""
    _patch_sources(
        monkeypatch,
        search_videos=AsyncMock(side_effect=sources.SourceQuotaExceeded("YOUTUBE")),
        search_blogs=AsyncMock(side_effect=sources.SourceNotConfigured("NAVER")),
    )

    res = client.post("/resources/recommendations", json=PAYLOAD)

    assert res.status_code == 200
    assert [i["title"] for i in res.json()["items"]] == ["BOOK0", "WEB0"]


def test_all_quota_exceeded_maps_to_503(client, monkeypatch):
    quota = AsyncMock(side_effect=sources.SourceQuotaExceeded("x"))
    _patch_sources(monkeypatch, search_videos=quota, search_books=quota, search_web=quota, search_blogs=quota)

    res = client.post("/resources/recommendations", json=PAYLOAD)

    assert res.status_code == 503
    assert res.json()["code"] == "RESOURCE_QUOTA_EXCEEDED"
