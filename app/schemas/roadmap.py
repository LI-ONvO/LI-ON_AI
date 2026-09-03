"""로드맵 요청/응답 스키마.

대응 백엔드 API: POST /api/chat/sessions/{sessionId}/roadmaps

응답의 steps[]는 백엔드가 그대로 영속화한 뒤 id를 붙여 클라이언트에 내려준다.
따라서 AI 서버는 id를 만들지 않는다.
"""

from datetime import date

from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.chat import ChatMessage


class RoadmapRequest(CamelModel):
    session_id: int = Field(description="대화 세션 ID. 추적/로깅 용도로만 쓰인다.")
    jm_cd: str = Field(
        min_length=1,
        description=(
            "로드맵을 만들 자격증 종목코드. 사용자가 자격증을 하나 고른 뒤 대화를 시작하므로 "
            "항상 정해져 있다. 이 자격증의 실제 시험일정을 근거로 로드맵을 만든다."
        ),
    )
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="로드맵 수립 근거가 되는 대화 목록. 오래된 메시지가 앞.",
    )
    title: str | None = Field(
        default=None,
        description="클라이언트가 지정한 로드맵 제목. 없으면 AI가 생성한다.",
    )


class RoadmapStep(CamelModel):
    title: str = Field(description="스텝 제목")
    description: str = Field(description="스텝 설명")
    order_no: int = Field(ge=1, description="1부터 시작하는 순서")
    target_date: date | None = Field(default=None, description="목표 일자. 추정 불가 시 null")


class RoadmapResponse(CamelModel):
    title: str = Field(description="로드맵 제목")
    steps: list[RoadmapStep] = Field(description="순서대로 정렬된 학습 스텝 목록")
