"""Vercel 서버리스 진입점.

Vercel은 api/ 아래의 파이썬 파일을 함수로 만들고, 모듈에 노출된 ASGI 앱(app)을 찾아 실행한다.
FastAPI 앱 자체는 app/main.py 에 있고 여기서는 가져다 노출만 한다.

로컬 실행은 이 파일과 무관하다. 평소처럼 아래를 쓴다.
    uvicorn app.main:app --reload
"""

from app.main import app

__all__ = ["app"]
