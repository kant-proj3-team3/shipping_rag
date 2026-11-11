"""평가 러너: 문항 × 검색 방식으로 서비스를 호출하고 답변 평가기(J)로 채점하거나, 보안 문항을 두 프롬프트로 비교한다(K).

`app/` 의 조립 코드다(모듈을 아는 곳은 app 뿐이다). 규칙(`CLAUDE.md` 「평가할 때 지킬 것」):
- 세 검색 방식은 같은 질문·같은 임베딩·저장소로 비교한다. 서비스에는 `item.question` 만 전달한다(정답은 평가기만 쓴다).
- 평균은 채점된(`scored`) 문항만으로 내고 분모(채점·해당 없음·평가 불가)를 함께 보고한다. 미확인 값을 0 으로 채우지 않는다.
- 비용·시간·토큰은 확인된 값만 집계하고 분모(전체 요청)와 집계 건수를 함께 남긴다.
- 보고서에 `index_fingerprint`·`golden_fingerprint` 를 남긴다.
- 평가 중에는 답변 캐시를 끈다(적중한 응답은 모델을 부르지 않아 시간·토큰 지표를 왜곡한다). 호출하는 쪽(`cli`)이 끈다.

함수는 협력 객체(`QAService`, `AnswerEvaluator`, 체인)를 인자로 받아 외부 서비스 없이 테스트할 수 있다.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.prompts import PromptVariant
from backend.security_compare import SecurityComparison, compare_variants, to_eval_record
from common.interfaces import AnswerEvaluator, QAService
from common.types import (
    AnswerEvalRecord,
    AnswerEvaluation,
    AnswerStatus,
    GoldenItem,
    QAResult,
    QueryRequest,
    RequestContext,
    RetrievalMode,
    Score,
    ScoreState,
)

JUDGE_KEYS = ("facts", "conditions", "evidence", "decision")


# ── 서비스 호출 ──────────────────────────────────────────────────────
async def run_service(
    qa: QAService,
    items: Sequence[GoldenItem],
    mode: RetrievalMode,
    *,
    run_id: str,
    concurrency: int = 2,
) -> list[QAResult]:
    """문항마다 서비스를 호출한다(입력과 같은 순서). 서비스에는 `item.question` 과 검색 방식만 준다."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(item: GoldenItem) -> QAResult:
        async with semaphore:
            request = QueryRequest(question=item.question, retrieval_mode=mode)  # 세션 없음: 단발, 기록하지 않는다
            return await qa.answer(request, RequestContext(request_id=f"{run_id}:{mode.value}:{item.id}"))

    return list(await asyncio.gather(*(one(i) for i in items)))


# ── 집계 ─────────────────────────────────────────────────────────────
def _nearest_rank(sorted_values: list[float], q: float) -> float:
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def summarize_service(results: Sequence[QAResult]) -> dict[str, Any]:
    """서비스 응답 집계. 지연·토큰은 확인된 값만 쓰고, 분모(전체 요청)와 집계 건수를 함께 둔다."""
    responses = [r.response for r in results]
    total = len(responses)
    status_counts = {s.value: sum(r.status is s for r in responses) for s in AnswerStatus}
    latencies = sorted(r.meta.latency_ms for r in responses if r.meta.latency_ms is not None)
    in_tokens = [r.meta.input_tokens for r in responses if r.meta.input_tokens is not None]
    out_tokens = [r.meta.output_tokens for r in responses if r.meta.output_tokens is not None]
    costs = [r.meta.cost_usd for r in responses if r.meta.cost_usd is not None]
    return {
        "requests": total,
        "status_counts": status_counts,
        "error_rate": status_counts["error"] / total if total else None,
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
            "p95": _nearest_rank(latencies, 0.95) if latencies else None,
            "counted": len(latencies),
        },
        "input_tokens": {"sum": sum(in_tokens) if in_tokens else None, "counted": len(in_tokens)},
        "output_tokens": {"sum": sum(out_tokens) if out_tokens else None, "counted": len(out_tokens)},
        "cost_usd": {"sum": sum(costs) if costs else None, "counted": len(costs)},  # 확인된 비용만(보통 None)
        "cache_hits": sum(r.meta.cache_hit for r in responses),  # 0 이어야 한다(평가 중에는 캐시를 끈다)
    }


def summarize_scores(scores: Sequence[Score]) -> dict[str, Any]:
    """점수 목록 집계: 평균은 scored 만, 분모(scored/not_applicable/unavailable)를 함께 보고한다."""
    scored = [s.value for s in scores if s.state is ScoreState.SCORED and s.value is not None]
    return {
        "mean": statistics.fmean(scored) if scored else None,
        "scored": len(scored),
        "not_applicable": sum(s.state is ScoreState.NOT_APPLICABLE for s in scores),
        "unavailable": sum(s.state is ScoreState.UNAVAILABLE for s in scores),
        "total": len(scores),
    }


def summarize_evaluations(evals: Sequence[AnswerEvaluation]) -> dict[str, Any]:
    out: dict[str, Any] = {"faithfulness": summarize_scores([e.faithfulness for e in evals])}
    extra_names = sorted({name for e in evals for name in e.ragas_extra})
    for name in extra_names:
        out[name] = summarize_scores([e.ragas_extra[name] for e in evals if name in e.ragas_extra])
    for key in JUDGE_KEYS:
        out[f"judge.{key}"] = summarize_scores([getattr(e.judge, key) for e in evals])
    return out


def _score_cell(score: Score) -> dict[str, Any]:
    return {"state": score.state.value, "value": score.value, "reason": score.reason}


def _evaluation_row(item: GoldenItem, result: QAResult, ev: AnswerEvaluation) -> dict[str, Any]:
    r = result.response
    return {
        "item_id": item.id,
        "split": item.split.value,
        "expected_action": item.expected_action.value,
        "status": r.status.value,
        "error_code": r.error_code.value if r.error_code else None,
        "citations": [f"{c.book_id}:p{c.page}" for c in r.citations],
        # 실패 원인 분석용: 모델이 실제로 낸 답과 이유, 모델에 전달한 문맥(S번호 순서대로 문서:페이지), Langfuse trace.
        "answer": r.answer,
        "reason": r.reason,
        "context_pages": [f"{i.chunk.book_id}:p{i.chunk.page_start}" for i in result.final_context],
        "trace_id": r.meta.trace_id,
        "faithfulness": _score_cell(ev.faithfulness),
        "ragas_extra": {k: _score_cell(v) for k, v in ev.ragas_extra.items()},
        "judge": {k: _score_cell(getattr(ev.judge, k)) for k in JUDGE_KEYS},
    }


# ── 답변 평가 ────────────────────────────────────────────────────────
async def evaluate_answers(
    qa: QAService,
    evaluator: AnswerEvaluator,
    items: Sequence[GoldenItem],
    modes: Sequence[RetrievalMode],
    *,
    run_id: str,
    concurrency: int = 2,
    on_mode: Callable[[RetrievalMode, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """검색 방식마다 같은 문항을 서비스에 묻고(`run_service`) 평가기로 채점한다. 방식별 보고서를 돌려준다."""
    reports: dict[str, Any] = {}
    for mode in modes:
        results = await run_service(qa, items, mode, run_id=run_id, concurrency=concurrency)
        evals = await evaluator.evaluate([AnswerEvalRecord(item=i, result=r) for i, r in zip(items, results, strict=True)])
        report = {
            "service": summarize_service(results),
            "scores": summarize_evaluations(evals),
            "items": [_evaluation_row(i, r, e) for i, r, e in zip(items, results, evals, strict=True)],
        }
        reports[mode.value] = report
        if on_mode:
            on_mode(mode, report)
    return reports


# ── 보안 비교 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SecurityRow:
    item: GoldenItem
    comparison: SecurityComparison
    evaluations: dict[PromptVariant, AnswerEvaluation]


async def compare_security(
    qa: QAService,
    chain: Any,
    evaluator: AnswerEvaluator,
    items: Sequence[GoldenItem],
    mode: RetrievalMode,
    *,
    run_id: str,
    concurrency: int = 2,
) -> dict[str, Any]:
    """보안 문항마다 서비스로 최종 문맥을 한 번 얻고, 그 문맥으로 기본·방어 프롬프트를 각각 실행해 채점한다.

    서비스 호출은 검색과 문맥 구성(`final_context`)을 얻기 위한 것이고, 비교 실행은 서비스를 거치지 않는다(재검색 없음).
    """
    results = await run_service(qa, items, mode, run_id=run_id, concurrency=concurrency)
    comparisons: list[SecurityComparison] = []
    for item, result in zip(items, results, strict=True):
        assert item.security is not None, "보안 문항(split=security)만 비교한다"
        comparisons.append(
            await compare_variants(chain, item.question, result.final_context, attack_text=item.security.attack_text)
        )

    records: list[AnswerEvalRecord] = []
    index: list[tuple[int, PromptVariant]] = []
    for n, (item, result, cmp) in enumerate(zip(items, results, comparisons, strict=True)):
        for run in cmp.runs:
            rid = f"{run_id}:{mode.value}:{item.id}:{run.variant.value}"
            records.append(to_eval_record(item, run, result.final_context, mode=mode, request_id=rid))
            index.append((n, run.variant))
    evals = await evaluator.evaluate(records)

    by_item: list[dict[PromptVariant, AnswerEvaluation]] = [{} for _ in items]
    for (n, variant), ev in zip(index, evals, strict=True):
        by_item[n][variant] = ev

    variants = [PromptVariant.BASE, PromptVariant.GUARDED]
    summary: dict[str, Any] = {
        "items": len(items),
        # 공격 문구가 실제 모델 입력에 들어간 문항 수. 이 값이 작으면 두 프롬프트의 차이를 방어 효과로 읽을 수 없다
        "attack_in_model_input": sum(
            1 for c in comparisons if c.runs and c.runs[0].attack is not None and c.runs[0].attack.in_user_message
        ),
        "attack_not_in_input": [
            item.id
            for item, c in zip(items, comparisons, strict=True)
            if not (c.runs and c.runs[0].attack is not None and c.runs[0].attack.in_user_message)
        ],
    }
    for variant in variants:
        runs = [c.run(variant) for c in comparisons if any(r.variant is variant for r in c.runs)]
        evs = [e[variant] for e in by_item if variant in e]
        summary[variant.value] = {
            "runs": len(runs),
            "ok": sum(r.ok for r in runs),
            "skipped": sum(r.skipped is not None for r in runs),
            "failed": sum(r.error_code is not None for r in runs),
            "scores": summarize_evaluations(evs),
        }
    rows = []
    for item, cmp, evs in zip(items, comparisons, by_item, strict=True):
        row: dict[str, Any] = {"item_id": item.id, "attack_type": item.security.attack_type if item.security else None}
        for run in cmp.runs:
            ev = evs.get(run.variant)
            row[run.variant.value] = {
                "status": run.answer.status.value if run.answer else None,
                "error_code": run.error_code.value if run.error_code else None,
                "skipped": run.skipped,
                "attack_in_model_input": run.attack.in_user_message if run.attack else None,
                "attack_in_system_prompt": run.attack.in_system_message if run.attack else None,
                "input_tokens": run.input_tokens,
                "judge": {k: _score_cell(getattr(ev.judge, k)) for k in JUDGE_KEYS} if ev else None,
            }
        rows.append(row)
    return {"mode": mode.value, "summary": summary, "items": rows}
