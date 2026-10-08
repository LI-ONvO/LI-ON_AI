"""AI 기능 라우터 집약.

경로는 팀 API 명세를 따른다: /chat, /roadmaps, /recommendations.

엔드포인트가 늘어날 때 main.py를 건드리지 않도록 여기서만 등록한다.
"""

from fastapi import APIRouter

from app.api.v1 import chat, recommend, roadmap

api_router = APIRouter()
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(roadmap.router, prefix="/roadmaps", tags=["roadmap"])
api_router.include_router(recommend.router, prefix="/recommendations", tags=["recommend"])
