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
from app.core.config import settings
from app.core.exceptions import LLMOutputError
from app.core.llm import get_chat_model, llm_call_guard
from app.core.logging import get_logger
from app.prompts import render_prompt
from app.repositories.certifications import fetch_exam_schedules, get_certification
from app.schemas.chat import ChatMessage

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


def _build_instruction(title: str | None) -> str:
    instruction = "지금까지의 대화를 근거로 학습 로드맵을 작성하세요."
    if title:
        # 제목이 지정된 경우에도 모델에게 알려준다. 로드맵 내용의 방향을 잡는 힌트가 된다.
        instruction += f'\n로드맵 제목은 "{title}"로 고정합니다. 이 제목에 맞는 내용으로 구성하세요.'
    return instruction


def _format_schedules(jm_nm: str, schedules: list[dict]) -> str:
    """실제 시험일정을 프롬프트에 넣을 텍스트로 만든다."""
    lines = [f"[{jm_nm} 실제 시험일정]"]
    for schedule in schedules:
        lines.append(schedule["description"] or f"{schedule['implSeq']}회")
        for event in schedule["events"]:
            period = event["start"] if not event["end"] else f"{event['start']} ~ {event['end']}"
            mark = "예정" if event["upcoming"] else "종료"
            lines.append(f"  - [{mark}] {event['label']}: {period}")
    return "\n".join(lines)


async def _load_exam_context(jm_cd: str) -> str | None:
    """선택된 자격증의 실제 시험일정을 프롬프트용 텍스트로 만든다.

    이 정보가 없으면 모델이 "3개월 남았다" 같은 말만 보고 날짜를 지어낸다.
    로드맵의 핵심은 실제 시험일에서 역산하는 것이므로 근거를 함께 넘긴다.
    """
    target = await get_certification(jm_cd)
    if target is None:
        logger.warning("종목코드 %s 를 찾지 못했습니다.", jm_cd)
        return None

    schedules = await fetch_exam_schedules(jm_cd)
    if not schedules:
        return None

    return _format_schedules(target["jmNm"], schedules)


async def run_roadmap_chain(
    history: Sequence[ChatMessage],
    jm_cd: str,
    title: str | None = None,
) -> RoadmapDraft:
    """선택된 자격증과 대화 맥락으로부터 구조화된 로드맵 초안을 만든다."""
    system_prompt = render_prompt(
        "roadmap_system",
        today=date.today().isoformat(),
        min_steps=str(settings.min_roadmap_steps),
        max_steps=str(settings.max_roadmap_steps),
    )

    instruction = _build_instruction(title)
    exam_context = await _load_exam_context(jm_cd)
    if exam_context:
        instruction = f"{exam_context}\n\n{instruction}"
    else:
        logger.info("시험일정이 없어 대화 맥락만으로 로드맵을 만듭니다. | jmCd=%s", jm_cd)

    messages = build_messages(system_prompt, history, instruction)

    # 로드맵은 일관성이 중요하므로 채팅보다 낮은 temperature를 쓴다.
    model = get_chat_model(temperature=0.2).with_structured_output(RoadmapDraft)

    async with llm_call_guard("roadmap"):
        draft = await model.ainvoke(messages)

    if draft is None or not draft.steps:
        logger.warning("LLM이 스텝 없는 로드맵을 반환했습니다.")
        raise LLMOutputError("AI가 로드맵 스텝을 생성하지 못했습니다.")

    return draft
