"""AI 서버 도메인 예외.

백엔드는 AI 서버 장애/타임아웃 시 클라이언트에 502/504를 내려준다. 그 판단을 백엔드가 쉽게
할 수 있도록, AI 서버도 같은 의미의 상태 코드를 그대로 사용한다.
"""


class AIServerError(Exception):
    """AI 서버 도메인 예외의 최상위 타입."""

    status_code: int = 500
    code: str = "AI_INTERNAL_ERROR"
    message: str = "AI 처리 중 오류가 발생했습니다."

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class LLMTimeoutError(AIServerError):
    """LLM 응답이 제한 시간을 초과한 경우."""

    status_code = 504
    code = "LLM_TIMEOUT"
    message = "AI 모델 응답이 지연되어 요청을 완료하지 못했습니다."


class LLMUpstreamError(AIServerError):
    """LLM 호출 자체가 실패한 경우(인증, 레이트리밋, 네트워크 등)."""

    status_code = 502
    code = "LLM_UPSTREAM_ERROR"
    message = "AI 모델 호출에 실패했습니다."


class LLMOutputError(AIServerError):
    """LLM이 기대한 형식에 맞지 않는 응답을 준 경우."""

    status_code = 502
    code = "LLM_OUTPUT_INVALID"
    message = "AI 모델이 형식에 맞지 않는 응답을 반환했습니다."


class ConfigurationError(AIServerError):
    """서버 설정이 잘못된 경우(API 키 누락 등)."""

    status_code = 500
    code = "CONFIGURATION_ERROR"
    message = "AI 서버 설정이 올바르지 않습니다."


class RoadmapTargetUnknownError(AIServerError):
    """자격증을 고르지 않았고 대화에서도 목표 자격증을 찾지 못한 경우.

    서버 오류가 아니라 사용자가 아직 목표를 정하지 않은 상황이다. 502로 내보내면 앱이
    "서버 오류"로 보여 주므로, 목표를 먼저 정하라고 안내할 수 있게 따로 구분한다.
    """

    status_code = 422
    code = "ROADMAP_TARGET_UNKNOWN"
    message = "로드맵을 만들 목표 자격증을 대화에서 찾지 못했습니다. 먼저 자격증을 정해 주세요."
