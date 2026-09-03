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

    # --- 자격증 DB ---
    # 자격증 목록·상세·시험일정은 배치가 채워두고, 이 서버는 읽기만 한다.
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_db: str = ""

    # 한 번에 모델에 넘길 자격증 후보 수. 많으면 프롬프트가 커지고 적으면 고를 폭이 없다.
    max_candidates: int = 12
    # 설명 텍스트는 항목당 수천 자까지 있어서 잘라 쓴다.
    max_field_chars: int = 400


settings = Settings()
