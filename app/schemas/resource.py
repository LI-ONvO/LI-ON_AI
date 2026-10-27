"""학습 자료 추천 요청/응답 스키마.

대응 팀 명세: POST /resources/recommendations

응답의 title/url/reason 은 명세 그대로이고, 나머지는 프론트 요청("줄 수 있는 정보는 다 달라")에
따라 덧붙였다. 자료 종류마다 API 가 주는 정보가 달라 종류별 객체(video/book/blog)에 담는다.
해당 종류가 아니면 null 이다.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import Field

from app.schemas.base import CamelModel


class ResourceType(str, Enum):
    VIDEO = "VIDEO"  # YouTube
    BOOK = "BOOK"    # 카카오(다음) 책 검색
    WEB = "WEB"      # NAVER 웹문서 검색
    BLOG = "BLOG"    # NAVER 블로그 검색


class ResourceCertificate(CamelModel):
    jm_cd: str = Field(min_length=1, description="종목코드")
    name: str | None = Field(default=None, description="종목명. 없으면 종목코드로 조회한다.")


class ResourceContext(CamelModel):
    session_id: int | None = None
    roadmap_steps: list[str] = Field(
        default_factory=list, description="로드맵 스텝 제목들. 실기 단계면 실기 자료를 찾는다."
    )


class ResourceRequest(CamelModel):
    user_id: int | None = Field(default=None, description="추적/로깅 용도로만 쓰인다.")
    size: int = Field(default=8, ge=1, le=40, description="돌려받을 자료 개수(모든 종류 합)")
    certificate: ResourceCertificate
    context: ResourceContext | None = None
    exclude_urls: list[str] = Field(default_factory=list, description="이미 보여준 자료. 다시 주지 않는다.")
    types: list[ResourceType] | None = Field(
        default=None, description="(명세 외, 선택) 받을 자료 종류. 없으면 네 종류 모두."
    )


class VideoInfo(CamelModel):
    video_id: str
    channel_id: str | None = None
    channel_title: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    tags: list[str] = Field(default_factory=list)
    embeddable: bool | None = Field(default=None, description="앱 안에서 재생(임베드)할 수 있는지")


class BookInfo(CamelModel):
    authors: list[str] = Field(default_factory=list)
    translators: list[str] = Field(default_factory=list)
    publisher: str | None = None
    isbn: str | None = None
    price: int | None = Field(default=None, description="정가(원)")
    sale_price: int | None = Field(default=None, description="판매가(원). 없으면 null")
    status: str | None = Field(default=None, description="판매 상태. 예: 정상판매")
    edition_year: int | None = Field(default=None, description="제목의 'OOOO 프로그래밍기능사'에서 읽은 판 연도")


class BlogInfo(CamelModel):
    blogger_name: str | None = None
    blogger_link: str | None = None


class ResourceItem(CamelModel):
    type: ResourceType
    title: str
    url: str
    reason: str = Field(description="API 가 준 정보로 만든 한 줄 설명(출처·날짜·조회수 등)")
    description: str | None = Field(
        default=None, description="API 가 준 소개/미리보기 문구를 그대로. 우리가 요약한 글이 아니다."
    )
    source: str = Field(description="출처 표기. 예: YouTube · 채널명, NAVER 블로그, 다음 책")
    thumbnail_url: str | None = None
    published_at: date | datetime | None = Field(default=None, description="업로드·출간·작성일")
    video: VideoInfo | None = None
    book: BookInfo | None = None
    blog: BlogInfo | None = None


class UnavailableReason(str, Enum):
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"  # 외부 API 호출 한도를 다 씀. 시간이 지나면 풀린다
    NOT_CONFIGURED = "NOT_CONFIGURED"  # AI 서버에 그 API 키가 없음
    ERROR = "ERROR"                    # 그 외 실패(외부 API 장애, 시간 초과 등)


class UnavailableSource(CamelModel):
    type: ResourceType
    reason: UnavailableReason


class ResourceResponse(CamelModel):
    items: list[ResourceItem] = Field(
        description="실제 접근 가능한 자료만. 조건에 맞는 자료가 부족하면 size 보다 적을 수 있다."
    )
    unavailable: list[UnavailableSource] = Field(
        default_factory=list,
        description=(
            "이번에 검색하지 못한 자료 종류와 이유. 비어 있으면 모두 정상. "
            "items 에 어떤 종류가 없을 때 '검색 결과가 없음'인지 '한도 초과'인지 구분하는 데 쓴다."
        ),
    )
