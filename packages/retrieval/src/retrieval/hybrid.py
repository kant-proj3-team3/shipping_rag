"""Hybrid 검색: Dense(의미)와 BM25(키워드)의 검색 순위를 RRF로 결합한다."""

from __future__ import annotations

import asyncio
import heapq
import re
import time
from collections.abc import Sequence

from common.errors import ContractError, IndexNotReadyError, RetrievalError
from common.interfaces import Embedder
from common.types import (
    Chunk,
    IndexManifest,
    RequestContext,
    RetrievalMode,
    RetrievalRequest,
    RetrievalResult,
    RetrievedChunk,
)
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

from .dense import DenseRetriever, _to_chunk


# 검색 설정값
RRF_CONSTANT = 60  # RRF 순위 점수 계산에 사용하는 상수
CANDIDATE_POOL = 50  # Dense와 BM25에서 각각 가져올 최대 후보 수


def tokenize(text: str) -> list[str]:
    """텍스트를 소문자로 변환하고 단어 단위로 분리한다."""
    # 하이픈이 포함된 식별자(R-0021 등)는 하나의 단어로 유지
    return re.findall(r"\w+(?:-\w+)*", text.lower())


def load_chunks(client: QdrantClient, collection: str) -> list[Chunk]:
    """Qdrant 컬렉션에서 전체 청크를 읽어온다."""
    chunks: list[Chunk] = []
    offset = None
    while True:
        # 한 번에 최대 1000개씩 청크 조회
        points, offset = client.scroll(
            collection_name=collection,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        # 조회한 데이터를 Chunk 객체로 변환
        chunks.extend(_to_chunk(p.payload) for p in points)

        if offset is None:
            return chunks  # 모든 청크 조회 완료


def rrf_fuse(
        rankings: Sequence[Sequence[str]],
        constant: int = RRF_CONSTANT,
) -> list[tuple[str, float]]:
    """여러 검색 순위를 RRF 점수로 합쳐 정렬한다."""
    scores: dict[str, float] = {}

    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            # RRF 점수 =1 / (상수 + 순위), 여러 검색 결과의 점수를 합산
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (constant + rank)
    # 점수가 높은 순서로 정렬하고, 동점이면 chunk_id 기준 정렬 
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))



class Bm25Index:
    """청크의 키워드를 기반으로 검색하는 BM25 인덱스"""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self._chunks = list(chunks)


        # 청크가 있으면 BM25 인덱스를 생성 (청크가 없으면 만들 수 없으므로 None)
        self._bm25 = (
            BM25Okapi([tokenize(c.text) for c in self._chunks])
            if self._chunks
            else None
        )


    def search(self, query: str, n: int) -> list[str]:
        """질문과 키워드가 관련 있는 상위 n개 청크 ID를 반환한다."""

        # 청크가 없는 인덱스는 빈 결과(정상)
        if self._bm25 is None:
            return []

        # 질문과 각 청크의 BM25 관련성 점수 계산
        scores = self._bm25.get_scores(tokenize(query))
        # 점수가 높은 상위 n개 후보 선택
        top = heapq.nlargest(n, range(len(scores)), key=scores.__getitem__)

        return [self._chunks[i].chunk_id for i in top if scores[i] > 0]



class HybridRetriever:
    """Naive(Dense)와 Hybrid(Dense + BM25) 검색을 처리한다."""

    def __init__(
            self,
            embedder: Embedder,
            index: IndexManifest,
            client: QdrantClient,
    ) -> None:
        # Dense 검색기 초기화 및 임베딩 모델 검증
        self._dense = DenseRetriever(embedder, index, client)


        # IndexNotReadyError는 그대로, 나머지(payload 형식 오류 포함)는 모두 IndexNotReadyError로 바꾼다.
        try:

            self._chunks = load_chunks(client, index.index_name)

        except IndexNotReadyError:
            raise

        except Exception as exc:
            # 컬렉션 없음·연결 실패·payload 형식 불일치 모두 시작 시점에는 "인덱스 준비가 안됨"이다.
            # (질의 중 같은 실패는 dense.py에서 RetrievalError로 남긴다)
            raise IndexNotReadyError(f"청크를 읽지 못했다: {exc}") from exc
        

        self._by_id = {c.chunk_id: c for c in self._chunks}

        self._bm25 = Bm25Index(self._chunks)


    @property
    def index(self) -> IndexManifest:
        """현재 검색에 사용하는 인덱스 정보를 반환한다."""
        return self._dense.index

    @property
    def supported_modes(self) -> Sequence[RetrievalMode]:
        """지원하는 검색 방식 목록을 반환한다."""
        return [RetrievalMode.NAIVE, RetrievalMode.HYBRID]

    async def retrieve(
            self,
            request: RetrievalRequest,
            ctx: RequestContext,
    ) -> RetrievalResult:
        """요청한 검색 방식으로 관련 청크를 조회한다."""

        # 지원하지 않는 검색 방식인지 확인
        if request.mode not in self.supported_modes:
            raise RetrievalError(f"지원하지 않는 검색 방식: {request.mode}")

        # Naive 검색은 DenseRetriever에 위임
        if request.mode is RetrievalMode.NAIVE:
            return await self._dense.retrieve(request, ctx)

        # Hybrid 검색 시작 시간 기록
        started = time.perf_counter()

        # RRF 결합에 사용할 Dense 후보 요청 생성
        pool = RetrievalRequest(
            query=request.query,
            mode=RetrievalMode.NAIVE,
            k=CANDIDATE_POOL,
        )

        try:

            dense_result, bm25_ids = await asyncio.gather(
                self._dense.retrieve(pool, ctx),
                asyncio.to_thread(
                    self._bm25.search,
                    request.query,
                    CANDIDATE_POOL,
                ),
            )


        except ContractError:
            raise # 입력 값 검증 오류는 그대로 전달

        except Exception as exc:
            raise RetrievalError(f"하이브리드 검색 실패: {exc}") from exc

        # Dense 검색 결과에서 청크 ID 추출
        dense_ids = [rc.chunk.chunk_id for rc in dense_result.chunks]

        by_id = {
            **self._by_id,
            **{rc.chunk.chunk_id: rc.chunk for rc in dense_result.chunks},
        }

        # Dense와 BM25 순위를 RRF로 결합하고 상위 k개 선택
        fused = rrf_fuse([dense_ids, bm25_ids])[: request.k]


        return RetrievalResult(
            mode=request.mode,
            k=request.k,
            chunks=[
                RetrievedChunk(rank=i, score=s, chunk=by_id[cid])
                for i, (cid, s) in enumerate(fused, start=1)
            ],
            latency_ms=(time.perf_counter() - started) * 1000,
        )