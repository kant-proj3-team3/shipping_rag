"""목업 검색기: 데모 청크 4개에서 단어 겹침으로 순위를 매긴다. 세 mode 모두 같은 저장소·임베더·k를 쓴다."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence

from common.errors import IndexNotReadyError, RetrievalError
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

DEMO_CHUNKS: list[Chunk] = [
    Chunk(
        chunk_id="DEMO01-p1-0",
        book_id="DEMO01",
        file_name="DEMO01.pdf",
        title="가상해운 장비 안내",
        page_start=1,
        page_end=1,
        text="대상 장비는 20GP와 40GP다. 장비 A의 자동 화면 꺼짐 시간은 10분이다.",
    ),
    Chunk(
        chunk_id="DEMO02-p7-0",
        book_id="DEMO02",
        file_name="DEMO02.pdf",
        title="가상해운 부산–LA 항로 안내",
        page_start=7,
        page_end=8,
        text="본 안내의 대상은 부산 출발, 로스앤젤레스 도착의 일반 건화물 컨테이너 운송이다.",
    ),
    Chunk(
        chunk_id="DEMO_NOTICE-p1-0",
        book_id="DEMO_NOTICE",
        file_name="DEMO_NOTICE.pdf",
        title="정정 공지",
        page_start=1,
        page_end=1,
        text="2026년 11월 2일부터 장비 A의 자동 화면 꺼짐 시간을 10분에서 15분으로 정정한다.",
    ),
    Chunk(
        chunk_id="DEMO01-p21-0",
        book_id="DEMO01",
        file_name="DEMO01.pdf",
        title="가상해운 장비 안내",
        page_start=21,
        page_end=21,
        text="업무 확인 대장: 예약 번호 R-0021, 장비 20GP, 상태 확인 완료.",
    ),
]

# 목업 리랭커의 입력 한도. 인덱스의 max_chunk_tokens 가 이보다 크면 조용히 자르지 않고 IndexNotReadyError 로 알린다.
RERANKER_MAX_INPUT_TOKENS = 512

_MODE_SCALE = {  # 방식마다 점수 척도가 다르다는 점만 흉내낸다. 방식 간 비교 금지.
    RetrievalMode.NAIVE: 1.0,
    RetrievalMode.HYBRID: 2.0,
    RetrievalMode.HYBRID_RERANK: 10.0,
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class MockRetriever:
    def __init__(self, embedder: Embedder, index: IndexManifest) -> None:
        if embedder.embedder_id != index.embedder_id:
            raise IndexNotReadyError(
                f"임베더({embedder.embedder_id})와 인덱스({index.embedder_id})가 다르다"
            )
        if index.max_chunk_tokens > RERANKER_MAX_INPUT_TOKENS:
            raise IndexNotReadyError(
                f"인덱스 청크 한도({index.max_chunk_tokens})가 리랭커 입력 한도({RERANKER_MAX_INPUT_TOKENS})보다 크다"
            )
        self._embedder = embedder
        self._index = index

    @property
    def index(self) -> IndexManifest:
        return self._index

    @property
    def supported_modes(self) -> Sequence[RetrievalMode]:
        return list(RetrievalMode)

    async def retrieve(self, request: RetrievalRequest, ctx: RequestContext) -> RetrievalResult:
        started = time.perf_counter()
        if request.mode not in self.supported_modes:
            raise RetrievalError(f"지원하지 않는 검색 방식: {request.mode}")
        self._embedder.embed_query(request.query)  # 한도 초과는 InvalidInputError 그대로 전파
        q = _tokens(request.query)
        scored = []
        for c in DEMO_CHUNKS:
            overlap = len(q & _tokens(c.text + " " + (c.title or "")))
            if overlap:
                scored.append((overlap * _MODE_SCALE[request.mode], c))
        scored.sort(key=lambda t: (-t[0], t[1].chunk_id))
        top = scored[: request.k]
        return RetrievalResult(
            mode=request.mode,
            k=request.k,
            chunks=[RetrievedChunk(rank=i, score=s, chunk=c) for i, (s, c) in enumerate(top, start=1)],
            latency_ms=(time.perf_counter() - started) * 1000,
        )
