"""DenseRetriever 단위 테스트. Qdrant 는 메모리 모드로 돌리고, 임베더는 이 파일 안의 가짜를 쓴다(다른 모듈 import 금지)."""

import asyncio
from datetime import UTC, datetime

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from common.errors import IndexNotReadyError, InvalidInputError, RetrievalError
from common.types import IndexManifest, RequestContext, RetrievalMode, RetrievalRequest
from retrieval.dense import DenseRetriever

CTX = RequestContext(request_id="r1")
COLLECTION = "t"


class FakeEmbedder:
    embedder_id = "fake"
    dimension = 2
    max_input_tokens = 5

    def count_tokens(self, text):
        return len(text.split())

    def embed_passages(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        if len(text.split()) > self.max_input_tokens:
            raise InvalidInputError("too long")
        return [1.0, 0.0]


def _manifest(embedder_id="fake") -> IndexManifest:
    return IndexManifest(
        index_name=COLLECTION, embedder_id=embedder_id, embedding_dim=2, document_count=1, chunk_count=3,
        fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
    )


def _payload(i: int) -> dict:
    return {
        "chunk_id": f"c{i}", "book_id": "B1", "file_name": "B1.pdf", "page_start": i, "page_end": i, "text": f"본문 {i}",
    }


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    c.create_collection(COLLECTION, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    # 질의 벡터 [1, 0] 과 가까운 순서: c1 > c2 > c3
    vectors = {1: [1.0, 0.0], 2: [1.0, 1.0], 3: [0.0, 1.0]}
    c.upsert(COLLECTION, points=[PointStruct(id=i, vector=v, payload=_payload(i)) for i, v in vectors.items()])
    return c


def _req(query="질문", k=2, mode=RetrievalMode.NAIVE):
    return RetrievalRequest(query=query, mode=mode, k=k)


def test_embedder_id_불일치는_IndexNotReadyError(client):
    with pytest.raises(IndexNotReadyError):
        DenseRetriever(FakeEmbedder(), _manifest("other"), client)


def test_결과는_k_이하이고_rank는_1부터_연속(client):
    r = DenseRetriever(FakeEmbedder(), _manifest(), client)
    result = asyncio.run(r.retrieve(_req(k=2), CTX))
    assert [c.rank for c in result.chunks] == [1, 2]
    assert [c.chunk.chunk_id for c in result.chunks] == ["c1", "c2"]


def test_index는_주입받은_manifest_그대로(client):
    m = _manifest()
    assert DenseRetriever(FakeEmbedder(), m, client).index is m


def test_naive_외_방식은_RetrievalError(client):
    r = DenseRetriever(FakeEmbedder(), _manifest(), client)
    with pytest.raises(RetrievalError):
        asyncio.run(r.retrieve(_req(mode=RetrievalMode.HYBRID), CTX))


def test_질문이_한도를_넘으면_InvalidInputError가_그대로_전파(client):
    r = DenseRetriever(FakeEmbedder(), _manifest(), client)
    with pytest.raises(InvalidInputError):
        asyncio.run(r.retrieve(_req(query="a b c d e f g"), CTX))


def test_없는_컬렉션은_RetrievalError():
    r = DenseRetriever(FakeEmbedder(), _manifest(), QdrantClient(":memory:"))
    with pytest.raises(RetrievalError):
        asyncio.run(r.retrieve(_req(), CTX))


def test_빈_컬렉션은_빈_결과이고_예외가_아니다():
    c = QdrantClient(":memory:")
    c.create_collection(COLLECTION, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    result = asyncio.run(DenseRetriever(FakeEmbedder(), _manifest(), c).retrieve(_req(), CTX))
    assert result.chunks == []


def test_payload가_Chunk_스키마가_아니면_RetrievalError():
    c = QdrantClient(":memory:")
    c.create_collection(COLLECTION, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    c.upsert(COLLECTION, points=[PointStruct(id=1, vector=[1.0, 0.0], payload={"foo": "bar"})])
    with pytest.raises(RetrievalError):
        asyncio.run(DenseRetriever(FakeEmbedder(), _manifest(), c).retrieve(_req(), CTX))
