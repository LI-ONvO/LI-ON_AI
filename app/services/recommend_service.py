"""자격증 추천 유스케이스.

모델이 목록에 없는 종목코드를 만들어내거나 같은 자격증을 중복으로 고를 수 있다.
백엔드가 그대로 화면에 쓰는 데이터이므로 여기서 검증하고 정리해서 내보낸다.
"""

from app.chains.recommend_chain import run_recommend_chain
from app.core.exceptions import LLMOutputError
from app.core.logging import get_logger
from app.schemas.recommend import RecommendItem, RecommendRequest, RecommendResponse

logger = get_logger(__name__)


def normalize_items(drafts, valid_jm_cds: set[str], size: int) -> list[RecommendItem]:
    """존재하지 않는 종목코드와 중복을 걸러내고 size개까지만 남긴다."""
    items: list[RecommendItem] = []
    seen: set[str] = set()

    for draft in drafts:
        jm_cd = (draft.jm_cd or "").strip()
        reason = (draft.reason or "").strip()

        if jm_cd not in valid_jm_cds:
            logger.warning("목록에 없는 종목코드를 추천해 제외합니다. | jmCd=%s", jm_cd)
            continue
        if jm_cd in seen:
            logger.warning("중복 추천을 제외합니다. | jmCd=%s", jm_cd)
            continue
        if not reason:
            logger.warning("추천 이유가 비어 있어 제외합니다. | jmCd=%s", jm_cd)
            continue

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

    drafts, valid_jm_cds = await run_recommend_chain(payload.user, payload.size)
    items = normalize_items(drafts, valid_jm_cds, payload.size)

    if not items:
        raise LLMOutputError("추천할 수 있는 자격증을 찾지 못했습니다.")

    logger.info("추천 생성 완료 | userId=%s items=%d", payload.user_id, len(items))
    return RecommendResponse(items=items)
