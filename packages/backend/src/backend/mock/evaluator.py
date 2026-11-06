"""목업 답변 평가기: 실제 채점을 하지 않는다. 점수를 지어내지 않고 unavailable/not_applicable 로만 답한다."""

from __future__ import annotations

from collections.abc import Sequence

from common.interfaces import Embedder
from common.types import (
    AnswerEvalRecord,
    AnswerEvaluation,
    AnswerStatus,
    JudgeScores,
    Score,
    ScoreState,
)


def _score(state: ScoreState, reason: str) -> Score:
    return Score(state=state, reason=reason)


class MockAnswerEvaluator:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder  # answer_relevancy 용. 목업은 쓰지 않는다

    async def evaluate(self, records: Sequence[AnswerEvalRecord]) -> list[AnswerEvaluation]:
        out: list[AnswerEvaluation] = []
        for rec in records:
            resp = rec.result.response
            if resp.status is AnswerStatus.ERROR:
                state, why = ScoreState.UNAVAILABLE, "오류 응답이라 채점할 답변이 없다"
            elif resp.status is AnswerStatus.ANSWERED:
                state, why = ScoreState.UNAVAILABLE, "목업 평가기: 실제 채점을 하지 않는다"
            else:
                state, why = ScoreState.NOT_APPLICABLE, "사실 주장이 없는 응답"
            s = _score(state, why)
            out.append(
                AnswerEvaluation(
                    item_id=rec.item.id,
                    request_id=resp.request_id,
                    faithfulness=s,
                    ragas_extra={"answer_relevancy": s} if self._embedder is not None else {},
                    judge=JudgeScores(facts=s, conditions=s, evidence=s, decision=s),
                )
            )
        return out
