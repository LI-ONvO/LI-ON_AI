"""로드맵 유스케이스.

LLM 출력은 스키마는 맞아도 값이 어긋날 수 있다(순서 건너뜀, 과거 날짜, 앞뒤가 뒤집힌 날짜 등).
백엔드가 그대로 DB에 넣는 데이터이므로 여기서 정규화해서 내보낸다.
"""

from datetime import date

from app.chains.roadmap_chain import RoadmapDraft, RoadmapStepDraft, run_roadmap_chain
from app.core.exceptions import LLMOutputError
from app.core.logging import get_logger
from app.schemas.roadmap import RoadmapRequest, RoadmapResponse, RoadmapStep

logger = get_logger(__name__)

_FALLBACK_TITLE = "학습 로드맵"


def _resolve_title(requested: str | None, draft: RoadmapDraft) -> str:
    """클라이언트가 제목을 지정했으면 그것이 우선, 아니면 AI가 만든 제목을 쓴다."""
    for candidate in (requested, draft.title):
        if candidate and candidate.strip():
            return candidate.strip()
    return _FALLBACK_TITLE


def _normalize_target_date(
    raw: date | None,
    previous: date | None,
    today: date,
    step_index: int,
) -> date | None:
    """목표 일자를 검증한다. 과거이거나 앞 스텝보다 이른 날짜는 버린다."""
    if raw is None:
        return None

    if raw < today:
        logger.warning("스텝 %d의 목표 일자가 과거(%s)라 제거합니다.", step_index, raw)
        return None

    if previous is not None and raw < previous:
        logger.warning(
            "스텝 %d의 목표 일자(%s)가 앞 스텝(%s)보다 이르러 제거합니다.",
            step_index,
            raw,
            previous,
        )
        return None

    return raw


def _to_step(draft_step: RoadmapStepDraft, order_no: int, target_date: date | None) -> RoadmapStep:
    return RoadmapStep(
        title=draft_step.title.strip(),
        description=draft_step.description.strip(),
        order_no=order_no,
        target_date=target_date,
    )


def normalize_steps(draft: RoadmapDraft, today: date | None = None) -> list[RoadmapStep]:
    """스텝을 순서대로 정렬하고 order_no를 1..N으로 다시 매긴다."""
    today = today or date.today()

    # LLM이 준 order_no는 참고만 하고, 실제 번호는 여기서 다시 부여한다.
    # 그래야 번호가 비거나 중복돼도 백엔드가 받는 데이터는 항상 1..N이 된다.
    ordered = sorted(draft.steps, key=lambda step: step.order_no)

    steps: list[RoadmapStep] = []
    previous_date: date | None = None

    for index, draft_step in enumerate(ordered, start=1):
        if not draft_step.title.strip():
            logger.warning("제목이 빈 스텝을 건너뜁니다. (원본 order_no=%s)", draft_step.order_no)
            continue

        target_date = _normalize_target_date(draft_step.target_date, previous_date, today, index)
        if target_date is not None:
            previous_date = target_date

        steps.append(_to_step(draft_step, len(steps) + 1, target_date))

    return steps


async def generate_roadmap(payload: RoadmapRequest) -> RoadmapResponse:
    logger.info(
        "로드맵 생성 시작 | sessionId=%s jmCd=%s historyLen=%d titleGiven=%s",
        payload.session_id,
        payload.jm_cd,
        len(payload.history),
        payload.title is not None,
    )

    draft = await run_roadmap_chain(payload.history, payload.jm_cd, payload.title)
    steps = normalize_steps(draft)

    if not steps:
        raise LLMOutputError("생성된 로드맵에 유효한 스텝이 없습니다.")

    response = RoadmapResponse(title=_resolve_title(payload.title, draft), steps=steps)
    logger.info(
        "로드맵 생성 완료 | sessionId=%s title=%s steps=%d",
        payload.session_id,
        response.title,
        len(response.steps),
    )
    return response
