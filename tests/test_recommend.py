"""자격증 추천 테스트.

모델이 목록에 없는 종목코드를 만들어내거나 같은 자격증을 중복으로 고를 수 있다.
백엔드가 그대로 화면에 쓰는 데이터이므로 서비스 계층이 걸러내는지 확인한다.
"""

from unittest.mock import AsyncMock

import pytest

from app.chains.recommend_chain import RecommendationDraft
from app.core.exceptions import LLMOutputError, LLMTimeoutError
from app.services.recommend_service import normalize_items

VALID = {"1320", "2290", "6892"}


def _draft(jm_cd: str, reason: str = "이유") -> RecommendationDraft:
    return RecommendationDraft(jm_cd=jm_cd, reason=reason)


@pytest.fixture
def mock_chain(monkeypatch):
    """recommend_service가 호출하는 체인을 교체한다."""

    def _apply(**kwargs) -> AsyncMock:
        mock = AsyncMock(**kwargs)
        monkeypatch.setattr("app.services.recommend_service.run_recommend_chain", mock)
        return mock

    return _apply


def _payload(size: int = 5) -> dict:
    return {
        "userId": 1,
        "size": size,
        "user": {
            "nickname": "시흔",
            "desiredFields": ["클라우드", "보안"],
            "onboarding": [
                {"key": "study_time", "title": "하루 학습 가능 시간", "values": ["1~2시간"]}
            ],
        },
    }


# --------------------------------------------------------------- 정규화 로직

def test_drops_codes_that_do_not_exist():
    """모델이 지어낸 종목코드는 버린다."""
    items = normalize_items([_draft("1320"), _draft("9999"), _draft("2290")], VALID, 5)

    assert [i.jm_cd for i in items] == ["1320", "2290"]


def test_drops_duplicates():
    items = normalize_items([_draft("1320"), _draft("1320"), _draft("2290")], VALID, 5)

    assert [i.jm_cd for i in items] == ["1320", "2290"]


def test_drops_items_without_reason():
    items = normalize_items([_draft("1320", "  "), _draft("2290", "이유")], VALID, 5)

    assert [i.jm_cd for i in items] == ["2290"]


def test_truncates_to_requested_size():
    items = normalize_items([_draft("1320"), _draft("2290"), _draft("6892")], VALID, 2)

    assert len(items) == 2


# ------------------------------------------------------------------ 엔드포인트

def test_recommend_returns_items(client, mock_chain):
    mock_chain(return_value=([_draft("1320", "정보기술 기초가 됩니다.")], VALID))

    res = client.post("/v1/recommend", json=_payload())

    assert res.status_code == 200
    assert res.json() == {"items": [{"jmCd": "1320", "reason": "정보기술 기초가 됩니다."}]}


def test_recommend_size_is_capped(client, mock_chain):
    """모델이 요청보다 많이 골라도 size 개까지만 내보낸다."""
    mock_chain(return_value=([_draft("1320"), _draft("2290"), _draft("6892")], VALID))

    res = client.post("/v1/recommend", json=_payload(size=2))

    assert res.status_code == 200
    assert len(res.json()["items"]) == 2


def test_all_invalid_codes_maps_to_502(client, mock_chain):
    """남는 추천이 하나도 없으면 빈 목록 대신 오류로 알린다."""
    mock_chain(return_value=([_draft("9999"), _draft("8888")], VALID))

    res = client.post("/v1/recommend", json=_payload())

    assert res.status_code == 502
    assert res.json()["code"] == "LLM_OUTPUT_INVALID"


def test_recommend_timeout_maps_to_504(client, mock_chain):
    mock_chain(side_effect=LLMTimeoutError())

    res = client.post("/v1/recommend", json=_payload())

    assert res.status_code == 504


def test_size_out_of_range_is_rejected(client):
    res = client.post("/v1/recommend", json=_payload(size=0))

    assert res.status_code == 422
