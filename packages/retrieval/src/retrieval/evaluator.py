"""검색 평가기: Hit@k / Recall@k를 근거 그룹 단위로 계산한다."""

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


MAX_K = 50              # 검색 결과 요청 개수의 상한
MAX_CONCURRENCY = 8     # 동시에 실행할 검색 수의 기본 상한


def chunk_matches(ref: EvidenceRef, chunk: Chunk,
unit: EvidenceUnit) -> bool:
    """정답 근거와 검색된 청크가 문서 또는 페이지 기준으로 일치하는지 판정한다."""
    # 문서가 다르면 페이지 번호와 관계없이 불일치
    if ref.book_id != chunk.book_id:
        return False

    if unit is EvidenceUnit.DOCUMENT:
        return True     # 문서 단위 평가에서는 같은 문서이면 일치


    # 페이지 단위 평가에서는 근거 페이지가 청크의 페이지 범위에 포함되어야 함
    return chunk.page_start <= ref.page <= chunk.page_end



def _mean(values: list[float]) -> float | None:
    """점수 목록의 평균을 반환하고, 계산할 점수가 없으면 None을 반환한다."""
    # 평가 대상 없음(None)과 실제 평가 결과 0점을 구분
    return sum(values) / len(values) if values else None



class GroupRetrievalEvaluator:
    """각 근거 그룹의 충족 여부를 판단하고 문항별·전체 검색 점수를 계산한다."""

    def __init__(self, retriever: Retriever,
max_concurrency: int = MAX_CONCURRENCY) -> None:
        """평가에 사용할 검색기와 동시 검색 수의 상환을 저장한다."""

        self._retriever = retriever
        self._max_concurrency = max_concurrency

    async def evaluate(
            self,
            items: Sequence[GoldenItem],
            mode: RetrievalMode,
            k: int,
            unit: EvidenceUnit,
            golden_fingerprint: str | None = None,
    ) -> RetrievalReport:
        """정답 근거가 있는 평가 문항들을 검색하고, 개별 점수와 평균 보고서를 반환한다."""

        # 잘못된 k로 모든 문항의 검색이 실패하지 않도록 평가 시작 전에 검사 
        if not 1 <= k <= MAX_K:
            raise ValueError(f"k는 1 이상 {MAX_K} 이하여야 한다: {k}")

        # 실제 검색기가 사용하는 인덱스 정보를 보고서에 기록
        index = self._retriever.index

        # 세마포어: 동시에 검색 구간에 진입할 수 있는 작업 수를 제한
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def evaluate_item(item: GoldenItem) -> RetrievalItemMetrics:
            """문항 하나를 검색하고 근거 그룹 충족 여부로 Hit와 Recall를 계산한다."""
            total = len(item.evidence_groups)

            # 근거가 없는 문항은 평가 대상 아님으로 표시하고 검색을 생략 
            if total == 0:
                na = Score(state=ScoreState.NOT_APPLICABLE, reason="근거 그룹이 없는 문항")
                return RetrievalItemMetrics(item_id=item.id, hit=na, recall=na, groups_total=0)

            try:
                async with semaphore:
                    result = await self._retriever.retrieve(
                        RetrievalRequest(
                            query=item.question, 
                            mode=mode,
                            k=k),
                            RequestContext(request_id=f"eval-{item.id}"),
                            )
            except Exception as exc:

                # 검색 실패 문항은 평가 불가로 기록하고 전체 평균에서 제외
                un = Score(
                    state=ScoreState.UNAVAILABLE, 
                    reason=f"{type(exc).__name__}: {exc}"
                    )
                return RetrievalItemMetrics(
                    item_id=item.id, 
                    hit=un, 
                    recall=un, 
                    groups_total=total
                    )

            # 그룹 안의 근거 후보 중 하나라도 검색 청크와 일치하면 해당 그룹 충족
            # 그룹 번호를 한 번만 기록하므로 여러 청크가 일치해도 중복 집계하지 않음
            satisfied = [
                gi for gi, group in enumerate(item.evidence_groups)
                if any(chunk_matches(ref, rc.chunk, unit) for ref in group for rc in result.chunks)
            ]


            # Hit : 한 그룹이라도 찾으면 1점 / Recall: 찾은 그룹 수 + 전체 그룹 수
            # 검색이 성공했지만 결과가 비어 있으면 두 지표 모두 0점
            return RetrievalItemMetrics(
                item_id=item.id,
                hit=Score(value=1.0 if satisfied else 0.0, state=ScoreState.SCORED),
                recall=Score(value=len(satisfied) / total, state=ScoreState.SCORED),
                groups_total=total,
                satisfied_groups=satisfied,
                )

        # 문항 평가를 함께 실행하되, 실제 동시 검색 수는 세마포어로 제한
        metrics = list(await asyncio.gather(*(evaluate_item(i) for i in items)))
        # gather의 반환값은 완료 순서가 아니라 입력 문항 순서를 유지
        scored = [m for m in metrics if m.hit.state is ScoreState.SCORED]


        # 검색 조건, 데이터 식별 정보, 문항별 결과와 상태별 건수를 보고서로 구성
        return RetrievalReport(
            mode=mode,
            k=k,
            unit=unit,
            index_name=index.index_name,
            index_fingerprint=index.fingerprint,
            golden_fingerprint=golden_fingerprint,      # 호출자가 전달한 평가 데이터 식별값
            items=metrics,
            hit_at_k_mean=_mean([m.hit.value for m in scored]),
            recall_at_k_mean=_mean([m.recall.value for m in scored]),
            scored=len(scored),
            not_applicable=sum(m.hit.state is ScoreState.NOT_APPLICABLE for m in metrics),
            unavailable=sum(m.hit.state is ScoreState.UNAVAILABLE for m in metrics),
        )
        

        

        