"""retrieval 모듈 진입점 (common.entrypoints 시그니처).

뼈대 단계: 실제 구현이 생기기 전까지 목업을 돌려준다. 구현이 들어오면 이 함수들만 교체한다.
"""

from __future__ import annotations

from common.interfaces import Embedder, RetrievalEvaluator, Retriever
from common.types import IndexManifest

from .mock import MockRetrievalEvaluator, MockRetriever


def create_retriever(embedder: Embedder, index: IndexManifest) -> Retriever:
    return MockRetriever(embedder, index)


def create_retrieval_evaluator(retriever: Retriever) -> RetrievalEvaluator:
    return MockRetrievalEvaluator(retriever)
