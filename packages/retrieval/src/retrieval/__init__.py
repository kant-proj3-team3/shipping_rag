"""retrieval 모듈 진입점 (common.entrypoints 시그니처).

RETRIEVAL_IMPL=real 이면 실제 구현(Qdrant 검색, 근거 그룹 평가기)을, 아니면 목업을 돌려준다.
"""

from __future__ import annotations

import os

from common.interfaces import Embedder, RetrievalEvaluator, Retriever
from common.types import IndexManifest

from .mock import MockRetrievalEvaluator, MockRetriever


def _use_real() -> bool:
    # 기본값은 목업이다. 실제 색인이 준비되기 전에도 api·cli 가 지금과 똑같이 동작한다.
    return os.environ.get("RETRIEVAL_IMPL", "mock").strip().lower() == "real"


def create_retriever(embedder: Embedder, index: IndexManifest) -> Retriever:
    if _use_real():
        # 목업만 쓸 때는 무거운 라이브러리(qdrant·torch)를 읽지 않도록 필요할 때 가져온다
        from .hybrid import HybridRetriever
        from .store import create_qdrant_client

        return HybridRetriever(embedder, index, create_qdrant_client())
    return MockRetriever(embedder, index)


def create_retrieval_evaluator(retriever: Retriever) -> RetrievalEvaluator:
    if _use_real():
        from .evaluator import GroupRetrievalEvaluator

        return GroupRetrievalEvaluator(retriever)
    return MockRetrievalEvaluator(retriever)

