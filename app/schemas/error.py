"""오류 응답 스키마.

성공/실패 응답 형태를 통일해 두면 백엔드가 AI 서버 오류를 분기하기 쉬워진다.
"""

from typing import Any

from pydantic import Field

from app.schemas.base import CamelModel


class ErrorResponse(CamelModel):
    code: str = Field(description="오류 식별 코드 (예: LLM_TIMEOUT)")
    message: str = Field(description="사람이 읽을 수 있는 오류 설명")
    detail: Any = Field(default=None, description="추가 정보. 유효성 오류 목록 등")
