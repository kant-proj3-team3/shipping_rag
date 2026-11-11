"""backend 모듈 진입점 (common.entrypoints 시그니처).

`BACKEND_IMPL` 환경변수로 구현을 고른다(retrieval·chunking 의 `*_IMPL` 과 같은 방식).
- 없거나 "mock": 목업 (기본값). 키·DB 없이 돌아서 CI 와 다른 모듈의 개발이 그대로 동작한다.
- "real": 실제 QA 서비스(검색 → 문맥 → 모델 → 검증, Langfuse 기록)와 PostgreSQL+Redis 세션. 자세한 내용은 `factory.py`.

create_qa_service 와 create_session_service 는 인자로 서로를 받지 않으므로 같은 프로세스 안에서 세션 저장소를 공유한다
(목업은 메모리 저장소, 실제 구현은 PostgreSQL 원본 + Redis 캐시 하나). 답변 평가기(`create_answer_evaluator`)는 J 단계 전까지
`BACKEND_IMPL` 과 상관없이 목업이다.
"""

from __future__ import annotations

import os

from fastapi import APIRouter

from common.interfaces import AnswerEvaluator, Embedder, QAService, Retriever, SessionService
from common.types import IndexManifest

from .mock import InMemorySessionStore, MockAnswerEvaluator, MockQAService, MockSessionService
from .router import build_router

_STORE = InMemorySessionStore()


def _use_real() -> bool:
    # 기본값은 목업이다. 키·DB 가 없어도 api·cli 와 CI 가 지금과 똑같이 동작한다.
    return os.environ.get("BACKEND_IMPL", "mock").strip().lower() == "real"


def create_qa_service(retriever: Retriever) -> QAService:
    if _use_real():
        # 목업만 쓸 때는 모델·DB 라이브러리를 읽지 않도록 필요할 때 가져온다
        from .factory import create_real_qa_service

        return create_real_qa_service(retriever)
    return MockQAService(retriever, _STORE)


def create_session_service() -> SessionService:
    if _use_real():
        from .factory import create_real_session_service

        return create_real_session_service()
    return MockSessionService(_STORE)


def create_answer_evaluator(embedder: Embedder | None) -> AnswerEvaluator:
    return MockAnswerEvaluator(embedder)


def create_router(qa_service: QAService, session_service: SessionService, index: IndexManifest) -> APIRouter:
    return build_router(qa_service, session_service, index)
