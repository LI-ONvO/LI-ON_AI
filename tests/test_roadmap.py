from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from app.chains.roadmap_chain import RoadmapDraft, RoadmapStepDraft
from app.core.exceptions import LLMOutputError, LLMTimeoutError
from app.services.roadmap_service import normalize_steps

TODAY = date(2026, 8, 6)


def make_draft(*steps: RoadmapStepDraft, title: str = "AI가 만든 제목") -> RoadmapDraft:
    return RoadmapDraft(title=title, steps=list(steps))


def step(order_no: int, target_date: date | None = None, title: str | None = None) -> RoadmapStepDraft:
    return RoadmapStepDraft(
        title=title if title is not None else f"스텝 {order_no}",
        description=f"설명 {order_no}",
        order_no=order_no,
        target_date=target_date,
    )


@pytest.fixture
def mock_chain(monkeypatch):
    def _apply(**kwargs) -> AsyncMock:
        mock = AsyncMock(**kwargs)
        monkeypatch.setattr("app.services.roadmap_service.run_roadmap_chain", mock)
        return mock

    return _apply


# --------------------------------------------------------------------------
# 엔드포인트
# --------------------------------------------------------------------------


def test_roadmap_returns_camel_case_fields(client, mock_chain):
    mock_chain(
        return_value=make_draft(
            step(1, TODAY + timedelta(days=9)),
            step(2, TODAY + timedelta(days=26)),
            title="3개월 속성 플랜",
        )
    )

    res = client.post("/v1/roadmap", json={"sessionId": 1, "jmCd": "1320", "history": []})

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "3개월 속성 플랜"
    assert len(body["steps"]) == 2

    first = body["steps"][0]
    # 백엔드 명세와 동일한 camelCase 키여야 한다.
    assert set(first) == {"title", "description", "orderNo", "targetDate"}
    assert first["orderNo"] == 1


def test_client_title_overrides_ai_title(client, mock_chain):
    mock_chain(return_value=make_draft(step(1), title="AI가 만든 제목"))

    res = client.post("/v1/roadmap", json={"sessionId": 1, "jmCd": "1320", "title": "3개월 속성 플랜"})

    assert res.status_code == 200
    assert res.json()["title"] == "3개월 속성 플랜"


def test_ai_title_used_when_not_given(client, mock_chain):
    mock_chain(return_value=make_draft(step(1), title="AI가 만든 제목"))

    res = client.post("/v1/roadmap", json={"sessionId": 1, "jmCd": "1320"})

    assert res.status_code == 200
    assert res.json()["title"] == "AI가 만든 제목"


def test_roadmap_without_steps_maps_to_502(client, mock_chain):
    mock_chain(side_effect=LLMOutputError())

    res = client.post("/v1/roadmap", json={"sessionId": 1, "jmCd": "1320"})

    assert res.status_code == 502
    assert res.json()["code"] == "LLM_OUTPUT_INVALID"


def test_roadmap_timeout_maps_to_504(client, mock_chain):
    mock_chain(side_effect=LLMTimeoutError())

    res = client.post("/v1/roadmap", json={"sessionId": 1, "jmCd": "1320"})

    assert res.status_code == 504
    assert res.json()["code"] == "LLM_TIMEOUT"


def test_roadmap_rejects_missing_session_id(client):
    res = client.post("/v1/roadmap", json={})

    assert res.status_code == 422


# --------------------------------------------------------------------------
# 정규화 로직
# --------------------------------------------------------------------------


def test_order_no_is_renumbered_sequentially():
    """LLM이 번호를 건너뛰거나 순서를 섞어도 결과는 항상 1..N 이어야 한다."""
    draft = make_draft(step(9), step(3), step(5))

    steps = normalize_steps(draft, today=TODAY)

    assert [s.order_no for s in steps] == [1, 2, 3]
    # order_no 오름차순으로 정렬된 뒤 번호가 다시 매겨진다.
    assert [s.title for s in steps] == ["스텝 3", "스텝 5", "스텝 9"]


def test_past_target_date_is_dropped():
    draft = make_draft(step(1, TODAY - timedelta(days=1)))

    steps = normalize_steps(draft, today=TODAY)

    assert steps[0].target_date is None


def test_today_target_date_is_kept():
    draft = make_draft(step(1, TODAY))

    steps = normalize_steps(draft, today=TODAY)

    assert steps[0].target_date == TODAY


def test_backwards_target_date_is_dropped():
    """뒤 스텝이 앞 스텝보다 이른 날짜면 그 스텝의 날짜만 버린다."""
    draft = make_draft(
        step(1, TODAY + timedelta(days=30)),
        step(2, TODAY + timedelta(days=10)),
        step(3, TODAY + timedelta(days=40)),
    )

    steps = normalize_steps(draft, today=TODAY)

    assert steps[0].target_date == TODAY + timedelta(days=30)
    assert steps[1].target_date is None
    assert steps[2].target_date == TODAY + timedelta(days=40)


def test_blank_title_step_is_skipped():
    draft = make_draft(step(1), step(2, title="   "), step(3))

    steps = normalize_steps(draft, today=TODAY)

    assert [s.order_no for s in steps] == [1, 2]
    assert [s.title for s in steps] == ["스텝 1", "스텝 3"]


def test_whitespace_is_trimmed():
    draft = make_draft(step(1, title="  필기 이론 1회독  "))

    steps = normalize_steps(draft, today=TODAY)

    assert steps[0].title == "필기 이론 1회독"


def test_null_target_dates_are_allowed():
    draft = make_draft(step(1), step(2), step(3))

    steps = normalize_steps(draft, today=TODAY)

    assert all(s.target_date is None for s in steps)
    assert [s.order_no for s in steps] == [1, 2, 3]
