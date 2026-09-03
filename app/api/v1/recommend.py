"""자격증 추천 엔드포인트.

대화 없이 사용자 프로필만으로 추천한다. 메인 페이지에서 자격증 카드를 띄울 때 쓴다.
"""

from fastapi import APIRouter, status

from app.schemas.recommend import RecommendRequest, RecommendResponse
from app.services.recommend_service import recommend_certifications

router = APIRouter()


@router.post(
    "",
    response_model=RecommendResponse,
    status_code=status.HTTP_200_OK,
    summary="사용자 프로필 기반 자격증 추천",
)
async def create_recommendations(payload: RecommendRequest) -> RecommendResponse:
    return await recommend_certifications(payload)
