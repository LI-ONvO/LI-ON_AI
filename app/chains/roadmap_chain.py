"""로드맵 생성 체인.

자유 텍스트가 아니라 고정 스키마(JSON)를 받아야 하므로 with_structured_output으로
모델 출력 형식을 강제한다. 이렇게 하면 "응답을 파싱 → 실패 시 재시도" 로직을 직접 짤 필요가 없다.

대화만으로는 실제 시험일을 알 수 없어 모델이 날짜를 지어낸다. 로드맵은 시험일에서
역산하는 것이 핵심이므로, DB에 저장된 실제 시험일정을 함께 넘긴다.
"""

from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, Field

from app.chains.base import build_messages
from app.chains.tools import _resolve
from app.core.config import settings
from app.core.exceptions import LLMOutputError, RoadmapTargetUnknownError
from app.core.llm import get_chat_model, llm_call_guard
from app.core.logging import get_logger
from app.prompts import render_prompt
from app.repositories.certifications import fetch_exam_schedules, get_certification
from app.schemas.chat import ChatMessage, Sender
from app.schemas.roadmap import RoadmapUser

logger = get_logger(__name__)


class RoadmapStepDraft(BaseModel):
    """LLM이 채워야 할 스텝 한 건.

    필드 설명(description)이 그대로 모델에게 전달되는 스키마가 되므로,
    프롬프트만큼 중요하게 다뤄야 한다.
    """

    title: str = Field(description="스텝 제목. 짧고 구체적으로. 예: '필기 이론 1회독'")
    description: str = Field(description="이 스텝에서 실제로 할 행동과 분량. 예: '5과목 개념 정리, 과목당 3일'")
    order_no: int = Field(description="1부터 시작하는 학습 순서")
    target_date: date | None = Field(
        default=None,
        description="이 스텝을 마치는 목표 일자(YYYY-MM-DD). 추정할 근거가 없으면 null",
    )


class RoadmapDraft(BaseModel):
    """LLM이 반환하는 로드맵 전체."""

    title: str = Field(description="로드맵 제목. 목표와 기간이 드러나게. 예: '정보처리기능사 3개월 속성 플랜'")
    steps: list[RoadmapStepDraft] = Field(description="시간 순서대로 정렬된 학습 스텝 목록")


def _format_user(user: RoadmapUser | None) -> str:
    """온보딩 답변을 프롬프트에 넣는다. 하루 학습 시간은 스텝 분량을 정하는 근거다."""
    if user is None:
        return ""
    lines = [f"- {a.title}: {', '.join(a.values)}" for a in user.onboarding if a.values]
    if not lines:
        return ""
    return "\n".join(["[사용자 정보]", *lines])


def _build_instruction(title: str | None) -> str:
    instruction = "지금까지의 대화를 근거로 학습 로드맵을 작성하세요."
    if title:
        # 제목이 지정된 경우에도 모델에게 알려준다. 로드맵 내용의 방향을 잡는 힌트가 된다.
        instruction += f'\n로드맵 제목은 "{title}"로 고정합니다. 이 제목에 맞는 내용으로 구성하세요.'
    return instruction


def _format_schedules(jm_nm: str, schedules: list[dict]) -> str:
    """실제 시험일정을 프롬프트에 넣을 텍스트로 만든다.

    회차 안에서도 필기는 끝나고 실기만 남은 경우가 있다. 그대로 넘기면 모델이
    "실기 접수 마감"을 고정점으로 잡아, 필기를 아직 안 본 학생에게 응시할 수 없는
    일정을 만들어 준다. 그래서 회차를 어떻게 읽어야 하는지 함께 알려준다.
    """
    lines = [
        f"[{jm_nm} 실제 시험일정]",
        "필기 원서접수가 [종료]인 회차는 지금 새로 응시할 수 없습니다. "
        "사용자가 이미 필기에 합격했다고 대화에서 밝힌 경우가 아니면, "
        "필기 원서접수가 [예정]인 회차를 목표로 역산하세요.",
    ]
    for schedule in schedules:
        lines.append(schedule["description"] or f"{schedule['implSeq']}회")
        for event in schedule["events"]:
            period = event["start"] if not event["end"] else f"{event['start']} ~ {event['end']}"
            mark = "예정" if event["upcoming"] else "종료"
            lines.append(f"  - [{mark}] {event['label']}: {period}")
    return "\n".join(lines)


def _is_open_for_new_applicants(schedule: dict) -> bool:
    """이 회차에 지금 새로 원서를 낼 수 있는지.

    회차의 첫 원서접수(필기가 있으면 필기, 실기만 있는 회차면 실기)가 아직 끝나지 않았어야 한다.
    필기 접수가 끝난 회차는 실기 일정이 남아 있어도 필기를 안 본 사람은 응시할 수 없다.
    """
    registrations = [e for e in schedule["events"] if e["label"].endswith("원서접수")]
    return bool(registrations) and registrations[0]["upcoming"]


def _no_open_round_note(jm_nm: str, has_any_schedule: bool) -> str:
    """새로 접수할 수 있는 회차가 없을 때 모델에게 줄 안내.

    이 경우 끝난 회차의 일정은 넘기지 않는다. 넘기면 "필기 접수 종료"라고 표시해도 모델이
    남아 있는 실기 날짜를 목표로 잡아, 필기를 안 본 학생에게 응시할 수 없는 일정을 짜 준다.
    (2026-10 실제 사례: 정보처리기사 로드맵이 접수가 끝난 3회 실기를 목표로 5주 계획을 냈다)
    """
    situation = (
        "올해 원서접수는 모두 끝났고 다음 시험 일정은 아직 공개되지 않았습니다."
        if has_any_schedule
        else "등록된 시험일정이 없습니다."
    )
    return "\n".join([
        f"[{jm_nm} 시험일정]",
        f"지금 새로 원서접수할 수 있는 회차가 없습니다. {situation}",
        "- 시험일과 원서접수일을 지어내지 마세요. 끝난 회차의 날짜를 목표로 삼지 마세요.",
        "- 대화에 학습 기간(예: 3개월)이 있으면 오늘부터 그 기간 안에서 공부 순서대로 "
        "target_date 를 정하세요. 기간을 추정할 근거가 없으면 target_date 는 null 로 두세요.",
        "- 마지막 스텝은 '다음 회차 일정 확인 후 원서접수'로 하고 target_date 는 null 로 두세요.",
        "- 로드맵 title 에 시험 회차나 시험 날짜를 넣지 마세요.",
    ])


async def _load_exam_context(jm_cd: str) -> str | None:
    """선택된 자격증의 실제 시험일정을 프롬프트용 텍스트로 만든다. 종목이 없으면 None.

    이 정보가 없으면 모델이 "3개월 남았다" 같은 말만 보고 날짜를 지어낸다.
    로드맵의 핵심은 실제 시험일에서 역산하는 것이므로 근거를 함께 넘긴다.
    """
    target = await get_certification(jm_cd)
    if target is None:
        logger.warning("종목코드 %s 를 찾지 못했습니다.", jm_cd)
        return None

    # 올해만 보면 연말에는 접수가 끝난 회차뿐이다. 실제로 9월 기준 2026년에 필기
    # 원서접수가 남은 종목은 0개였다. 내년 일정까지 함께 넘겨야 역산할 고정점이 생긴다.
    this_year = date.today().year
    schedules: list[dict] = []
    for year in (this_year, this_year + 1):
        schedules.extend(await fetch_exam_schedules(jm_cd, year))

    # 모든 일정이 지나간 회차는 로드맵의 근거가 되지 못하고 프롬프트만 늘린다.
    schedules = [s for s in schedules if any(event["upcoming"] for event in s["events"])]

    if not any(_is_open_for_new_applicants(s) for s in schedules):
        logger.info("새로 접수할 수 있는 회차가 없어 날짜를 고정하지 않습니다. | jmCd=%s", jm_cd)
        return _no_open_round_note(target["jmNm"], has_any_schedule=bool(schedules))

    return _format_schedules(target["jmNm"], schedules)


class TargetCertification(BaseModel):
    """대화에서 뽑은 목표 자격증."""

    name: str | None = Field(
        description="사용자가 취득하려는 자격증의 정확한 종목명. 정해지지 않았으면 null"
    )


_TARGET_PROMPT = """아래 대화에서 사용자가 이번에 취득하려고 하는 자격증 하나의 종목명을 고르세요.
- 여러 자격증이 나왔으면 사용자가 마지막에 목표로 정한 것을 고릅니다.
- AI가 옛 이름을 바로잡았다면(예: 정보처리기능사 → 프로그래밍기능사) 바로잡은 이름을 씁니다.
- 대화에 나온 이름만 씁니다. 대화에 없는 자격증을 짐작해서 넣지 않습니다.
- 목표 자격증이 정해지지 않았으면 null 로 둡니다."""


async def infer_jm_cd(history: Sequence[ChatMessage]) -> str | None:
    """자격증을 고르지 않고 대화만 한 세션에서 목표 자격증의 종목코드를 찾는다.

    이름을 뽑는 것만 모델에게 맡기고, 종목코드는 DB에서 찾는다. 모델에게 코드를 바로
    쓰게 하면 그럴듯한 코드를 지어낸다. 하나로 정해지지 않으면 None 을 돌려주고,
    호출한 쪽은 대화 내용만으로 로드맵을 만든다(틀린 자격증의 일정을 쓰는 것보다 낫다).

    대화에 목표 자격증이 아예 없으면 만들 근거가 없어 RoadmapTargetUnknownError 를 낸다.
    (DB에 없는 민간자격처럼 이름은 있는데 코드를 못 찾는 경우는 대화만으로 만든다.)
    """
    if not any(m.sender == Sender.USER for m in history):
        raise RoadmapTargetUnknownError()

    model = get_chat_model(temperature=0).with_structured_output(TargetCertification)
    async with llm_call_guard("roadmap-target"):
        target = await model.ainvoke(build_messages(_TARGET_PROMPT, history))

    name = (target.name or "").strip() if target else ""
    if not name:
        logger.info("대화에서 목표 자격증을 찾지 못했습니다.")
        raise RoadmapTargetUnknownError()

    # 챗봇 도구와 같은 규칙으로 찾는다(같은 이름의 과정평가형은 뺀다).
    matches = (await _resolve(name))["matches"]
    compact = name.replace(" ", "")
    exact = [m for m in matches if m["jmNm"].replace(" ", "") == compact]
    candidates = exact or matches
    if len(candidates) != 1:
        logger.info("목표 자격증 '%s'을(를) 하나로 정하지 못했습니다. | 후보 %d개", name, len(candidates))
        return None

    logger.info("대화에서 목표 자격증을 찾았습니다. | %s → %s", name, candidates[0]["jmCd"])
    return candidates[0]["jmCd"]


async def run_roadmap_chain(
    history: Sequence[ChatMessage],
    jm_cd: str | None,
    title: str | None = None,
    user: RoadmapUser | None = None,
) -> RoadmapDraft:
    """선택된 자격증과 대화 맥락으로부터 구조화된 로드맵 초안을 만든다.

    자격증을 고르지 않고 대화만 하다 로드맵을 만들면 jm_cd 가 없다. 그때는 대화에서 찾는다.
    """
    if not jm_cd:
        jm_cd = await infer_jm_cd(history)

    system_prompt = render_prompt(
        "roadmap_system",
        today=date.today().isoformat(),
        min_steps=str(settings.min_roadmap_steps),
        max_steps=str(settings.max_roadmap_steps),
    )

    instruction = _build_instruction(title)
    user_context = _format_user(user)
    if user_context:
        instruction = f"{user_context}\n\n{instruction}"
    exam_context = await _load_exam_context(jm_cd) if jm_cd else None
    if exam_context:
        instruction = f"{exam_context}\n\n{instruction}"
    else:
        logger.info("종목 정보를 찾지 못해 대화 맥락만으로 로드맵을 만듭니다. | jmCd=%s", jm_cd)

    messages = build_messages(system_prompt, history, instruction)

    # 로드맵은 일관성이 중요하므로 채팅보다 낮은 temperature를 쓴다.
    model = get_chat_model(temperature=0.2).with_structured_output(RoadmapDraft)

    async with llm_call_guard("roadmap"):
        draft = await model.ainvoke(messages)

    if draft is None or not draft.steps:
        logger.warning("LLM이 스텝 없는 로드맵을 반환했습니다.")
        raise LLMOutputError("AI가 로드맵 스텝을 생성하지 못했습니다.")

    return draft
