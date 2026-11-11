"""chunking 모듈 진입점 (common.entrypoints 시그니처).

CHUNKING_IMPL 환경변수로 구현을 고른다.
- 없거나 "mock": 목업 (기본값). PDF·Qdrant·모델 없이 돌아가서 CI 와 다른 모듈의 개발·테스트가 그대로 동작한다.
- "real": 실제 구현. pdfplumber 구조 청킹 → E5 임베딩 → Qdrant 색인, 평가 파일 기반 골든셋.

실제 구현은 무거운 라이브러리(sentence-transformers 등)를 쓰므로, 고를 때만 불러온다.
"""

from __future__ import annotations

import os

from common.interfaces import Embedder, GoldenDatasetProvider, Indexer

from .mock import MockEmbedder, MockGoldenProvider, MockIndexer


def _use_real() -> bool:
    return (os.environ.get("CHUNKING_IMPL") or "mock").strip().lower() == "real"


def create_embedder() -> Embedder:
    if _use_real():
        from .embedder import E5Embedder

        return E5Embedder()
    return MockEmbedder()


def create_indexer(embedder: Embedder) -> Indexer:
    if _use_real():
        from .indexer import PdfIndexer

        return PdfIndexer(embedder)
    return MockIndexer(embedder)


def create_golden_provider() -> GoldenDatasetProvider:
    if _use_real():
        from .golden import EvaluationGoldenProvider

        return EvaluationGoldenProvider()
    return MockGoldenProvider()
