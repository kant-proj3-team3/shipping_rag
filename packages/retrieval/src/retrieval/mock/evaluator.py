"""목업 검색 평가기: Hit@k / Recall@k를 근거 그룹 단위로 계산한다 (계약 규칙은 실제 구현과 같다)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from common.interfaces import Retriever
from common.types import (
    Chunk,
    EvidenceRef,
    EvidenceUnit,
    GoldenItem,
    RequestContext,
    RetrievalItemMetrics,
    RetrievalMode,
    RetrievalReport,
    RetrievalRequest,
    Score,
    ScoreState,
)


def _matches(ref: EvidenceRef, chunk: Chunk, unit: EvidenceUnit) -> bool:
    if ref.book_id != chunk.book_id:
        return False
    if unit is EvidenceUnit.DOCUMENT:
        return True
    return chunk.page_start <= ref.page <= chunk.page_end


class MockRetrievalEvaluator:
    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    async def evaluate(
        self,
        items: Sequence[GoldenItem],
        mode: RetrievalMode,
        k: int,
        unit: EvidenceUnit,
        golden_fingerprint: str | None = None,
    ) -> RetrievalReport:
        index = self._retriever.index  # 보고서의 인덱스 신원은 주입받은 retriever 에서 읽는다

        async def one(item: GoldenItem) -> RetrievalItemMetrics:
            total = len(item.evidence_groups)
            if total == 0:
                na = Score(state=ScoreState.NOT_APPLICABLE, reason="근거 그룹이 없는 문항")
                return RetrievalItemMetrics(item_id=item.id, hit=na, recall=na, groups_total=0)
            try:
                result = await self._retriever.retrieve(
                    RetrievalRequest(query=item.question, mode=mode, k=k),
                    RequestContext(request_id=f"eval-{item.id}"),
                )
            except Exception as exc:  # 호출 실패는 해당 문항만 unavailable
                un = Score(state=ScoreState.UNAVAILABLE, reason=f"{type(exc).__name__}: {exc}")
                return RetrievalItemMetrics(item_id=item.id, hit=un, recall=un, groups_total=total)
            satisfied = [
                gi
                for gi, group in enumerate(item.evidence_groups)
                if any(_matches(ref, rc.chunk, unit) for ref in group for rc in result.chunks)
            ]
            return RetrievalItemMetrics(
                item_id=item.id,
                hit=Score(value=1.0 if satisfied else 0.0, state=ScoreState.SCORED),
                recall=Score(value=len(satisfied) / total, state=ScoreState.SCORED),
                groups_total=total,
                satisfied_groups=satisfied,
            )

        metrics = list(await asyncio.gather(*(one(i) for i in items)))  # 입력 순서가 유지된다
        scored = [m for m in metrics if m.hit.state is ScoreState.SCORED]
        return RetrievalReport(
            mode=mode,
            k=k,
            unit=unit,
            index_name=index.index_name,
            index_fingerprint=index.fingerprint,
            golden_fingerprint=golden_fingerprint,
            items=metrics,
            hit_at_k_mean=sum(m.hit.value for m in scored) / len(scored) if scored else None,
            recall_at_k_mean=sum(m.recall.value for m in scored) / len(scored) if scored else None,
            scored=len(scored),
            not_applicable=sum(m.hit.state is ScoreState.NOT_APPLICABLE for m in metrics),
            unavailable=sum(m.hit.state is ScoreState.UNAVAILABLE for m in metrics),
        )
