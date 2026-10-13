"""로드맵 요청/응답 스키마.

대응 백엔드 API: POST /api/chat/sessions/{sessionId}/roadmaps

응답의 steps[]는 백엔드가 그대로 영속화한 뒤 id를 붙여 클라이언트에 내려준다.
따라서 AI 서버는 id를 만들지 않는다.
"""

from datetime import date
from typing import Any

from pydantic import AliasChoices, Field, model_validator

from app.schemas.base import CamelModel
from app.schemas.chat import ChatMessage
from app.schemas.recommend import OnboardingAnswer


class RoadmapUser(CamelModel):
    nickname: str | None = Field(default=None, description="호칭")
    onboarding: list[OnboardingAnswer] = Field(
        default_factory=list,
        description="온보딩 답변. 하루 학습 가능 시간 등은 스텝 분량을 정하는 근거가 된다.",
    )


class RoadmapCertificate(CamelModel):
    jm_cd: str = Field(min_length=1, description="로드맵을 만들 자격증 종목코드")
    name: str | None = Field(default=None, description="종목명")
    category: str | None = None
    description: str | None = None
    # 백엔드가 함께 보내 주지만 쓰지 않는다. 일정은 종목코드로 직접 조회해서
    # 회차 정리(빈자리 추가접수 제외 등)와 접수 가능 여부 판단을 한 곳에서 한다.
    exam_schedules: list[dict[str, Any]] = Field(default_factory=list)


class RoadmapRequest(CamelModel):
    """팀 명세서 형식: 자격증은 certificate 객체로, 대화는 messages 로 온다.

    초기 형식(맨 바깥 jmCd, history)도 계속 받는다.
    """

    session_id: int = Field(description="대화 세션 ID. 추적/로깅 용도로만 쓰인다.")
    today: date | None = Field(
        default=None, description="백엔드 기준 오늘 날짜. 지금은 서버 날짜를 쓰고 로그에만 남긴다."
    )
    user: RoadmapUser | None = Field(default=None, description="사용자 정보")
    certificate: RoadmapCertificate | None = Field(
        default=None, description="사용자가 고른 자격증. 이 자격증의 실제 시험일정을 근거로 만든다."
    )
    jm_cd: str | None = Field(default=None, description="(초기 형식) 자격증 종목코드")
    history: list[ChatMessage] = Field(
        default_factory=list,
        # 명세서는 messages, 초기 형식은 history. 이름을 잘못 받으면 오류 없이 대화가
        # 통째로 빠지므로 둘 다 받는다.
        validation_alias=AliasChoices("messages", "history"),
        description="로드맵 수립 근거가 되는 대화 목록. 오래된 메시지가 앞.",
    )
    title: str | None = Field(
        default=None,
        description="클라이언트가 지정한 로드맵 제목. 없으면 AI가 생성한다.",
    )

    @model_validator(mode="after")
    def _require_certificate(self) -> "RoadmapRequest":
        if not self.target_jm_cd:
            raise ValueError("certificate.jmCd 가 필요합니다.")
        return self

    @property
    def target_jm_cd(self) -> str | None:
        if self.certificate is not None:
            return self.certificate.jm_cd
        return (self.jm_cd or "").strip() or None


class RoadmapStep(CamelModel):
    title: str = Field(description="스텝 제목")
    description: str = Field(description="스텝 설명")
    order_no: int = Field(ge=1, description="1부터 시작하는 순서")
    target_date: date | None = Field(default=None, description="목표 일자. 추정 불가 시 null")


class RoadmapResponse(CamelModel):
    title: str = Field(description="로드맵 제목")
    steps: list[RoadmapStep] = Field(description="순서대로 정렬된 학습 스텝 목록")
