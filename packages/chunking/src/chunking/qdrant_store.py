"""Qdrant 저장소: 청크 컬렉션과 인덱스 신원(IndexManifest)을 보관한다.

- 청크 컬렉션 이름 = index_name. 벡터는 이름 없는 기본 벡터, 거리는 코사인 (검색 모듈과 맞춘 전제).
- payload 는 Chunk.model_dump(mode="json") 그대로다. 검색 모듈은 Chunk.model_validate 로 읽는다.
- manifest 는 별도 컬렉션 "<index_name>__manifest" 의 점 하나에 저장한다.
  청크 컬렉션에 섞으면 검색 모듈이 모든 점을 Chunk 로 읽을 때(BM25 용 scroll) 깨지기 때문이다.
  api·cli 처럼 다른 프로세스도 get_manifest 로 같은 값을 읽을 수 있다.
- 연결: QDRANT_PATH(서버 없이 단독 개발, 한 번에 한 프로세스)가 있으면 그것을, 없으면 QDRANT_URL.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from common.types import Chunk, IndexManifest

MANIFEST_SUFFIX = "__manifest"
_MANIFEST_POINT_ID = 1
_UPSERT_BATCH = 256


def create_qdrant_client() -> QdrantClient:
    path = os.environ.get("QDRANT_PATH")
    if path:
        return QdrantClient(path=path)
    return QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))


def point_id(chunk_id: str) -> str:
    # Qdrant 의 점 id 는 정수나 UUID 만 된다. chunk_id 로부터 항상 같은 UUID 를 만든다 (재색인해도 같은 id)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class QdrantIndexStore:
    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    @staticmethod
    def manifest_collection(index_name: str) -> str:
        return index_name + MANIFEST_SUFFIX

    def exists(self, index_name: str) -> bool:
        return self._client.collection_exists(index_name) or self._client.collection_exists(
            self.manifest_collection(index_name)
        )

    def delete(self, index_name: str) -> None:
        for name in (self.manifest_collection(index_name), index_name):  # manifest 를 먼저 지운다
            if self._client.collection_exists(name):
                self._client.delete_collection(name)

    def write_chunks(self, index_name: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]], dimension: int) -> None:
        self._client.create_collection(
            collection_name=index_name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        for start in range(0, len(chunks), _UPSERT_BATCH):
            batch = zip(chunks[start : start + _UPSERT_BATCH], vectors[start : start + _UPSERT_BATCH], strict=True)
            self._client.upsert(
                collection_name=index_name,
                points=[
                    PointStruct(id=point_id(c.chunk_id), vector=list(v), payload=c.model_dump(mode="json"))
                    for c, v in batch
                ],
            )

    def save_manifest(self, manifest: IndexManifest) -> None:
        name = self.manifest_collection(manifest.index_name)
        if not self._client.collection_exists(name):
            # 점 하나만 담는 보관용 컬렉션. 벡터는 형식상 필요해서 1차원 고정값을 넣는다
            self._client.create_collection(collection_name=name, vectors_config=VectorParams(size=1, distance=Distance.EUCLID))
        self._client.upsert(
            collection_name=name,
            points=[PointStruct(id=_MANIFEST_POINT_ID, vector=[0.0], payload={"manifest": manifest.model_dump(mode="json")})],
        )

    def load_manifest(self, index_name: str) -> IndexManifest | None:
        name = self.manifest_collection(index_name)
        if not (self._client.collection_exists(name) and self._client.collection_exists(index_name)):
            return None
        points = self._client.retrieve(collection_name=name, ids=[_MANIFEST_POINT_ID], with_payload=True)
        if not points:
            return None
        return IndexManifest.model_validate(points[0].payload["manifest"])
