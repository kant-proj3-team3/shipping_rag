"""QAService 실제 구현: A~D 를 한 줄기로 엮고, 모든 실패를 계약된 응답(status=error)으로 바꾼다.

흐름
====

::

    answer(request, ctx)
      ├─ retriever.retrieve(...)            실패 → invalid_input / index_not_ready / retrieval_failed
      ├─ build_context(...)                 B: 토큰 예산 적용
      ├─ 문맥이 비면                         모델 호출 없이 abstained
      ├─ generate_validated(...)            C+D: 모델 호출 → 검증 → 재생성
      │    ├─ ModelTimeoutError             → model_timeout
      │    ├─ ModelCallError                → model_failed
      │    └─ outcome.answer is None        → output_invalid
      └─ 세션 기록(error 제외) → QueryResponse

규칙
----
- `status=error` 는 이 모듈의 코드만 만든다. 모델 출력(`ModelOutput`)은 error 를 고를 수 없다.
- 예외를 호출자에게 던지지 않는다(`asyncio.CancelledError` 같은 BaseException 은 제외).
- 사용자용 오류 문구는 고정 문자열이다. 예외 메시지·스택·내부 주소를 넣지 않는다(서버 로그에만 남긴다).
- `meta.latency_ms` 는 수신~반환 전체이고 실패에도 채운다. 토큰은 확인된 값만(모르면 None).
  모델 호출이 예외로 끝난 요청은 응답을 받지 못해 토큰을 알 수 없으므로 None 이다.
- 세션 기록 실패는 응답을 실패로 만들지 않는다(기록만 건너뛴다).
- Langfuse 기록(F)은 주입받은 `Tracer` 로 하고, 어떤 트레이서든 장애 격리 래퍼를 씌운다. `meta.trace_id` 는 기록을 시작했을 때만
  채운다(tracing.py 모듈 docstring 참고). 기록이 실패해도 응답은 그대로 나간다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from backend.chain import AnswerChain, ModelCallError, ModelTimeoutError
from backend.context import ContextBuild, build_context, context_max_tokens
from backend.prompts import PromptVariant, prompt_version
from backend.tracing import (
    STEP_CONTEXT,
    STEP_RETRIEVE,
    NoopTracer,
    RequestTrace,
    TraceStep,
    Tracer,
    guard,
    redact,
    summarize_context,
    summarize_retrieved,
)
from backend.validate import ValidatedAnswer, generate_validated
from common.errors import IndexNotReadyError, InvalidInputError, RetrievalError
from common.interfaces import Retriever
from common.types import (
    AnswerStatus,
    Citation,
    ContextItem,
    ErrorCode,
    QAResult,
    QueryMeta,
    QueryRequest,
    QueryResponse,
    RequestContext,
    RetrievalMode,
    RetrievalRequest,
    SessionTurn,
)

logger = logging.getLogger(__name__)

# 임시 기본값(목업과 같다). 검색 개수 설정은 팀이 정하면 생성자 인자로 바꾼다.
DEFAULT_MODE = RetrievalMode.HYBRID
DEFAULT_K = 5

# 사용자에게 나가는 문구. 내부 정보가 섞이지 않도록 고정 문자열만 쓴다.
_USER_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_INPUT: "질문을 처리할 수 없습니다. 더 짧게 다시 질문해 주세요.",
    ErrorCode.INDEX_NOT_READY: "검색 인덱스가 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.RETRIEVAL_FAILED: "자료를 검색하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.MODEL_TIMEOUT: "답변 생성이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.MODEL_FAILED: "답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.OUTPUT_INVALID: "답변을 올바른 형식으로 만들지 못했습니다. 질문을 바꿔 다시 시도해 주세요.",
    ErrorCode.INTERNAL: "내부 오류가 발생했습니다.",
}
_REASONS: dict[ErrorCode, str] = {
    ErrorCode.INVALID_INPUT: "입력을 처리할 수 없다",
    ErrorCode.INDEX_NOT_READY: "인덱스가 준비되지 않았다",
    ErrorCode.RETRIEVAL_FAILED: "검색에 실패했다",
    ErrorCode.MODEL_TIMEOUT: "모델 응답 시간이 초과됐다",
    ErrorCode.MODEL_FAILED: "모델 호출에 실패했다",
    ErrorCode.OUTPUT_INVALID: "모델 출력이 검증을 통과하지 못했다",
    ErrorCode.INTERNAL: "서버 오류",
}

_EMPTY_ANSWER = "제공된 자료에서 답할 근거를 찾지 못했습니다. 관련 문서를 추가로 확인해 주세요."
_EMPTY_REASON = "검색 결과가 없다"
_EMPTY_BUDGET_REASON = "문맥 토큰 예산 안에 들어오는 자료가 없다"


def error_code_for(exc: BaseException) -> ErrorCode:
    """예외 → 오류 코드. 목록에 없는 예외(IngestError 포함)는 internal 이다."""
    if isinstance(exc, InvalidInputError):
        return ErrorCode.INVALID_INPUT
    if isinstance(exc, IndexNotReadyError):
        return ErrorCode.INDEX_NOT_READY
    if isinstance(exc, RetrievalError):
        return ErrorCode.RETRIEVAL_FAILED
    if isinstance(exc, ModelTimeoutError):
        return ErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelCallError):
        return ErrorCode.MODEL_FAILED
    return ErrorCode.INTERNAL


class SessionRecorder(Protocol):
    """턴을 기록하는 저장소(목업 메모리 저장소 또는 `PersistentSessionStore`). 블로킹 호출이어도 된다: 서비스가 스레드로 부른다."""

    def append(self, session_id: str, turn: SessionTurn) -> None: ...


class BackendQAService:
    def __init__(
        self,
        retriever: Retriever,
        chain: AnswerChain,
        sessions: SessionRecorder,
        *,
        default_mode: RetrievalMode = DEFAULT_MODE,
        k: int = DEFAULT_K,
        variant: PromptVariant = PromptVariant.BASE,
        tracer: Tracer | None = None,
    ) -> None:
        self._retriever = retriever
        self._chain = chain
        self._sessions = sessions
        self._default_mode = default_mode
        self._k = k
        self._variant = variant
        # 기록은 부가 기능이다. 어떤 트레이서가 들어와도 장애 격리 래퍼를 씌워 응답에 영향이 없게 한다.
        self._tracer: Tracer = guard(tracer if tracer is not None else NoopTracer())

    async def answer(self, request: QueryRequest, ctx: RequestContext) -> QAResult:
        started = time.perf_counter()
        mode = request.retrieval_mode or self._default_mode
        trace = self._tracer.start(
            ctx.request_id, request.question, mode, k=self._k, prompt_version=prompt_version(self._variant)
        )
        try:
            result = await self._run(request, ctx, mode, started, trace)
        except BaseException:  # CancelledError 등: 응답이 없어도 열린 단계를 닫는다
            trace.abort()
            raise
        trace.end(result.response, result.final_context)
        return result

    async def _run(
        self, request: QueryRequest, ctx: RequestContext, mode: RetrievalMode, started: float, trace: RequestTrace
    ) -> QAResult:
        context: ContextBuild | None = None
        active: TraceStep | None = None  # 실패했을 때 오류로 닫을 단계
        trace_id = trace.trace_id  # 기록을 시작하지 못했으면 None

        def meta(input_tokens: int | None = None, output_tokens: int | None = None) -> QueryMeta:
            # 호출 시점에 재서 실패 응답에도 시간이 채워진다. 확인 못 한 값은 None 으로 둔다.
            return QueryMeta(
                retrieval_mode=mode,
                latency_ms=(time.perf_counter() - started) * 1000,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                trace_id=trace_id,
            )

        def final_context() -> list[ContextItem]:
            return list(context.items) if context is not None else []

        def error(code: ErrorCode, input_tokens: int | None = None, output_tokens: int | None = None) -> QAResult:
            resp = QueryResponse(
                request_id=ctx.request_id,
                status=AnswerStatus.ERROR,
                answer=_USER_MESSAGES[code],
                reason=_REASONS[code],
                error_code=code,
                meta=meta(input_tokens, output_tokens),
            )
            return QAResult(response=resp, final_context=final_context())  # 오류는 세션에 기록하지 않는다

        try:
            active = trace.step(STEP_RETRIEVE, {"mode": mode.value, "k": self._k})
            retrieved = await self._retriever.retrieve(
                RetrievalRequest(query=request.question, mode=mode, k=self._k), ctx
            )
            active.end(summarize_retrieved(retrieved.chunks))

            max_tokens = context_max_tokens()
            active = trace.step(STEP_CONTEXT, {"max_tokens": max_tokens, "retrieved": len(retrieved.chunks)})
            context = build_context(retrieved.chunks, max_tokens=max_tokens)
            active.end(
                summarize_context(
                    context.items, context.dropped_chunk_ids, context.count_before, context.count_after, context.token_count
                )
            )
            active = None

            if context.is_empty:  # 모델을 호출하지 않는다
                reason = _EMPTY_REASON if not retrieved.chunks else _EMPTY_BUDGET_REASON
                trace.annotate(model_called=False)
                return await self._finish(
                    request, ctx, mode, meta(), AnswerStatus.ABSTAINED, _EMPTY_ANSWER, reason, [], []
                )

            outcome = await generate_validated(
                self._chain, request.question, context, self._variant, callbacks=trace.callbacks() or None
            )
        except Exception as exc:  # noqa: BLE001 - 계약: 예외를 던지지 않고 error 응답으로 바꾼다
            code = error_code_for(exc)
            if active is not None:
                active.end(error=code.value)
            trace.annotate(model_called=active is None)  # 단계가 닫힌 뒤에 난 오류 = 모델 호출 단계의 실패
            # 원본 메시지는 사용자 응답에 쓰지 않는다. 서버 로그에는 종류와 스택을 남긴다.
            logger.warning("질의 처리 실패 request_id=%s code=%s", ctx.request_id, code.value, exc_info=True)
            return error(code)

        trace.annotate(
            model_called=True,
            model_calls=outcome.calls,
            regenerations=outcome.regenerations,
            validation_failure=outcome.failure,  # 안전한 요약(모델 원문 없음)
        )
        if outcome.answer is None:
            logger.warning("출력 검증 실패 request_id=%s calls=%d", ctx.request_id, outcome.calls)
            return error(ErrorCode.OUTPUT_INVALID, outcome.input_tokens, outcome.output_tokens)

        validated: ValidatedAnswer = outcome.answer
        return await self._finish(
            request,
            ctx,
            mode,
            meta(outcome.input_tokens, outcome.output_tokens),
            validated.status,
            validated.answer,
            validated.reason,
            validated.citations,
            context.items,
        )

    async def _finish(
        self,
        request: QueryRequest,
        ctx: RequestContext,
        mode: RetrievalMode,
        meta: QueryMeta,
        status: AnswerStatus,
        answer: str,
        reason: str,
        citations: Sequence[Citation],
        items: Sequence[ContextItem],
    ) -> QAResult:
        resp = QueryResponse(
            request_id=ctx.request_id,
            status=status,
            answer=answer,
            reason=reason,
            citations=list(citations),
            meta=meta,
        )
        if request.session_id:
            try:
                turn = SessionTurn(
                    request_id=ctx.request_id,
                    asked_at=datetime.now(UTC),
                    question=redact(request.question),  # 영구 저장하므로 이메일·키 모양을 가린다(계약 v0.1.1)
                    retrieval_mode=mode,
                    status=status,
                    answer=answer,
                    citations=list(citations),
                )
                # 저장소(Redis)가 동기 호출이라 이벤트 루프 밖에서 부른다. 멈춰도 다른 요청을 막지 않는다.
                await asyncio.to_thread(self._sessions.append, request.session_id, turn)
            except Exception:  # noqa: BLE001 - 기록 실패가 답변 실패가 되지 않게 한다
                logger.warning("세션 기록 실패 request_id=%s", ctx.request_id, exc_info=True)
        return QAResult(response=resp, final_context=list(items))
