"""학습 자료 추천 엔드포인트.

이 기능은 AI 를 쓰지 않는다. 검색 API 약관(카카오: 외부 LLM 전달 제한, NAVER: 가공 없이 노출) 때문에
코드 규칙으로 고른다. 자세한 기준은 app/repositories/resource_sources.py.
"""

from fastapi import APIRouter, status

from app.schemas.resource import ResourceRequest, ResourceResponse
from app.services.resource_service import recommend_resources

router = APIRouter()


@router.post(
    "/recommendations",
    response_model=ResourceResponse,
    status_code=status.HTTP_200_OK,
    summary="자격증 학습 자료(영상·책·웹·블로그) 추천",
)
async def create_resource_recommendations(payload: ResourceRequest) -> ResourceResponse:
    return await recommend_resources(payload)
