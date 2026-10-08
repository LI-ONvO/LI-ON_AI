"""자격증 추천 테스트.

모델이 목록에 없는 종목코드를 만들어내거나 같은 자격증을 중복으로 고를 수 있다.
백엔드가 그대로 화면에 쓰는 데이터이므로 서비스 계층이 걸러내는지 확인한다.
"""

from unittest.mock import AsyncMock

import pytest

from app.chains.recommend_chain import RecommendationDraft
from app.core.exceptions import LLMOutputError, LLMTimeoutError
from app.services.recommend_service import normalize_items

VALID = {"1320": "기사", "2290": "산업기사", "6892": "기능사"}


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

    res = client.post("/recommendations", json=_payload())

    assert res.status_code == 200
    assert res.json()["items"][0]["jmCd"] == "1320"
    assert res.json()["items"][0]["reason"].startswith("정보기술 기초가 됩니다.")


def test_recommend_size_is_capped(client, mock_chain):
    """모델이 요청보다 많이 골라도 size 개까지만 내보낸다."""
    mock_chain(return_value=([_draft("1320"), _draft("2290"), _draft("6892")], VALID))

    res = client.post("/recommendations", json=_payload(size=2))

    assert res.status_code == 200
    assert len(res.json()["items"]) == 2


def test_all_invalid_codes_maps_to_502(client, mock_chain):
    """남는 추천이 하나도 없으면 빈 목록 대신 오류로 알린다."""
    mock_chain(return_value=([_draft("9999"), _draft("8888")], VALID))

    res = client.post("/recommendations", json=_payload())

    assert res.status_code == 502
    assert res.json()["code"] == "LLM_OUTPUT_INVALID"


def test_recommend_timeout_maps_to_504(client, mock_chain):
    mock_chain(side_effect=LLMTimeoutError())

    res = client.post("/recommendations", json=_payload())

    assert res.status_code == 504


def test_size_out_of_range_is_rejected(client):
    res = client.post("/recommendations", json=_payload(size=0))

    assert res.status_code == 422


def test_drops_weakly_related_items():
    """모델이 관련도 "약함"으로 표시한 항목은 개수를 채우는 용도이므로 버린다."""
    weak = RecommendationDraft(jm_cd="2290", reason="이유", fit="약함")
    items = normalize_items([_draft("6892"), weak], VALID, 5)

    assert [i.jm_cd for i in items] == ["6892"]


def test_adds_eligibility_note_to_upper_grades():
    """고등학생은 산업기사·기사에 바로 응시할 수 없으므로 안내를 붙인다. 기능사에는 붙이지 않는다."""
    items = normalize_items([_draft("6892"), _draft("2290"), _draft("1320")], VALID, 5)
    reasons = {i.jm_cd: i.reason for i in items}

    assert reasons["6892"] == "이유"
    assert "응시할 수" in reasons["2290"] and "산업기사" in reasons["2290"]
    assert "응시할 수" in reasons["1320"] and "산업기사" not in reasons["1320"]


def test_grade_is_read_from_name_not_series():
    """seriesNm 은 산업기사도 "기사"로 오므로 이름에서 등급을 읽는다."""
    from app.chains.recommend_chain import _grade

    assert _grade("정보처리산업기사", "기사") == "산업기사"
    assert _grade("정보처리기사", "기사") == "기사"
    assert _grade("미용사(네일)", "기능사") == "기능사"
    assert _grade("소방설비산업기사(기계분야)", "기사") == "산업기사"
    assert _grade("사회조사분석사2급", "기사") == "기타(기사 계열)"
