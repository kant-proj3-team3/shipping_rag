"""chunking 모듈 진입점 (common.entrypoints 시그니처).

뼈대 단계: 실제 구현이 생기기 전까지 목업을 돌려준다. 구현이 들어오면 이 함수들만 교체한다.
"""

from __future__ import annotations

from common.interfaces import Embedder, GoldenDatasetProvider, Indexer

from .mock import MockEmbedder, MockGoldenProvider, MockIndexer


def create_embedder() -> Embedder:
    return MockEmbedder()


def create_indexer(embedder: Embedder) -> Indexer:
    return MockIndexer(embedder)


def create_golden_provider() -> GoldenDatasetProvider:
    return MockGoldenProvider()
