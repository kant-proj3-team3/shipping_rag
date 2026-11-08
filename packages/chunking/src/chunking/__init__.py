"""chunking 모듈 진입점 (common.entrypoints 시그니처).

CHUNKING_IMPL 환경변수로 구현을 고른다.
- 없거나 "mock": 목업 (기본값). PDF·Qdrant·모델 없이 돌아가서 CI 와 다른 모듈의 개발·테스트가 그대로 동작한다.
- "real": 실제 구현. 지금은 골든셋만 실제 구현이 있고, 임베더·인덱서는 아직 목업이다.

실제 구현은 고를 때만 불러온다.
"""

from __future__ import annotations

import os

from common.interfaces import Embedder, GoldenDatasetProvider, Indexer

from .mock import MockEmbedder, MockGoldenProvider, MockIndexer


def _use_real() -> bool:
    return (os.environ.get("CHUNKING_IMPL") or "mock").strip().lower() == "real"


def create_embedder() -> Embedder:
    return MockEmbedder()


def create_indexer(embedder: Embedder) -> Indexer:
    return MockIndexer(embedder)


def create_golden_provider() -> GoldenDatasetProvider:
    if _use_real():
        from .golden import EvaluationGoldenProvider

        return EvaluationGoldenProvider()
    return MockGoldenProvider()
