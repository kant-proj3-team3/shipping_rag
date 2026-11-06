"""backend 모듈 진입점 (common.entrypoints 시그니처).

뼈대 단계: QA·세션·평가는 목업을 돌려준다. 구현이 들어오면 이 함수들만 교체한다.
create_qa_service 와 create_session_service 는 인자로 서로를 받지 않으므로 같은 프로세스 안에서
세션 저장소를 공유한다 (실제 구현은 둘 다 Redis 를 본다).
"""

from __future__ import annotations

from fastapi import APIRouter

from common.interfaces import AnswerEvaluator, Embedder, QAService, Retriever, SessionService
from common.types import IndexManifest

from .mock import InMemorySessionStore, MockAnswerEvaluator, MockQAService, MockSessionService
from .router import build_router

_STORE = InMemorySessionStore()


def create_qa_service(retriever: Retriever) -> QAService:
    return MockQAService(retriever, _STORE)


def create_session_service() -> SessionService:
    return MockSessionService(_STORE)


def create_answer_evaluator(embedder: Embedder | None) -> AnswerEvaluator:
    return MockAnswerEvaluator(embedder)


def create_router(qa_service: QAService, session_service: SessionService, index: IndexManifest) -> APIRouter:
    return build_router(qa_service, session_service, index)
