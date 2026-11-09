"""Naive(Dense) 검색: 질문을 임베딩해 Qdrant에서 top-k 청크를 가져온다."""

from __future__ import annotations

# 표준 라이브러리: 스레드 실행(asyncio), 소요 시간 측정(time), 타입 힌트(Sequence)
import asyncio
import time
from collections.abc import Sequence

# 계약(common): 이 모듈은 common 과 외부 라이브러리만 import 한다
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
# 외부 라이브러리: Qdrant 벡터DB 클라이언트
from qdrant_client import QdrantClient


class DenseRetriever:
    """Naive(Dense) 검색기. 질문 벡터와 가장 가까운 청크를 Qdrant 에서 k개 가져온다."""

    def __init__(
        self,
        embedder: Embedder,
        index: IndexManifest,
        client: QdrantClient,
    ) -> None:
        # 인덱싱과 질의는 같은 임베더를 써야 점수 기준이 같다. 다르면 시작 단계에서 막는다.
        if embedder.embedder_id != index.embedder_id:
            raise IndexNotReadyError(
                f"임베더({embedder.embedder_id})와 인덱스({index.embedder_id})가 다르다"
            )
        # 협력 객체를 보관한다: 임베더(질문→벡터), 인덱스 신원, Qdrant 클라이언트
        self._embedder = embedder
        self._index = index
        self._client = client

    @property
    def index(self) -> IndexManifest:
        # 주입받은 manifest 를 그대로 노출한다. 평가기·백엔드가 인덱스 신원을 읽는 경로다.
        return self._index

    @property
    def supported_modes(self) -> Sequence[RetrievalMode]:
        # 2단계에서는 Naive만 지원한다. 하이브리드, 리랭킹은 이후 단계에서 추가한다.
        return [RetrievalMode.NAIVE]

    async def retrieve(self, request: RetrievalRequest, ctx: RequestContext) -> RetrievalResult:
        """검색 진입점. 검색 → Chunk 복원 → RetrievalResult 조립 순서로 진행한다."""
        started = time.perf_counter()  # latency_ms 계산용 시작 시각
        if request.mode not in self.supported_modes:
            raise RetrievalError(f"지원하지 않는 검색 방식: {request.mode}")

        try:
            # 임베딩, Qdrant 호출은 동기 함수라 별도 스레드에서 돌려 이벤트 루프를 막지 않는다.
            points = await asyncio.to_thread(self._search, request.query, request.k)
        except ContractError:
            # InvalidInputError(질문이 임베더 한도 초과) 등 계약 오류는 감싸지 않고 그대로 올린다.
            raise
        except Exception as exc:
            # 그 밖의 Qdrant 오류(연결 실패, 컬렉션 없음 등)는 RetrievalError로 감싼다.
            raise RetrievalError(f"Qdrant 검색 실패: {exc}") from exc

        # 검색 결과(points)를 계약 타입(RetrievedChunk) 목록으로 변환한다
        chunks = [
            # payload는 Chunk 스키마를 따른다. rank는 1부터 연속이다.
            RetrievedChunk(rank=i, score=p.score, chunk=_to_chunk(p.payload))
            for i, p in enumerate(points, start=1)
        ]
        return RetrievalResult(
            mode=request.mode,
            k=request.k,
            chunks=chunks,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _search(self, query: str, k: int):
        """동기 검색: 질문을 임베딩하고 Qdrant 에서 가장 가까운 k개 포인트를 가져온다."""
        vector = self._embedder.embed_query(query)  # 한도 초과 시 InvalidInputError
        response = self._client.query_points(
            collection_name=self._index.index_name,
            query=vector,
            limit=k,
            with_payload=True,
        )
        return response.points  # 점수 내림차순. 결과가 없으면 빈 리스트(정상)


def _to_chunk(payload: dict | None) -> Chunk:
    """Qdrant payload를 Chunk로 복원한다. 스키마가 다르면 인덱스 문제이므로 RetrievalError."""
    try:
        return Chunk.model_validate(payload or {})
    except Exception as exc:
        raise RetrievalError(f"payload를 Chunk로 복원하지 못했다: {exc}") from exc
