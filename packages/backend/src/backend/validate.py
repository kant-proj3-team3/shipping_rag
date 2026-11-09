"""모델 출력이 계약을 지키는지 코드로 확인하고, 사용자에게 나갈 출처(Citation)를 코드가 채운다.

한눈에 보는 흐름
================

::

    generate_validated(chain, question, context)
      └─ 반복 (재생성 횟수·요청 전체 호출 수 상한 안에서)
           ├─ chain.generate(...)                 # C 단계: 모델 호출 + 스키마 파싱
           ├─ output 이 None            → 실패(스키마 위반·JSON 아님)
           ├─ validate_output(output, items)      # 이 모듈: 의미 검증 + Citation 생성
           │     └─ 실패(OutputValidationError)  → 실패(문맥에 없는 source_id)
           └─ 성공 → ValidatedAnswer / 실패 → 상한 전이면 재생성, 아니면 failure 로 종료

검증은 세 겹이고, 앞의 두 겹은 `ModelOutput` 스키마(prompts.py)가 이미 한다::

    ① 구문·타입      JSON 이고 필드가 맞다, status 가 answered|needs_clarification|abstained 다   (스키마)
    ② 필드 관계      answered 면 source_ids 가 1개 이상이다, source_ids 에 중복이 없다            (스키마)
    ③ 출처 범위      source_ids 가 전부 이번 요청 문맥의 ID 다                                      (여기)

③을 따로 두는 이유: 존재하는 문서여도 이번 요청의 문맥에 없으면 모델이 근거로 쓸 수 없었다. 이번 요청의
`ContextItem` 목록만 기준으로 삼는다(앞 요청의 S1 대응표를 재사용하면 엉뚱한 문서에 출처가 붙는다).

출처 정책
---------
- 범위 밖 source_id 는 status 와 상관없이 항상 거부한다(지어낸 S99 포함).
- `abstained`·`needs_clarification` 의 source_ids 는 범위 안이면 허용한다. 자료끼리 충돌해서 보류할 때
  양쪽 자료를 근거로 드는 응답이 정당할 수 있기 때문이다(프롬프트의 abstained 정의).
- `answered` 는 1개 이상 필수다(스키마).
- 이 검증은 "문장이 그 자료로 지지되는지"를 확인하지 못한다. 그건 답변 평가기(J)와 사람의 대조 몫이다.

이 모듈이 하지 않는 일: `status=error` 응답 만들기와 오류 코드 매핑(qa, E 단계). 여기서는 실패를 예외가 아니라
`ValidationOutcome.failure` 로 돌려주고, E 가 이를 `output_invalid` 로 바꾼다.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field

from langchain_core.callbacks import BaseCallbackHandler

from backend.chain import AnswerChain, ChainResult
from backend.context import ContextBuild
from backend.prompts import ModelOutput, PromptVariant, RenderedPrompt
from common.types import AnswerStatus, Citation, ContextItem

ENV_MAX_REGENERATIONS = "OUTPUT_MAX_REGENERATIONS"
# 임시 기본값. 팀이 정하면 환경변수로 바꾼다(코드 수정 없음).
DEFAULT_MAX_REGENERATIONS = 1


def max_regenerations() -> int:
    """환경변수에서 재생성 상한을 읽는다. 없거나 잘못된(음수·숫자 아님) 값이면 기본값. 0 이면 재생성하지 않는다."""
    raw = os.environ.get(ENV_MAX_REGENERATIONS, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_REGENERATIONS
    return value if value >= 0 else DEFAULT_MAX_REGENERATIONS


# ── 결과 타입 ─────────────────────────────────────────────────────────
class OutputValidationError(ValueError):
    """모델 출력이 문맥과 맞지 않는다. 메시지에는 모델 원문을 넣지 않는다(source_id 같은 짧은 값만)."""


@dataclass(frozen=True)
class ValidatedAnswer:
    """검증을 통과한 답. citations 는 코드가 문맥에서 만든 것이고, 모델이 쓴 문서명·페이지는 쓰지 않는다."""

    status: AnswerStatus
    answer: str
    reason: str
    source_ids: list[str]  # 모델이 고른 ID(문맥 안임이 확인됨). 모델이 쓴 순서 그대로
    citations: list[Citation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationOutcome:
    """`generate_validated` 의 결과. answer 가 None 이면 끝내 통과하지 못한 것이고 failure 에 이유가 있다."""

    answer: ValidatedAnswer | None
    failure: str | None  # 마지막 시도의 실패 이유(안전한 요약). 성공이면 None
    raw_text: str  # 마지막으로 받은 모델 원문(트레이스용)
    prompt: RenderedPrompt  # 마지막으로 모델에 전달한 입력
    calls: int  # 모델을 부른 총 횟수(재시도·재생성 포함)
    regenerations: int  # 검증 실패로 다시 생성한 횟수
    input_tokens: int | None  # 전체 호출의 합. 하나라도 확인 못 하면 None(0 아님)
    output_tokens: int | None

    @property
    def ok(self) -> bool:
        return self.answer is not None


# ── 순수 검증 함수 ────────────────────────────────────────────────────
def find_unknown_source_ids(source_ids: Sequence[str], items: Sequence[ContextItem]) -> list[str]:
    """이번 요청 문맥에 없는 source_id 목록(모델이 쓴 순서). 비어 있으면 모두 범위 안이다."""
    known = {item.source_id for item in items}
    return [sid for sid in source_ids if sid not in known]


def build_citations(source_ids: Sequence[str], items: Sequence[ContextItem]) -> list[Citation]:
    """source_id → Citation. 문서명·페이지는 문맥의 `Chunk` 값이다.

    여러 페이지에 걸친 청크는 페이지마다 Citation 을 하나씩 만든다(`Citation.page` 가 정수 하나라서, 첫 페이지만
    남기면 나머지 페이지가 사라진다). 같은 source_id 로 page 만 다른 Citation 이 이어서 나온다.
    범위 밖 source_id 는 건너뛰지 않고 오류로 본다(검증 전에 부르면 안 된다).
    """
    by_id = {item.source_id: item for item in items}
    citations: list[Citation] = []
    for sid in source_ids:
        chunk = by_id[sid].chunk  # KeyError 는 검증 순서를 어긴 프로그래밍 오류다
        for page in range(chunk.page_start, chunk.page_end + 1):
            citations.append(Citation(source_id=sid, book_id=chunk.book_id, file_name=chunk.file_name, page=page))
    return citations


def validate_output(output: ModelOutput, items: Sequence[ContextItem]) -> ValidatedAnswer:
    """스키마를 통과한 출력이 이번 문맥과 맞는지 확인하고 Citation 을 채운다. 실패하면 OutputValidationError."""
    unknown = find_unknown_source_ids(output.source_ids, items)
    if unknown:
        raise OutputValidationError("이번 문맥에 없는 source_id: " + ", ".join(unknown))
    return ValidatedAnswer(
        status=output.status,
        answer=output.answer,
        reason=output.reason,
        source_ids=list(output.source_ids),
        citations=build_citations(output.source_ids, items),
    )


# ── 재생성을 포함한 생성+검증 ─────────────────────────────────────────
async def generate_validated(
    chain: AnswerChain,
    question: str,
    context: ContextBuild,
    variant: PromptVariant = PromptVariant.BASE,
    *,
    callbacks: Sequence[BaseCallbackHandler] | None = None,
    max_regen: int | None = None,
) -> ValidationOutcome:
    """모델 호출 → 검증을 하고, 실패하면 제한 횟수만큼 다시 생성한다.

    두 가지 상한이 함께 걸린다. ① 재생성 횟수 `max_regen`(기본: 환경변수 OUTPUT_MAX_REGENERATIONS).
    ② 요청 전체의 모델 호출 수 `chain.config.max_calls`(재시도·재생성 합). 둘 중 먼저 닿는 쪽에서 멈춘다.

    전제: 문맥이 비어 있으면 호출하지 않는다(모델 없이 abstained 로 처리하는 일은 E 의 몫). 비었으면 ValueError.
    예외: 호출 실패(ModelTimeoutError/ModelCallError)는 그대로 던진다. 재생성 도중 호출이 실패하면 앞선 호출의
        토큰은 응답에 담지 못하고 잃는다(확인된 값만 집계한다는 원칙상 허용되는 과소 집계).
    """
    if context.is_empty:
        raise ValueError("빈 문맥으로는 생성하지 않는다(호출자가 abstained 로 처리한다)")

    regen_limit = max_regenerations() if max_regen is None else max(0, max_regen)
    call_limit = chain.config.max_calls

    calls = 0
    regenerations = 0
    in_total = out_total = 0
    usage_known = True

    while True:
        result: ChainResult = await chain.generate(
            question, context.text, variant, callbacks=callbacks, attempt_limit=call_limit - calls
        )
        calls += result.attempts
        if result.input_tokens is None or result.output_tokens is None:
            usage_known = False
        else:
            in_total += result.input_tokens
            out_total += result.output_tokens

        validated: ValidatedAnswer | None = None
        if result.output is None:
            failure = result.parse_error or "출력을 읽을 수 없다"
        else:
            try:
                validated = validate_output(result.output, context.items)
                failure = None
            except OutputValidationError as e:
                failure = str(e)

        if validated is not None or regenerations >= regen_limit or calls >= call_limit:
            return ValidationOutcome(
                answer=validated,
                failure=failure,
                raw_text=result.raw_text,
                prompt=result.prompt,
                calls=calls,
                regenerations=regenerations,
                input_tokens=in_total if usage_known else None,
                output_tokens=out_total if usage_known else None,
            )
        regenerations += 1
