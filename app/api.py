"""FastAPI 앱. `uvicorn app.api:create_app --factory` 로 실행한다 (import 만으로 모듈을 조립하지 않는다)."""

from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

import backend
from common.api import PATH_HEALTH
from common.types import HealthResponse

from .envfile import load_env_file
from .wiring import apply_impl_default, build_base, build_services, index_name, wait_for_manifest


def cors_origins() -> list[str]:
    """CORS_ALLOW_ORIGINS(쉼표 구분)에 적은 출처만 허용한다. 비어 있으면 CORS 를 켜지 않는다."""
    return [o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]


def create_app() -> FastAPI:
    load_env_file()  # 호스트 실행 시 .env 적용 (이미 설정된 환경변수는 덮어쓰지 않는다)
    apply_impl_default()  # 기본은 실제 구현. APP_IMPL=mock 이면 목업
    app = FastAPI(title="RAG Q&A API", version="0.1.0")
    origins = cors_origins()
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    base = build_base()
    manifest = wait_for_manifest(base.indexer, index_name())
    if manifest is None:
        # 인덱스가 아직 없다: 죽지 않고 /health 로 준비 안 됨을 알린다
        fallback = APIRouter()

        @fallback.get(PATH_HEALTH, response_model=HealthResponse)
        async def health() -> HealthResponse:
            return HealthResponse(index_ready=False, index_name=index_name())

        app.include_router(fallback)
        return app

    svc = build_services(base, manifest)
    app.include_router(backend.create_router(svc.qa, svc.session, manifest))
    return app
