"""선택된 자격증(jmCd)이 챗봇·로드맵에 반영되는지 확인한다.

사용자는 자격증을 하나 고른 뒤 대화를 시작하므로, 두 엔드포인트 모두 대상 자격증이
정해진 상태로 호출된다. 대화에서 자격증을 추측하지 않는다.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.chains.chat_chain import run_chat_chain
from app.chains.roadmap_chain import RoadmapDraft, RoadmapStepDraft, run_roadmap_chain

CERT = {
    "jmCd": "1320",
    "jmNm": "정보처리기사",
    "qualGbNm": "국가기술자격",
    "seriesNm": "기사",
    "mdobligFldNm": "정보기술",
    "job": "정보시스템의 분석·설계·구현 업무",
    "summary": "컴퓨터를 효과적으로 활용하기 위한 자격",
    "career": "소프트웨어 개발업체 등",
}

SCHEDULES = [
    {
        "description": "국가기술자격 기사 (2026년도 제3회)",
        "implSeq": "3",
        "events": [
            {"label": "필기 시험", "start": "2026-08-07", "end": "2026-09-01", "upcoming": True},
            {"label": "실기 원서접수", "start": "2026-09-21", "end": "2026-10-19", "upcoming": True},
        ],
    }
]


class FakeModel:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[list] = []

    def bind_tools(self, _tools):
        return self

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return self.response


def _system_text(model: FakeModel) -> str:
    return str(model.calls[0][0].content)


def _all_text(model: FakeModel) -> str:
    return "\n".join(str(getattr(m, "content", "")) for m in model.calls[0])


@pytest.fixture
def patch_cert(monkeypatch):
    def _apply(target, module: str):
        monkeypatch.setattr(f"{module}.get_certification", AsyncMock(return_value=target))

    return _apply


def test_chat_tells_model_which_certification_was_selected(monkeypatch, patch_cert):
    """선택된 자격증 정보가 시스템 프롬프트에 들어가야 한다."""
    patch_cert(CERT, "app.chains.chat_chain")
    model = FakeModel(AIMessage(content="네, 정보처리기사 기준으로 안내할게요."))
    monkeypatch.setattr("app.chains.chat_chain.get_chat_model", lambda **_: model)

    asyncio.run(run_chat_chain([], "언제부터 준비할까?", jm_cd="1320"))

    system = _system_text(model)
    assert "정보처리기사" in system
    assert "1320" in system


def test_chat_works_without_selected_certification(monkeypatch, patch_cert):
    """jmCd가 없으면 자격증 안내 없이 평소대로 동작한다."""
    patch_cert(None, "app.chains.chat_chain")
    model = FakeModel(AIMessage(content="어떤 자격증을 준비하시나요?"))
    monkeypatch.setattr("app.chains.chat_chain.get_chat_model", lambda **_: model)

    answer = asyncio.run(run_chat_chain([], "안녕하세요"))

    assert answer == "어떤 자격증을 준비하시나요?"
    assert "선택한 자격증" not in _system_text(model)


def test_roadmap_uses_real_exam_dates_of_selected_certification(monkeypatch, patch_cert):
    """로드맵은 선택된 자격증의 실제 시험일정을 근거로 받아야 한다."""
    patch_cert(CERT, "app.chains.roadmap_chain")
    monkeypatch.setattr(
        "app.chains.roadmap_chain.fetch_exam_schedules", AsyncMock(return_value=SCHEDULES)
    )
    draft = RoadmapDraft(
        title="정보처리기사 3개월 플랜",
        steps=[RoadmapStepDraft(title="필기 1회독", description="5과목", order_no=1)],
    )
    model = FakeModel(draft)
    monkeypatch.setattr("app.chains.roadmap_chain.get_chat_model", lambda **_: model)

    asyncio.run(run_roadmap_chain([], jm_cd="1320"))

    prompt = _all_text(model)
    assert "2026-08-07" in prompt
    assert "실기 원서접수" in prompt


CLOSED_ROUND = [
    {
        # 필기 접수가 끝나고 실기만 남은 회차. 필기를 안 본 학생은 응시할 수 없다.
        "description": "2026년도 제3회",
        "implSeq": "3",
        "events": [
            {"label": "필기 원서접수", "start": "2026-07-20", "end": "2026-07-23", "upcoming": False},
            {"label": "실기 원서접수", "start": "2026-09-21", "end": "2026-10-19", "upcoming": True},
            {"label": "실기 시험", "start": "2026-11-14", "end": "2026-11-28", "upcoming": True},
        ],
    }
]


def _run_roadmap_with(monkeypatch, patch_cert, schedules) -> str:
    patch_cert(CERT, "app.chains.roadmap_chain")
    monkeypatch.setattr(
        "app.chains.roadmap_chain.fetch_exam_schedules", AsyncMock(return_value=schedules)
    )
    draft = RoadmapDraft(
        title="플랜", steps=[RoadmapStepDraft(title="스텝", description="설명", order_no=1)]
    )
    model = FakeModel(draft)
    monkeypatch.setattr("app.chains.roadmap_chain.get_chat_model", lambda **_: model)
    asyncio.run(run_roadmap_chain([], jm_cd="1320"))
    return _all_text(model)


def test_roadmap_hides_rounds_closed_to_new_applicants(monkeypatch, patch_cert):
    """접수가 끝난 회차만 있으면 그 날짜를 넘기지 않는다.

    넘기면 모델이 남은 실기 날짜를 목표로 잡아, 필기를 안 본 학생에게 응시할 수 없는
    일정을 만든다(실제로 그랬다).
    """
    prompt = _run_roadmap_with(monkeypatch, patch_cert, CLOSED_ROUND)

    assert "새로 원서접수할 수 있는 회차가 없습니다" in prompt
    assert "아직 공개되지 않았습니다" in prompt
    assert "2026-11-14" not in prompt


def test_roadmap_tells_model_when_no_schedule_at_all(monkeypatch, patch_cert):
    prompt = _run_roadmap_with(monkeypatch, patch_cert, [])

    assert "등록된 시험일정이 없습니다" in prompt


def test_roadmap_keeps_open_round_dates(monkeypatch, patch_cert):
    """접수 가능한 회차가 하나라도 있으면 실제 날짜를 그대로 넘긴다."""
    open_round = [
        {
            "description": "2027년도 제1회",
            "implSeq": "1",
            "events": [
                {"label": "필기 원서접수", "start": "2027-01-12", "end": "2027-01-15", "upcoming": True},
                {"label": "필기 시험", "start": "2027-02-07", "end": "2027-02-07", "upcoming": True},
            ],
        }
    ]
    prompt = _run_roadmap_with(monkeypatch, patch_cert, CLOSED_ROUND + open_round)

    assert "2027-01-12" in prompt
    assert "새로 원서접수할 수 있는 회차가 없습니다" not in prompt


def test_roadmap_falls_back_when_no_schedule(monkeypatch, patch_cert):
    """일정이 없어도 실패하지 않고 대화 맥락만으로 로드맵을 만든다."""
    patch_cert(CERT, "app.chains.roadmap_chain")
    monkeypatch.setattr(
        "app.chains.roadmap_chain.fetch_exam_schedules", AsyncMock(return_value=[])
    )
    draft = RoadmapDraft(
        title="플랜",
        steps=[RoadmapStepDraft(title="스텝", description="설명", order_no=1)],
    )
    model = FakeModel(draft)
    monkeypatch.setattr("app.chains.roadmap_chain.get_chat_model", lambda **_: model)

    result = asyncio.run(run_roadmap_chain([], jm_cd="1320"))

    assert result.title == "플랜"
