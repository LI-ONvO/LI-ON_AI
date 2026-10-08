"""애플리케이션 전역 설정.

.env 파일 또는 환경변수에서 값을 읽는다. 코드 어디에서도 os.environ을 직접 읽지 않고
이 모듈의 settings 객체만 사용한다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict # 자동으로 값을 가져옴


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # pydantic v2는 model_ 로 시작하는 필드명을 예약어로 취급해 경고를 낸다.
        # model_name 을 쓰기 위해 보호 네임스페이스를 해제한다.
        protected_namespaces=(),
    )

    app_name: str = "LI-ON AI Server"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # 백엔드가 X-API-Key 헤더에 담아 보내는 값. 비어 있으면 AI 기능 요청을 모두 거절한다.
    # (설정을 빠뜨렸을 때 조용히 무방비가 되지 않도록)
    api_key: str = ""

    # --- LLM ---
    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    temperature: float = 0.3
    request_timeout_seconds: float = 20.0
    max_retries: int = 2

    # --- 대화 맥락 ---
    # 히스토리가 길어지면 토큰 비용이 선형으로 증가한다. 최근 N개만 모델에 전달한다.
    max_history_messages: int = 30

    # --- 로드맵 ---
    min_roadmap_steps: int = 3
    max_roadmap_steps: int = 8

    # --- 자격증 조회 (백엔드 API) ---
    # 자격증 DB 는 백엔드 서버 안쪽에 있어 직접 읽지 않고 백엔드 API 로 조회한다.
    # (DB 를 채우는 배치는 batch/ 에서 MySQL 에 직접 쓴다. 이 설정과 무관하다.)
    backend_api_base_url: str = ""
    backend_api_key: str = ""
    # 챗봇 한 번에 최대 4번 부르므로 길게 잡으면 전체 응답이 늘어진다.
    backend_timeout_seconds: float = 10.0

    # 한 번에 모델에 넘길 자격증 후보 수. 많으면 프롬프트가 커지고 적으면 고를 폭이 없다.
    max_candidates: int = 12
    # 설명 텍스트는 항목당 수천 자까지 있어서 잘라 쓴다.
    max_field_chars: int = 400


settings = Settings()
