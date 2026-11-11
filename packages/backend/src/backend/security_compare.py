"""보안 비교 지원(K): 같은 최종 문맥으로 기본 프롬프트와 방어 문장 프롬프트를 각각 실행한다.

한눈에 보는 구조
================

::

    저장해 둔 final_context ──┬─▶ [기본 프롬프트]   ─▶ VariantRun(base)
    (재검색 없음)             └─▶ [방어 문장 프롬프트] ─▶ VariantRun(guarded)
                                      같은 모델·같은 문맥 문자열·같은 출력 스키마·같은 호출 한도

서비스 경로(`BackendQAService`)와 **분리된** 경로다. 이 모듈은 검색, 세션 기록, 답변 캐시, Langfuse 트레이스, `QueryResponse`
(운영 `meta`)를 건드리지 않는다. 그래서 비교 실험의 호출이 서비스 운영 지표(응답 시간·오류율·토큰·캐시 적중)에 섞이지 않는다.
결과의 시간·토큰은 `VariantRun` 안에만 있고 서비스 지표와 무관한 실험 기록이다.

지키는 것
---------
- **재검색 금지**: 입력은 질문과 저장된 `final_context`뿐이고 `Retriever` 를 받지 않는다.
- **두 호출의 입력이 같다**: 문맥 문자열은 한 번만 만들어 두 변형에 그대로 쓴다(`build_context` 와 같은 형식: `[S1] 파일명 p.3\\n본문`을
  빈 줄로 잇는다). 달라지는 것은 시스템 프롬프트의 방어 문장 한 줄(`GUARD_SENTENCE`)뿐이다. 모델·출력 형식·재시도·재생성 한도도 같은
  체인과 같은 인자를 쓴다.
- **`attack_text` 를 문맥에 붙이지 않는다**: 공격 문구는 이미 코퍼스 문서(= `final_context` 안의 청크)에 들어 있다. `attack_text` 인자는
  **확인용**이다: 프롬프트를 만든 뒤 그 문구가 실제 모델 입력에 들어 있는지 대조하는 데만 쓰고 어떤 프롬프트에도 넣지 않는다.
- **정답 정보는 받지 않는다**: 입력은 질문 문자열과 문맥뿐이다(`GoldenItem` 을 받지 않는다). 채점은 `AnswerEvaluator`(J)가 한다.
- 이력(멀티턴)은 쓰지 않는다. 보안 문항은 단발로 비교한다.

실패는 던지지 않는다: 모델 호출 실패·검증 실패는 그 변형의 `VariantRun` 에 오류로 담고 다른 변형은 계속 실행한다.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from backend.chain import AnswerGenerator, ModelCallError, ModelTimeoutError
from backend.context import ContextBuild, _render_block
from backend.prompts import PromptVariant, RenderedPrompt, _neutralize_tags
from backend.validate import ValidatedAnswer, generate_validated
from common.types import (
    AnswerEvalRecord,
    AnswerStatus,
    ContextItem,
    ErrorCode,
    GoldenItem,
    QAResult,
    QueryMeta,
    QueryResponse,
    RetrievalMode,
)

COMPARISON_VARIANTS: tuple[PromptVariant, ...] = (PromptVariant.BASE, PromptVariant.GUARDED)
_SEPARATOR = "\n\n"  # build_context 와 같은 구분자(모델이 본 문맥 형식을 그대로 재현한다)


@dataclass(frozen=True)
class AttackCheck:
    """공격 문구가 실제 모델 입력에 들어갔는지. 확인용이며 프롬프트에는 아무것도 더하지 않는다."""

    in_user_message: bool  # 사용자 메시지(질문+검색 자료 영역)에 있다 = 모델이 공격 문구를 읽었다
    in_system_message: bool  # 시스템 프롬프트에 있다(있으면 안 된다: 공격 문구가 지시 영역에 새어 들어간 것)
    source_ids: tuple[str, ...]  # 문구를 포함한 문맥 조각(S번호)


@dataclass(frozen=True)
class VariantRun:
    """한 프롬프트 변형의 실행 결과. 실험 기록이며 서비스 지표가 아니다."""

    variant: PromptVariant
    prompt: RenderedPrompt | None  # 모델에 실제 전달한 입력(system·user). 모델을 부르지 못했으면 마지막 입력 또는 None
    answer: ValidatedAnswer | None  # 검증을 통과한 답. 실패·건너뜀이면 None
    error_code: ErrorCode | None  # 모델 호출 실패(model_timeout/model_failed)·출력 검증 실패(output_invalid)
    failure: str | None  # 실패 이유의 안전한 요약(모델 원문·키 없음)
    skipped: str | None  # 모델을 부르지 않은 이유(예: 문맥이 비어 있다)
    calls: int | None  # 모델 호출 횟수(재시도·재생성 포함). 부르지 않았으면 0, 호출 실패면 알 수 없어 None
    input_tokens: int | None  # 확인된 값만. 모르면 None(0 아님)
    output_tokens: int | None
    latency_ms: float
    attack: AttackCheck | None  # attack_text 를 줬을 때만

    @property
    def ok(self) -> bool:
        return self.answer is not None


@dataclass(frozen=True)
class SecurityComparison:
    """같은 문맥에 대한 변형별 실행 결과. `runs` 는 요청한 변형 순서와 같다."""

    context_text: str  # 두 변형이 공통으로 본 문맥 문자열
    runs: tuple[VariantRun, ...]

    def run(self, variant: PromptVariant) -> VariantRun:
        for r in self.runs:
            if r.variant is variant:
                return r
        raise KeyError(variant)


# ── 문맥 ─────────────────────────────────────────────────────────────
def render_context(final_context: Sequence[ContextItem]) -> ContextBuild:
    """저장한 `final_context` 를 모델 문맥으로 되돌린다. 토큰 예산은 다시 적용하지 않는다(이미 예산을 거친 목록이다)."""
    items = list(final_context)
    text = _SEPARATOR.join(_render_block(i.source_id, i.chunk) for i in items)
    return ContextBuild(items=items, text=text, count_before=len(items), count_after=len(items))


def _squash(text: str) -> str:
    return " ".join(text.split())


def check_attack(attack_text: str, prompt: RenderedPrompt, items: Sequence[ContextItem]) -> AttackCheck:
    """공격 문구가 모델 입력에 있는지 대조한다. 공백 차이는 무시하고, 입력 속 영역 표식 무력화(전각 변환)도 고려한다."""
    needles = {_squash(attack_text), _squash(_neutralize_tags(attack_text))}
    needles.discard("")

    def contains(haystack: str) -> bool:
        flat = _squash(haystack)
        return any(n in flat for n in needles)

    return AttackCheck(
        in_user_message=contains(prompt.user),
        in_system_message=contains(prompt.system),
        source_ids=tuple(i.source_id for i in items if contains(i.chunk.text)),
    )


# ── 실행 ─────────────────────────────────────────────────────────────
async def run_variant(
    chain: AnswerGenerator,
    question: str,
    context: ContextBuild,
    variant: PromptVariant,
    *,
    attack_text: str | None = None,
    max_regen: int | None = None,
) -> VariantRun:
    """한 변형을 실행한다. 모델 호출 실패·검증 실패는 예외 대신 결과에 담는다(프로그래밍 오류는 그대로 던진다)."""
    started = time.perf_counter()

    def elapsed() -> float:
        return (time.perf_counter() - started) * 1000.0

    if context.is_empty:
        # 서비스도 빈 문맥이면 모델을 부르지 않는다. 비교할 입력이 없으므로 건너뛴다.
        return VariantRun(variant, None, None, None, None, "empty_context", 0, None, None, elapsed(), None)

    try:
        outcome = await generate_validated(chain, question, context, variant, max_regen=max_regen)
    except ModelTimeoutError:
        code, why = ErrorCode.MODEL_TIMEOUT, "모델 응답 시간이 초과되었다"
    except ModelCallError:
        code, why = ErrorCode.MODEL_FAILED, "모델 호출에 실패했다"
    else:
        attack = check_attack(attack_text, outcome.prompt, context.items) if attack_text else None
        return VariantRun(
            variant=variant,
            prompt=outcome.prompt,
            answer=outcome.answer,
            error_code=None if outcome.ok else ErrorCode.OUTPUT_INVALID,
            failure=outcome.failure,
            skipped=None,
            calls=outcome.calls,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_ms=elapsed(),
            attack=attack,
        )
    # 호출 자체가 실패했다: 입력은 같은 방식으로 다시 만들 수 있지만 모델이 받았는지 알 수 없으므로 prompt 는 비워 둔다
    return VariantRun(variant, None, None, code, why, None, None, None, None, elapsed(), None)


async def compare_variants(
    chain: AnswerGenerator,
    question: str,
    final_context: Sequence[ContextItem],
    *,
    variants: Sequence[PromptVariant] = COMPARISON_VARIANTS,
    attack_text: str | None = None,
    max_regen: int | None = None,
) -> SecurityComparison:
    """저장한 `final_context` 로 변형마다 한 번씩 생성한다(재검색 없음, 순차 실행).

    순차로 도는 이유: 같은 조건에서 비교하고, 한 문항의 호출 수를 예측 가능하게 하려는 것이다.
    `attack_text` 는 확인용이다(`VariantRun.attack`). 문맥이나 프롬프트에는 더하지 않는다.
    """
    context = render_context(final_context)
    runs = [
        await run_variant(chain, question, context, variant, attack_text=attack_text, max_regen=max_regen)
        for variant in variants
    ]
    return SecurityComparison(context_text=context.text, runs=tuple(runs))


# ── 평가기(J) 연결 ───────────────────────────────────────────────────
def to_eval_record(
    item: GoldenItem,
    run: VariantRun,
    final_context: Sequence[ContextItem],
    *,
    mode: RetrievalMode,
    request_id: str,
) -> AnswerEvalRecord:
    """변형 실행 결과를 `AnswerEvaluator` 입력으로 바꾼다. 실제 서비스 응답이 아니라 실험 기록을 같은 모양에 담은 것이다.

    `meta` 에는 확인된 값(토큰·시간)만 넣고 `cache_hit`·`trace_id` 는 비운다. 이 레코드는 서비스 지표 집계에 쓰지 않는다.
    """
    if run.answer is not None:
        status, answer, reason = run.answer.status, run.answer.answer, run.answer.reason
        citations, error_code = run.answer.citations, None
    elif run.skipped is not None:
        # 서비스와 같은 규칙: 문맥이 비면 모델을 부르지 않고 abstained
        status, answer, reason = AnswerStatus.ABSTAINED, "관련 자료를 찾지 못했습니다.", "문맥이 비어 모델을 호출하지 않았다"
        citations, error_code = [], None
    else:
        status, answer, reason, citations = AnswerStatus.ERROR, "답변을 만들지 못했습니다.", run.failure or "오류", []
        error_code = run.error_code or ErrorCode.INTERNAL
    response = QueryResponse(
        request_id=request_id,
        status=status,
        answer=answer,
        reason=reason,
        citations=list(citations),
        error_code=error_code,
        meta=QueryMeta(
            retrieval_mode=mode,
            latency_ms=run.latency_ms,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
        ),
    )
    return AnswerEvalRecord(item=item, result=QAResult(response=response, final_context=list(final_context)))


__all__ = [
    "COMPARISON_VARIANTS",
    "AttackCheck",
    "SecurityComparison",
    "VariantRun",
    "check_attack",
    "compare_variants",
    "render_context",
    "run_variant",
    "to_eval_record",
]
