"""로드맵 엔드포인트.

백엔드가 POST /api/chat/sessions/{sessionId}/roadmaps 를 처리하는 도중 프록시로 호출한다.
응답의 steps[]에는 id가 없다. id는 백엔드가 영속화하면서 부여한다.
"""

from fastapi import APIRouter, status

from app.schemas.roadmap import RoadmapRequest, RoadmapResponse
from app.services.roadmap_service import generate_roadmap

router = APIRouter()


@router.post(
    "",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
    summary="대화 맥락 기반 구조화 로드맵 생성",
)
async def create_roadmap(payload: RoadmapRequest) -> RoadmapResponse:
    return await generate_roadmap(payload)
