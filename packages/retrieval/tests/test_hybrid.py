"""HybridRetriever 단위 테스트. Qdrant 는 메모리 모드로 돌리고, 임베더는 이 파일 안의 가짜를 쓴다(다른 모듈 import 금지)."""

import asyncio
from datetime import UTC, datetime

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from common.errors import IndexNotReadyError, InvalidInputError, RetrievalError
from common.types import Chunk, IndexManifest, RequestContext, RetrievalMode, RetrievalRequest
from retrieval.hybrid import Bm25Index, HybridRetriever, rrf_fuse, tokenize

CTX = RequestContext(request_id="r1")
COL = "t"


class FakeEmbedder:
    embedder_id = "fake"
    dimension = 2
    max_input_tokens = 5

    def count_tokens(self, t):
        return len(t.split())

    def embed_passages(self, ts):
        return [[1.0, 0.0] for _ in ts]

    def embed_query(self, t):
        if len(t.split()) > self.max_input_tokens:
            raise InvalidInputError("too long")
        return [1.0, 0.0]


def manifest(eid="fake"):
    return IndexManifest(
        index_name=COL, embedder_id=eid, embedding_dim=2, document_count=1, chunk_count=3,
        fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
    )


def payload(i, text):
    return {"chunk_id": f"c{i}", "book_id": "B", "file_name": "B.pdf", "page_start": i, "page_end": i, "text": text}


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    c.create_collection(COL, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    # 질의 벡터 [1,0] 기준 Dense 순위: c1 > c2 > c3. 하지만 예약번호 R-0021 은 c3 에만 있다.
    rows = {
        1: ([1.0, 0.0], "운임 안내 일반"),
        2: ([1.0, 1.0], "장비 안내 일반"),
        3: ([0.0, 1.0], "예약 번호 R-0021 확인"),
    }
    c.upsert(COL, points=[PointStruct(id=i, vector=v, payload=payload(i, t)) for i, (v, t) in rows.items()])
    return c


def req(q="R-0021", k=3, mode=RetrievalMode.HYBRID):
    return RetrievalRequest(query=q, mode=mode, k=k)


def test_tokenize_식별자_유지():
    assert tokenize("예약 R-0021 확인") == ["예약", "r-0021", "확인"]


def test_rrf_두_순위에_모두_있는_항목이_앞선다():
    fused = rrf_fuse([["a", "b"], ["b", "c"]])
    assert [cid for cid, _ in fused] == ["b", "a", "c"]


def test_bm25_겹침_없으면_빈_결과():
    idx = Bm25Index([Chunk(chunk_id="x", book_id="B", file_name="B.pdf", page_start=1, page_end=1, text="가나다")])
    assert idx.search("라마바", 5) == []
    assert Bm25Index([]).search("아무거나", 5) == []  # 청크가 없는 인덱스도 빈 결과(정상)


def test_hybrid는_키워드가_맞는_청크를_Dense보다_위로_올린다(client):
    r = HybridRetriever(FakeEmbedder(), manifest(), client)
    dense = asyncio.run(r.retrieve(req(mode=RetrievalMode.NAIVE), CTX))
    hybrid = asyncio.run(r.retrieve(req(), CTX))
    assert dense.chunks[-1].chunk.chunk_id == "c3"  # Dense 만으로는 꼴찌
    assert hybrid.chunks[0].chunk.chunk_id == "c3"  # 하이브리드는 1등
    assert [c.rank for c in hybrid.chunks] == [1, 2, 3]
    assert len({c.chunk.chunk_id for c in hybrid.chunks}) == len(hybrid.chunks)


def test_k_이하로_자른다(client):
    r = HybridRetriever(FakeEmbedder(), manifest(), client)
    assert len(asyncio.run(r.retrieve(req(k=2), CTX)).chunks) == 2


def test_리랭킹은_아직_미지원(client):
    r = HybridRetriever(FakeEmbedder(), manifest(), client)
    with pytest.raises(RetrievalError):
        asyncio.run(r.retrieve(req(mode=RetrievalMode.HYBRID_RERANK), CTX))


def test_한도_초과는_InvalidInputError_전파(client):
    r = HybridRetriever(FakeEmbedder(), manifest(), client)
    with pytest.raises(InvalidInputError):
        asyncio.run(r.retrieve(req(q="a b c d e f g"), CTX))


def test_임베더_불일치와_없는_컬렉션은_IndexNotReadyError(client):
    with pytest.raises(IndexNotReadyError):
        HybridRetriever(FakeEmbedder(), manifest("other"), client)
    with pytest.raises(IndexNotReadyError):
        HybridRetriever(FakeEmbedder(), manifest(), QdrantClient(":memory:"))
