"""Vercel 서버리스 진입점.

Vercel은 api/ 아래의 파이썬 파일을 함수로 만들고, 모듈에 노출된 ASGI 앱(app)을 찾아 실행한다.
FastAPI 앱 자체는 app/main.py 에 있고 여기서는 가져다 노출만 한다.

이 파일이 api/ 안에 있어서 파이썬의 검색 경로에 프로젝트 루트가 들어가지 않는다.
그대로 두면 `from app.main import ...` 이 ModuleNotFoundError 로 죽어 함수 전체가 실행되지 않는다.
그래서 루트를 직접 넣어준다.

로컬 실행은 이 파일과 무관하다. 평소처럼 아래를 쓴다.
    uvicorn app.main:app --reload
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

__all__ = ["app"]
