"""가짜 임베더와 리랭커로 검색 순서, 결과 개수, 오류 처리를 검증한다."""

import asyncio
from datetime import UTC, datetime

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from common.errors import IndexNotReadyError, InvalidInputError, RetrievalError
from common.types import IndexManifest, RequestContext, RetrievalMode, RetrievalRequest
from retrieval.hybrid import HybridRetriever
from retrieval.reranker import CrossEncoderReranker

CTX = RequestContext(request_id="r1")  # 테스트 공통 요청 정보
COL = "t"  # 테스트용 컬렉션 이름


class FakeEmbedder:
    """실제 모델 대신 고정 벡터와 간단한 길이 검사를 제공하는 테스트용 임베더."""

    embedder_id = "fake"
    dimension = 2
    max_input_tokens = 5

    def count_tokens(self, t):
        """입력 문자열을 공백으로 나눠 테스트용 토큰 수를 반환한다."""
        return len(t.split())

    def embed_passages(self, ts):
        """각 문서에 대해 동일한 2차원 벡터를 반환한다."""
        return [[1.0, 0.0] for _ in ts]

    def embed_query(self, t):
        """질문 길이를 검사하고, 한도 이내이면 고정된 질문 벡터를 반환한다."""
        if len(t.split()) > self.max_input_tokens:
            raise InvalidInputError("too long")
        return [1.0, 0.0]


def manifest(max_chunk_tokens=8):
    """테스트용 인덱스 정보 객체를 생성한다. 청크 길이 한도는 인자로 바꿀 수 있다."""
    return IndexManifest(
        index_name=COL, embedder_id="fake", embedding_dim=2, document_count=1, chunk_count=3,
        fingerprint="fp", max_chunk_tokens=max_chunk_tokens, created_at=datetime.now(UTC),
    )


def payload(i, text):
    """벡터와 함께 저장할 청크의 ID, 문서 출처, 페이지, 본문을 구성한다."""
    return {"chunk_id": f"c{i}", "book_id": "B", "file_name": "B.pdf", "page_start": i, "page_end": i, "text": text}


@pytest.fixture
def client():
    """각 테스트에 사용할 메모리 Qdrant 저장소를 만들고 청크 3개를 저장한다."""
    # pytest가 client 인자를 받는 테스트에 이 함수의 반환값을 전달
    c = QdrantClient(":memory:")
    c.create_collection(COL, vectors_config=VectorParams(size=2, distance=Distance.COSINE))

    # 검색 방식에 따라 순위 차이가 생기도록 벡터와 본문 구성
    rows = {
        1: ([1.0, 0.0], "운임 안내 일반"),
        2: ([1.0, 1.0], "장비 안내 일반"),
        3: ([0.0, 1.0], "예약 번호 R-0021 확인"),
    }
    c.upsert(COL, points=[PointStruct(id=i, vector=v, payload=payload(i, t)) for i, (v, t) in rows.items()])
    return c


def fake_reranker(prefer: str, max_tokens=512):
    """지정한 문자열이 있는 청크에 높은 점수를 주는 테스트용 리랭커를 생성한다."""
    # 실제 모델 대신 전달한 채점 함수를 사용: 문자열이 있으면 1점, 없으면 0점
    return CrossEncoderReranker(
        max_tokens=max_tokens, scorer=lambda pairs: [1.0 if prefer in text else 0.0 for _, text in pairs]
    )


def req(mode, k=3):
    """질문을 'R-0021'로 고정하고 검색 방식과 반환 개수를 지정한 요청을 만든다."""
    return RetrievalRequest(query="R-0021", mode=mode, k=k)


def test_리랭킹은_점수_순으로_순서를_바꾼다(client):
    """리랭킹이 순서를 바꾸고, 결과 순위가 연속이며 중복 청크가 없는지 검증한다."""
    r = HybridRetriever(FakeEmbedder(), manifest(), client, reranker=fake_reranker("장비"))

    # 같은 질문으로 두 검색 방식을 실행
    hybrid = asyncio.run(r.retrieve(req(RetrievalMode.HYBRID), CTX))
    rerank = asyncio.run(r.retrieve(req(RetrievalMode.HYBRID_RERANK), CTX))

    assert hybrid.chunks[0].chunk.chunk_id == "c3"  # 하이브리드 검색 1위
    assert rerank.chunks[0].chunk.chunk_id == "c2"  # 리랭커가 선호하는 '장비' 청크
    assert [c.rank for c in rerank.chunks] == [1, 2, 3]
    assert len({c.chunk.chunk_id for c in rerank.chunks}) == len(rerank.chunks)


def test_k_이하로_자른다(client):
    """후보가 3개일 때 k=2로 요청하면 결과가 2개만 반환되는지 검증한다."""
    r = HybridRetriever(FakeEmbedder(), manifest(), client, reranker=fake_reranker("장비"))
    assert len(asyncio.run(r.retrieve(req(RetrievalMode.HYBRID_RERANK, k=2), CTX)).chunks) == 2


def test_청크_한도가_리랭커_한도보다_크면_IndexNotReadyError(client):
    """청크 길이 한도가 리랭커 한도를 넘으면 검색기 생성이 거부되는지 검증한다."""
    # 청크 한도 600 > 리랭커 기본 한도 512
    with pytest.raises(IndexNotReadyError):
        HybridRetriever(FakeEmbedder(), manifest(max_chunk_tokens=600), client, reranker=fake_reranker("x"))


def test_리랭커_오류는_RetrievalError로_감싼다(client):
    """리랭커 내부 실행 오류가 RetrievalError로 변환되는지 검증한다."""

    def boom(pairs):
        """모델 실행 실패를 재현하기 위해 호출될 때마다 오류를 발생시킨다."""
        raise RuntimeError("model failed")

    r = HybridRetriever(FakeEmbedder(), manifest(), client, reranker=CrossEncoderReranker(scorer=boom))

    # 지정한 오류가 발생해야 테스트 통과
    with pytest.raises(RetrievalError):
        asyncio.run(r.retrieve(req(RetrievalMode.HYBRID_RERANK), CTX))


def test_한도_초과_질문은_InvalidInputError_전파(client):
    """너무 긴 질문의 입력 오류가 다른 오류로 바뀌지 않고 전달되는지 검증한다."""
    r = HybridRetriever(FakeEmbedder(), manifest(), client, reranker=fake_reranker("장비"))

    # 가짜 임베더 한도는 5단어인데 질문은 7단어
    with pytest.raises(InvalidInputError):
        asyncio.run(r.retrieve(RetrievalRequest(query="a b c d e f g", mode=RetrievalMode.HYBRID_RERANK, k=3), CTX))


def test_빈_후보는_빈_결과():
    """리랭커에 빈 청크 목록을 전달하면 빈 점수 목록을 반환하는지 검증한다."""
    r = CrossEncoderReranker(scorer=lambda pairs: [])
    assert r.score("q", []) == []


def test_점수를_입력_순서대로_돌려준다():
    """점수가 입력 순서대로 반환되고, 반복 호출에서도 채점 함수가 재사용되는지 검증한다."""
    # 글자 수를 점수로 사용해 입력 순서와 반환값을 쉽게 비교
    r = CrossEncoderReranker(scorer=lambda pairs: [len(text) for _, text in pairs])
    assert r.score("q", ["가", "가나다", "가나"]) == [1.0, 3.0, 2.0]
    assert r.score("q", ["가나다라"]) == [4.0]