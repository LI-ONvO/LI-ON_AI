from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from app.chains.roadmap_chain import RoadmapDraft, RoadmapStepDraft
from app.core.exceptions import LLMOutputError, LLMTimeoutError, RoadmapTargetUnknownError
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

    res = client.post("/roadmaps", json={"sessionId": 1, "jmCd": "1320", "history": []})

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

    res = client.post("/roadmaps", json={"sessionId": 1, "jmCd": "1320", "title": "3개월 속성 플랜"})

    assert res.status_code == 200
    assert res.json()["title"] == "3개월 속성 플랜"


def test_ai_title_used_when_not_given(client, mock_chain):
    mock_chain(return_value=make_draft(step(1), title="AI가 만든 제목"))

    res = client.post("/roadmaps", json={"sessionId": 1, "jmCd": "1320"})

    assert res.status_code == 200
    assert res.json()["title"] == "AI가 만든 제목"


def test_roadmap_without_steps_maps_to_502(client, mock_chain):
    mock_chain(side_effect=LLMOutputError())

    res = client.post("/roadmaps", json={"sessionId": 1, "jmCd": "1320"})

    assert res.status_code == 502
    assert res.json()["code"] == "LLM_OUTPUT_INVALID"


def test_roadmap_timeout_maps_to_504(client, mock_chain):
    mock_chain(side_effect=LLMTimeoutError())

    res = client.post("/roadmaps", json={"sessionId": 1, "jmCd": "1320"})

    assert res.status_code == 504
    assert res.json()["code"] == "LLM_TIMEOUT"


def test_roadmap_rejects_missing_session_id(client):
    res = client.post("/roadmaps", json={})

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


# --------------------------------------------------------------------------
# 팀 명세서 요청 형식
# --------------------------------------------------------------------------

SPEC_PAYLOAD = {
    "sessionId": 1,
    "today": "2026-10-13",
    "user": {
        "nickname": "건",
        "onboarding": [{"title": "하루 학습 가능 시간", "values": ["1~2시간"]}],
    },
    "certificate": {
        "jmCd": "6921",
        "name": "프로그래밍기능사",
        "category": None,
        "description": None,
        "examSchedules": [{"implYy": 2026, "implSeq": "04", "docRegStartDt": "2026-08-24"}],
    },
    "messages": [
        {"sender": "USER", "content": "3개월 안에 따고 싶어요"},
        {"sender": "AI", "content": "좋아요"},
    ],
    "title": None,
}


def test_accepts_team_spec_request(client, mock_chain):
    """명세서 형식(certificate 객체, messages)으로 와도 받아야 한다."""
    mock = mock_chain(return_value=make_draft(step(1)))

    res = client.post("/roadmaps", json=SPEC_PAYLOAD)

    assert res.status_code == 200
    history, jm_cd, title = mock.call_args.args
    assert jm_cd == "6921"
    # messages 를 history 로 받지 못하면 오류 없이 대화가 빠진다.
    assert [m.content for m in history] == ["3개월 안에 따고 싶어요", "좋아요"]
    assert mock.call_args.kwargs["user"].onboarding[0].values == ["1~2시간"]


def test_null_certificate_falls_back_to_conversation(client, mock_chain):
    """자격증을 고르지 않고 대화만 한 세션은 certificate 가 null 이다. 대화에서 찾도록 넘긴다."""
    mock = mock_chain(return_value=make_draft(step(1)))

    res = client.post("/roadmaps", json={**SPEC_PAYLOAD, "certificate": None})

    assert res.status_code == 200
    assert mock.call_args.args[1] is None


def test_rejects_request_without_certificate_and_messages(client, mock_chain):
    mock_chain(return_value=make_draft(step(1)))

    res = client.post("/roadmaps", json={**SPEC_PAYLOAD, "certificate": None, "messages": []})

    assert res.status_code == 422


# --------------------------------------------------------------------------
# 대화에서 목표 자격증 찾기
# --------------------------------------------------------------------------

from app.chains import roadmap_chain  # noqa: E402
from app.chains.roadmap_chain import TargetCertification, infer_jm_cd  # noqa: E402
from app.schemas.chat import ChatMessage  # noqa: E402


class _NameModel:
    def __init__(self, name):
        self.name = name

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _messages):
        return TargetCertification(name=self.name)


def _infer(monkeypatch, name, matches):
    import asyncio

    monkeypatch.setattr(roadmap_chain, "get_chat_model", lambda **_: _NameModel(name))
    monkeypatch.setattr(
        roadmap_chain, "_resolve", AsyncMock(return_value={"total": len(matches), "matches": matches})
    )
    history = [ChatMessage(sender="USER", content="프로그래밍기능사 따고 싶어요")]
    return asyncio.run(infer_jm_cd(history))


PROG = {"jmCd": "6921", "jmNm": "프로그래밍기능사", "qualGbNm": "국가기술자격"}


def test_infers_code_from_conversation(monkeypatch):
    assert _infer(monkeypatch, "프로그래밍기능사", [PROG]) == "6921"


def test_prefers_exact_name_among_several(monkeypatch):
    """'정보처리기사'로 찾으면 정보처리산업기사 등도 걸린다. 이름이 정확히 같은 것을 쓴다."""
    matches = [
        {"jmCd": "1320", "jmNm": "정보처리기사", "qualGbNm": "국가기술자격"},
        {"jmCd": "2290", "jmNm": "정보처리산업기사", "qualGbNm": "국가기술자격"},
    ]
    assert _infer(monkeypatch, "정보처리기사", matches) == "1320"


def test_gives_up_when_ambiguous_or_missing(monkeypatch):
    """하나로 정해지지 않으면 틀린 자격증 일정을 쓰지 않고 None 을 준다."""
    many = [{"jmCd": c, "jmNm": f"{c}기능사", "qualGbNm": "국가기술자격"} for c in ("1", "2")]
    assert _infer(monkeypatch, "기능사", many) is None
    assert _infer(monkeypatch, "없는자격증", []) is None


def test_no_target_in_conversation_is_reported(monkeypatch):
    """대화에 목표 자격증이 없으면 서버 오류(502)가 아니라 전용 오류로 알린다."""
    with pytest.raises(RoadmapTargetUnknownError):
        _infer(monkeypatch, None, [PROG])


def test_no_target_maps_to_422(client, mock_chain):
    mock_chain(side_effect=RoadmapTargetUnknownError())

    res = client.post("/roadmaps", json={**SPEC_PAYLOAD, "certificate": None})

    assert res.status_code == 422
    assert res.json()["code"] == "ROADMAP_TARGET_UNKNOWN"
