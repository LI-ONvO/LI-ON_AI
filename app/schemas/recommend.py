"""자격증 추천 요청/응답 스키마.

메인 페이지처럼 대화 없이 사용자 프로필만으로 자격증을 추천할 때 쓴다.
"""

from pydantic import Field

from app.schemas.base import CamelModel


class OnboardingAnswer(CamelModel):
    key: str = Field(description="온보딩 항목 키. 예: study_time")
    title: str = Field(description="항목 제목. 예: 하루 학습 가능 시간")
    values: list[str] = Field(default_factory=list, description="사용자가 고른 값들")


class RecommendUser(CamelModel):
    nickname: str | None = Field(default=None, description="호칭에 사용")
    desired_fields: list[str] = Field(default_factory=list, description="희망 분야")
    onboarding: list[OnboardingAnswer] = Field(
        default_factory=list,
        description="온보딩 답변. study_time 은 취득 기간을 가늠하는 근거가 된다.",
    )


class RecommendRequest(CamelModel):
    user_id: int = Field(description="사용자 ID. 추적/로깅 용도로만 쓰인다.")
    size: int = Field(default=5, ge=1, le=20, description="추천받을 자격증 개수")
    user: RecommendUser = Field(description="추천 근거가 되는 사용자 정보")


class RecommendItem(CamelModel):
    jm_cd: str = Field(description="종목코드. 반드시 DB에 존재하는 값이다.")
    reason: str = Field(description="이 사용자에게 왜 맞는지에 대한 설명")


class RecommendResponse(CamelModel):
    items: list[RecommendItem] = Field(
        description="추천 목록. 적합한 자격증이 부족하면 size보다 적을 수 있다."
    )
