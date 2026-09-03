"""프롬프트 파일 로더.

상대 경로("app/prompts/...")로 읽으면 서버를 어느 디렉터리에서 실행하느냐에 따라 깨진다.
__file__ 기준 절대 경로로 읽고, 한 번 읽은 내용은 캐싱한다.
"""

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """app/prompts/{name}.txt 를 읽어 반환한다."""
    path = PROMPT_DIR / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"프롬프트 파일을 찾을 수 없습니다: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt(name: str, **variables: str) -> str:
    """프롬프트의 {변수} 자리표시자를 치환한다.

    str.format()은 프롬프트 본문에 있는 중괄호(JSON 예시 등)까지 해석해서 깨지므로
    단순 치환을 쓴다.
    """
    text = load_prompt(name)
    for key, value in variables.items():
        text = text.replace("{" + key + "}", value)
    return text
