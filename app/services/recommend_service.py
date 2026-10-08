"""자격증 추천 유스케이스.

모델이 목록에 없는 종목코드를 만들어내거나 같은 자격증을 중복으로 고를 수 있다.
백엔드가 그대로 화면에 쓰는 데이터이므로 여기서 검증하고 정리해서 내보낸다.
"""

from app.chains.recommend_chain import run_recommend_chain
from app.core.exceptions import LLMOutputError
from app.core.logging import get_logger
from app.schemas.recommend import RecommendItem, RecommendRequest, RecommendResponse

logger = get_logger(__name__)

# 고등학생은 기능사만 바로 응시할 수 있다. 모델에게 이 안내를 쓰라고 해도 자주 빠뜨려서
# 등급을 보고 직접 붙인다.
_ELIGIBILITY_NOTES = {
    "산업기사": "※ 산업기사는 관련 학과 대학 졸업(예정)이나 실무 경력이 있어야 응시할 수 있어, 졸업 후 다음 단계로 준비하는 자격증입니다.",
    "기사": "※ 기사는 관련 학과 대학 졸업(예정)이나 실무 경력이 있어야 응시할 수 있어, 졸업 후 다음 단계로 준비하는 자격증입니다.",
}


def normalize_items(drafts, grades: dict[str, str], size: int) -> list[RecommendItem]:
    """존재하지 않는 종목코드, 중복, 관련도 "약함"을 걸러내고 size개까지만 남긴다.

    grades 는 종목코드 → 등급. 산업기사·기사에는 응시자격 안내를 덧붙인다.
    """
    items: list[RecommendItem] = []
    seen: set[str] = set()

    for draft in drafts:
        jm_cd = (draft.jm_cd or "").strip()
        reason = (draft.reason or "").strip()

        if jm_cd not in grades:
            logger.warning("목록에 없는 종목코드를 추천해 제외합니다. | jmCd=%s", jm_cd)
            continue
        if jm_cd in seen:
            logger.warning("중복 추천을 제외합니다. | jmCd=%s", jm_cd)
            continue
        if not reason:
            logger.warning("추천 이유가 비어 있어 제외합니다. | jmCd=%s", jm_cd)
            continue

        if draft.fit == "약함":
            logger.info("관련도가 약해 제외합니다. | jmCd=%s", jm_cd)
            continue

        note = _ELIGIBILITY_NOTES.get(grades[jm_cd])
        if note:
            reason = f"{reason} {note}"

        seen.add(jm_cd)
        items.append(RecommendItem(jm_cd=jm_cd, reason=reason))

        if len(items) >= size:
            break

    return items


async def recommend_certifications(payload: RecommendRequest) -> RecommendResponse:
    logger.info(
        "추천 생성 시작 | userId=%s size=%d desiredFields=%s",
        payload.user_id,
        payload.size,
        payload.user.desired_fields,
    )

    drafts, grades = await run_recommend_chain(payload.user, payload.size)
    items = normalize_items(drafts, grades, payload.size)

    if not items:
        raise LLMOutputError("추천할 수 있는 자격증을 찾지 못했습니다.")

    logger.info("추천 생성 완료 | userId=%s items=%d", payload.user_id, len(items))
    return RecommendResponse(items=items)
