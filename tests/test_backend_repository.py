"""자격증 조회를 백엔드 API 로 바꾼 부분 테스트.

백엔드는 DB 행에 가까운 형태로 주고, 모델에게 보여줄 모양은 여기서 만든다.
그 변환(필드 이름, 순위, 연도 거르기, 일정 라벨)이 맞는지 본다. 네트워크는 쓰지 않는다.
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core import backend
from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.repositories import certifications as repo


@pytest.fixture(autouse=True)
def _clear_detail_cache():
    repo._detail_cache.clear()
    yield
    repo._detail_cache.clear()


def _mock_get_json(responses: dict):
    """경로별로 정해둔 응답을 돌려주는 가짜 get_json."""

    async def fake(path, params=None):
        return responses.get(path)

    return AsyncMock(side_effect=fake)


# ---------------------------------------------------------------------- 검색

def test_search_maps_fields_and_adds_rank():
    body = {
        "content": [
            {"jmCd": "7910", "name": "한식조리기능사", "seriesNm": "기능사",
             "mdobligFldNm": "조리", "job": "가" * 1000, "summary": None,
             "career": "c", "hist": "h", "score": 150},
            {"jmCd": "7911", "name": "양식조리기능사", "seriesNm": "기능사",
             "mdobligFldNm": "조리", "job": None, "summary": "s",
             "career": None, "hist": None, "score": 100},
        ],
        "totalElements": 2,
    }
    with patch.object(repo, "get_json", _mock_get_json({"/api/certificates/search": body})):
        results = asyncio.run(repo.search_certifications(["요리", "조리"]))

    assert [r["rank"] for r in results] == [1, 2]
    assert results[0]["jmNm"] == "한식조리기능사"
    assert results[0]["relevanceScore"] == 150
    # 설명이 길면 잘라서 프롬프트가 불어나지 않게 한다.
    assert len(results[0]["job"]) == settings.max_field_chars


def test_search_cleans_keywords_before_calling_backend():
    """백엔드는 키워드 5개를 넘기면 422 로 거절한다. 공백·중복도 미리 걸러 보낸다."""
    mock = _mock_get_json({"/api/certificates/search": {"content": []}})
    with patch.object(repo, "get_json", mock):
        asyncio.run(repo.search_certifications([" a ", "a", "", "b", "c", "d", "e", "f"]))

    params = mock.call_args.args[1]
    assert params["keywords"] == "a,b,c,d,e"


def test_search_with_no_keywords_does_not_call_backend():
    mock = _mock_get_json({})
    with patch.object(repo, "get_json", mock):
        assert asyncio.run(repo.search_certifications(["", "  "])) == []
    mock.assert_not_called()


# ---------------------------------------------------------------- 종목 찾기

def test_resolve_keeps_total_before_limit():
    """잘린 목록을 전부로 오해하지 않도록 백엔드의 전체 개수를 그대로 쓴다."""
    body = {"content": [{"jmCd": "6921", "name": "프로그래밍기능사", "qualGbCd": "T"}],
            "totalElements": 2}
    with patch.object(repo, "get_json", _mock_get_json({"/api/certificates/resolve": body})):
        result = asyncio.run(repo.resolve_certification("프로그래밍기능사", limit=1))

    assert result["total"] == 2
    assert result["matches"] == [
        {"jmCd": "6921", "jmNm": "프로그래밍기능사", "qualGbNm": "국가기술자격"}
    ]


# -------------------------------------------------------------------- 상세

DETAIL = {
    "jmCd": "1320", "name": "정보처리기사", "category": "기사",
    "description": "개요 문장", "qualGbCd": "T", "seriesNm": "기사",
    "mdobligFldNm": "정보기술", "job": "직무", "career": "진로",
    "docPassRate": 65.05, "pracPassRate": None, "docFee": 19400, "pracFee": 22600,
    "examSchedules": [],
}


def test_get_certification_maps_description_to_summary():
    with patch.object(repo, "get_json", _mock_get_json({"/api/certificates/1320": DETAIL})):
        cert = asyncio.run(repo.get_certification("1320"))

    assert cert["jmNm"] == "정보처리기사"
    assert cert["qualGbNm"] == "국가기술자격"
    assert cert["summary"] == "개요 문장"


def test_unknown_certification_returns_none():
    with patch.object(repo, "get_json", _mock_get_json({})):
        assert asyncio.run(repo.get_certification("0000")) is None
        assert asyncio.run(repo.fetch_exam_schedules("0000")) == []


def test_pass_rate_and_fee_skip_nulls():
    with patch.object(repo, "get_json", _mock_get_json({"/api/certificates/1320": DETAIL})):
        rate = asyncio.run(repo.fetch_pass_rate("1320"))
        fee = asyncio.run(repo.fetch_exam_fee("1320"))

    assert rate == {"passRates": [{"examType": "필기", "passRate": 65.05}]}
    assert fee == {"fees": [{"examType": "필기", "won": 19400}, {"examType": "실기", "won": 22600}]}


def test_detail_is_fetched_once_per_certification():
    """로드맵은 종목 정보와 올해·내년 일정을 따로 부른다. 같은 상세를 세 번 가져오지 않는다."""
    mock = _mock_get_json({"/api/certificates/1320": DETAIL})
    with patch.object(repo, "get_json", mock):
        asyncio.run(repo.get_certification("1320"))
        asyncio.run(repo.fetch_exam_schedules("1320", 2026))
        asyncio.run(repo.fetch_exam_schedules("1320", 2027))
        asyncio.run(repo.fetch_pass_rate("1320"))

    assert mock.call_count == 1


# -------------------------------------------------------------------- 일정

def test_schedules_filter_year_sort_and_mark_upcoming():
    today = date.today()
    past = (today - timedelta(days=30)).isoformat()
    future = (today + timedelta(days=30)).isoformat()
    year = today.year

    detail = dict(DETAIL, examSchedules=[
        {"implYy": year, "implSeq": "3", "docRegStartDt": future, "docRegEndDt": future},
        {"implYy": year, "implSeq": "01", "docRegStartDt": past, "docRegEndDt": past,
         "pracPassDt": future},
        {"implYy": year + 1, "implSeq": "1", "docRegStartDt": future},
    ])
    with patch.object(repo, "get_json", _mock_get_json({"/api/certificates/1320": detail})):
        schedules = asyncio.run(repo.fetch_exam_schedules("1320", year))

    # 다른 연도는 빠지고, "01" 과 "3" 이 숫자 순으로 정렬된다.
    assert [s["implSeq"] for s in schedules] == ["01", "3"]
    # 백엔드에 회차 설명이 없어 연도가 드러나게 만든다.
    assert schedules[0]["description"] == f"{year}년도 제1회"

    first = schedules[0]["events"]
    assert first[0]["label"] == "필기 원서접수" and first[0]["upcoming"] is False
    assert first[-1]["label"] == "실기 합격발표" and first[-1]["upcoming"] is True


# ----------------------------------------------------------------- 클라이언트

def _run_with_transport(handler, path="/api/certificates/1320"):
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    with patch.object(backend.httpx, "AsyncClient", client_factory), \
         patch.object(settings, "backend_api_base_url", "http://backend.test"), \
         patch.object(settings, "backend_api_key", "secret"):
        return asyncio.run(backend.get_json(path))


def test_client_sends_internal_key_header():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("X-Internal-Key")
        return httpx.Response(200, json={"ok": True})

    assert _run_with_transport(handler) == {"ok": True}
    assert seen["key"] == "secret"


def test_client_returns_none_on_404():
    assert _run_with_transport(lambda r: httpx.Response(404, json={})) is None


def test_client_treats_401_as_configuration_error():
    """키가 틀리면 재시도해도 소용없다. 설정 문제로 알린다."""
    with pytest.raises(ConfigurationError):
        _run_with_transport(lambda r: httpx.Response(401, json={}))


def test_client_requires_configuration():
    with patch.object(settings, "backend_api_base_url", ""), \
         patch.object(settings, "backend_api_key", ""):
        with pytest.raises(ConfigurationError):
            asyncio.run(backend.get_json("/api/certificates/1320"))
