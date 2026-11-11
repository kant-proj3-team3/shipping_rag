"""요청 하나의 전 과정을 Langfuse 에 `request_id` 기준으로 묶어 기록한다(F 단계).

한눈에 보는 구조
================

한 요청은 trace 하나가 되고, 안에 단계(observation)가 트리로 달린다::

    qa-query                         root span  입력=질문, 출력=status·answer·citations, 메타=request_id·토큰·시간·오류 코드
      ├─ load-history                (session_id 가 있고 멀티턴이 켜졌을 때) 이전 대화 개수. 본문은 넣지 않는다
      ├─ retrieve                    검색 결과: rank·score·chunk_id (전부)
      ├─ build-context               예산 적용 전후: 검색된 chunk_id ↔ 최종 문맥(S번호↔chunk_id) ↔ 제외된 chunk_id
      ├─ generate-answer             LangChain CallbackHandler 가 만든 단계(ChatOpenAI GENERATION 에 실제 모델 입출력·토큰)
      └─ record-session              (session_id 가 있을 때) 세션 저장소(DB·Redis) 기록. 실패하면 ERROR 로 닫힌다

record-session 이 따로 있는 이유: 저장소가 느려지거나 꺼졌을 때(timeout 만큼 요청이 늦어진다) 그 지연이 어느 단계에도 안 잡히면
원인을 찾기 어렵다. 정상일 때는 수 ms 다. `meta.latency_ms` 는 이 기록 직전까지의 시간이고 root span 은 기록까지 포함한다.

"검색에서 못 찾음"과 "문맥 축소 중 빠짐"은 retrieve 와 build-context 를 나란히 보면 구분된다
(검색 결과에는 있는데 dropped_chunk_ids 에 있으면 문맥 축소, 처음부터 없으면 검색 단계 문제).

trace_id 와 request_id
----------------------
`trace_id` 는 `request_id` 를 씨앗으로 만든 값이라(`Langfuse.create_trace_id(seed=...)`) 같은 request_id 는 항상 같은
trace 에 모인다. 이 값은 **로컬에서 만든 식별자**다. 전송은 SDK 가 백그라운드로 하므로 서버에 도착했는지는 이 시점에
알 수 없다(flush 와 서버 조회가 따로 필요하다). 그래서 응답의 `meta.trace_id` 는 "기록을 시작했다"는 뜻이고, 도착 여부는
README 의 확인 방법(Langfuse 화면에서 request_id 로 검색)으로 본다. 기록을 시작하지 못했으면 `None` 이다.

장애 격리
---------
기록은 부가 기능이다. Langfuse 가 꺼져 있거나 SDK 가 예외를 내도 `/query` 응답은 그대로 나간다.
`create_tracer()` 가 돌려주는 객체는 항상 `_SafeTracer` 로 감싸져 있어서, 안쪽에서 난 예외를 모두 잡아 경고 로그만 남기고
기본값(trace_id=None, 빈 콜백)으로 돌아간다. 키가 없거나 `LANGFUSE_TRACING_ENABLED=false` 면 아무것도 하지 않는 구현을 쓴다.

개인정보·키
-----------
전송 직전에 `mask_otel_spans` 가 모든 문자열 속성에서 이메일과 API 키(환경에 설정된 키 값 자체 포함)를 가린다. 질문 원문은
그대로 남기되 이 규칙만 적용한다. 정규식이라 이름·주소 같은 다른 개인정보는 막지 못한다(범위를 README 에 적었다).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler

from common.types import ContextItem, QueryResponse, RetrievalMode, RetrievedChunk

logger = logging.getLogger(__name__)

ENV_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
ENV_SECRET_KEY = "LANGFUSE_SECRET_KEY"
ENV_TRACING_ENABLED = "LANGFUSE_TRACING_ENABLED"  # SDK 가 쓰는 이름 그대로. false 면 끈다

ROOT_NAME = "qa-query"
STEP_RETRIEVE = "retrieve"
STEP_CONTEXT = "build-context"
STEP_HISTORY = "load-history"  # 멀티턴: 세션 이력을 읽어 프롬프트에 넣을 이전 대화를 고르는 단계
STEP_CACHE = "cache-lookup"  # 답변 캐시 조회. 적중하면 검색·모델 호출 단계는 생기지 않는다(이력이 있는 요청은 우회해서 이 단계도 없다)
STEP_SESSION = "record-session"  # 끝난 질의응답을 세션 저장소(DB·Redis)에 기록하는 단계. session_id 가 있을 때만 생긴다


# ── 공개 인터페이스 ───────────────────────────────────────────────────
class TraceStep(Protocol):
    """요청 안의 한 단계(검색, 문맥 빌드). `end` 는 여러 번 불러도 한 번만 반영된다."""

    def end(self, output: Any = None, *, error: str | None = None) -> None: ...


class RequestTrace(Protocol):
    """요청 하나의 기록. QAService 가 요청마다 `Tracer.start` 로 받는다."""

    @property
    def trace_id(self) -> str | None:
        """기록을 시작하지 못했으면 None."""
        ...

    def callbacks(self) -> list[BaseCallbackHandler]:
        """체인에 넘길 LangChain 콜백. 모델 호출 단계가 이 요청의 trace 아래에 붙는다."""
        ...

    def step(self, name: str, input: Any = None) -> TraceStep: ...

    def annotate(self, **metadata: Any) -> None:
        """요청 끝에 root 메타데이터로 합쳐질 값(호출 수·재생성 수·검증 실패 사유 등)."""
        ...

    def end(self, response: QueryResponse, final_context: Sequence[ContextItem]) -> None:
        """최종 응답을 기록하고 trace 를 닫는다. 열려 있는 단계도 함께 닫는다."""
        ...

    def abort(self) -> None:
        """응답 없이 끝날 때(취소 등) 열린 단계와 trace 를 닫는다."""
        ...


class Tracer(Protocol):
    def start(self, request_id: str, question: str, mode: RetrievalMode, **metadata: Any) -> RequestTrace: ...


# ── 요약 헬퍼: 무엇을 기록할지 한곳에서 정한다 ─────────────────────────
def summarize_retrieved(chunks: Sequence[RetrievedChunk]) -> dict[str, Any]:
    """검색 결과 요약. 본문은 넣지 않는다(실제 모델 입력에서 보인다). 순위·점수·chunk_id 와 위치만 남긴다."""
    return {
        "count": len(chunks),
        "results": [
            {
                "rank": c.rank,
                "score": c.score,
                "chunk_id": c.chunk.chunk_id,
                "book_id": c.chunk.book_id,
                "pages": [c.chunk.page_start, c.chunk.page_end],
            }
            for c in chunks
        ],
    }


def summarize_context(
    items: Sequence[ContextItem], dropped_chunk_ids: Sequence[str], before: int, after: int, token_count: int
) -> dict[str, Any]:
    """예산 적용 전후 문맥 요약. S 번호와 chunk_id 의 대응이 곧 final_context 다."""
    return {
        "count_before": before,
        "count_after": after,
        "token_count": token_count,
        "final_context": [{"source_id": i.source_id, "chunk_id": i.chunk.chunk_id} for i in items],
        "dropped_chunk_ids": list(dropped_chunk_ids),
    }


def summarize_history(count: int, max_turns: int) -> dict[str, Any]:
    """이전 대화 요약. 질문·답 본문은 넣지 않는다(실제 모델 입력에서 보인다)."""
    return {"count": count, "max_turns": max_turns}


def summarize_response(response: QueryResponse) -> dict[str, Any]:
    return {
        "status": response.status.value,
        "answer": response.answer,
        "reason": response.reason,
        "error_code": response.error_code.value if response.error_code else None,
        "citations": [
            {"source_id": c.source_id, "file_name": c.file_name, "page": c.page} for c in response.citations
        ],
    }


# ── 아무것도 하지 않는 구현 ───────────────────────────────────────────
class _NoopStep:
    def end(self, output: Any = None, *, error: str | None = None) -> None:
        return None


class NoopTrace:
    trace_id: str | None = None

    def callbacks(self) -> list[BaseCallbackHandler]:
        return []

    def step(self, name: str, input: Any = None) -> TraceStep:
        return _NoopStep()

    def annotate(self, **metadata: Any) -> None:
        return None

    def end(self, response: QueryResponse, final_context: Sequence[ContextItem]) -> None:
        return None

    def abort(self) -> None:
        return None


class NoopTracer:
    """키가 없거나 기록을 끈 때. trace_id 는 항상 None 이다."""

    def start(self, request_id: str, question: str, mode: RetrievalMode, **metadata: Any) -> RequestTrace:
        return NoopTrace()


# ── 장애 격리 ─────────────────────────────────────────────────────────
class _SafeStep:
    def __init__(self, inner: TraceStep | None) -> None:
        self._inner = inner

    def end(self, output: Any = None, *, error: str | None = None) -> None:
        if self._inner is None:
            return
        try:
            self._inner.end(output, error=error)
        except Exception:  # noqa: BLE001 - 기록 장애가 응답 실패가 되지 않게 한다
            logger.warning("트레이스 단계 종료 실패", exc_info=True)


class _SafeTrace:
    """안쪽 RequestTrace 의 모든 호출에서 난 예외를 잡는다. 실패하면 기본값(None·빈 목록)으로 돌아간다."""

    def __init__(self, inner: RequestTrace | None) -> None:
        self._inner = inner

    @property
    def trace_id(self) -> str | None:
        if self._inner is None:
            return None
        try:
            return self._inner.trace_id
        except Exception:  # noqa: BLE001
            return None

    def callbacks(self) -> list[BaseCallbackHandler]:
        if self._inner is None:
            return []
        try:
            return self._inner.callbacks()
        except Exception:  # noqa: BLE001
            logger.warning("트레이스 콜백을 만들지 못했다", exc_info=True)
            return []

    def step(self, name: str, input: Any = None) -> TraceStep:
        if self._inner is None:
            return _SafeStep(None)
        try:
            return _SafeStep(self._inner.step(name, input))
        except Exception:  # noqa: BLE001
            logger.warning("트레이스 단계 시작 실패 name=%s", name, exc_info=True)
            return _SafeStep(None)

    def annotate(self, **metadata: Any) -> None:
        if self._inner is None:
            return
        try:
            self._inner.annotate(**metadata)
        except Exception:  # noqa: BLE001
            logger.warning("트레이스 메타데이터 기록 실패", exc_info=True)

    def end(self, response: QueryResponse, final_context: Sequence[ContextItem]) -> None:
        if self._inner is None:
            return
        try:
            self._inner.end(response, final_context)
        except Exception:  # noqa: BLE001
            logger.warning("트레이스 종료 실패", exc_info=True)

    def abort(self) -> None:
        if self._inner is None:
            return
        try:
            self._inner.abort()
        except Exception:  # noqa: BLE001
            logger.warning("트레이스 중단 처리 실패", exc_info=True)


class _SafeTracer:
    def __init__(self, inner: Tracer) -> None:
        self._inner = inner

    def start(self, request_id: str, question: str, mode: RetrievalMode, **metadata: Any) -> RequestTrace:
        try:
            return _SafeTrace(self._inner.start(request_id, question, mode, **metadata))
        except Exception:  # noqa: BLE001
            logger.warning("트레이스를 시작하지 못했다 request_id=%s", request_id, exc_info=True)
            return _SafeTrace(None)

    def flush(self) -> None:
        """남은 기록을 보낸다(종료 시점·수동 확인용). 요청 경로에서는 부르지 않는다."""
        flush = getattr(self._inner, "flush", None)
        if flush is None:
            return
        try:
            flush()
        except Exception:  # noqa: BLE001
            logger.warning("Langfuse flush 실패", exc_info=True)


# ── 마스킹 ────────────────────────────────────────────────────────────
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_KEY_LIKE = re.compile(r"\b(?:sk|pk)-(?:lf-|proj-)?[A-Za-z0-9_-]{16,}")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ENVS = ("OPENAI_API_KEY", ENV_SECRET_KEY, ENV_PUBLIC_KEY)


def redact(text: str) -> str:
    """이메일과 키 모양 문자열, 환경에 설정된 키 값을 가린다. 정규식이 닿는 범위만 막는다."""
    out = _KEY_LIKE.sub("[SECRET]", _BEARER.sub("[SECRET]", _EMAIL.sub("[EMAIL]", text)))
    for name in _SECRET_ENVS:
        value = os.environ.get(name, "").strip()
        if len(value) >= 8:  # 너무 짧은 값은 일반 단어를 지울 수 있어 건너뛴다
            out = out.replace(value, "[SECRET]")
    return out


def _mask_spans(*, params: Any) -> Any:
    """Langfuse `mask_otel_spans` 콜백: 바뀐 문자열 속성만 patch 로 돌려준다(전송 직전에 적용된다)."""
    from langfuse import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        changed = {
            key: redact(value)
            for key, value in span.attributes.items()
            if isinstance(value, str) and redact(value) != value
        }
        if changed:
            patches[identifier] = OtelSpanPatch(set_attributes=changed)
    return MaskOtelSpansResult(span_patches=patches)


# ── Langfuse 구현 ─────────────────────────────────────────────────────
class _LangfuseStep:
    def __init__(self, span: Any) -> None:
        self._span = span
        self._ended = False

    def end(self, output: Any = None, *, error: str | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        if error is not None:
            self._span.update(output=output, level="ERROR", status_message=error)
        else:
            self._span.update(output=output)
        self._span.end()


class _LangfuseTrace:
    def __init__(self, root: Any, trace_id: str, public_key: str | None) -> None:
        self._root = root
        self._trace_id = trace_id
        self._public_key = public_key
        self._steps: list[_LangfuseStep] = []
        self._metadata: dict[str, Any] = {}
        self._closed = False

    @property
    def trace_id(self) -> str | None:
        return self._trace_id

    def callbacks(self) -> list[BaseCallbackHandler]:
        from langfuse.langchain import CallbackHandler

        # 컨텍스트 변수에 기대지 않고 부모를 명시해서, 같은 trace 의 root 아래에 모델 호출 단계가 붙게 한다.
        handler = CallbackHandler(
            public_key=self._public_key,
            trace_context={"trace_id": self._trace_id, "parent_span_id": self._root.id},
        )
        return [handler]

    def step(self, name: str, input: Any = None) -> TraceStep:
        step = _LangfuseStep(self._root.start_observation(name=name, as_type="span", input=input))
        self._steps.append(step)
        return step

    def annotate(self, **metadata: Any) -> None:
        self._metadata.update(metadata)

    def _close_steps(self, error: str | None) -> None:
        for step in self._steps:
            step.end(error=error)

    def end(self, response: QueryResponse, final_context: Sequence[ContextItem]) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_steps(error=None)
        meta = response.meta
        metadata = {
            **self._metadata,
            "status": response.status.value,
            "error_code": response.error_code.value if response.error_code else None,
            "retrieval_mode": meta.retrieval_mode.value,
            "latency_ms": meta.latency_ms,
            "input_tokens": meta.input_tokens,  # 모르면 None (0 아님)
            "output_tokens": meta.output_tokens,
            "final_context_chunk_ids": [i.chunk.chunk_id for i in final_context],
        }
        is_error = response.error_code is not None
        self._root.update(
            output=summarize_response(response),
            metadata=metadata,
            level="ERROR" if is_error else "DEFAULT",
            status_message=response.error_code.value if response.error_code else None,
        )
        self._root.end()

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_steps(error="aborted")
        self._root.update(level="WARNING", status_message="aborted", metadata=dict(self._metadata))
        self._root.end()


class LangfuseTracer:
    """Langfuse SDK 로 기록한다. 클라이언트는 주입받는다(테스트에서는 가짜를 넣는다)."""

    def __init__(self, client: Any, *, public_key: str | None = None) -> None:
        self._client = client
        self._public_key = public_key

    def start(self, request_id: str, question: str, mode: RetrievalMode, **metadata: Any) -> RequestTrace:
        trace_id = self._client.create_trace_id(seed=request_id)  # 같은 request_id 는 같은 trace
        root = self._client.start_observation(
            trace_context={"trace_id": trace_id},
            name=ROOT_NAME,
            as_type="span",
            input={"question": question},
            metadata={"request_id": request_id, "retrieval_mode": mode.value, **metadata},
        )
        return _LangfuseTrace(root, trace_id, self._public_key)

    def flush(self) -> None:
        self._client.flush()


def guard(tracer: Tracer) -> Tracer:
    """어떤 트레이서든 장애 격리 래퍼를 씌운다(이미 씌워져 있으면 그대로). 서비스는 주입받은 트레이서를 이걸로 감싼다."""
    return tracer if isinstance(tracer, _SafeTracer) else _SafeTracer(tracer)


def create_tracer(*, client: Any | None = None) -> Tracer:
    """환경변수 설정으로 트레이서를 만든다. 항상 장애 격리 래퍼를 씌워 돌려준다.

    - 공개·비밀 키가 둘 다 있고 `LANGFUSE_TRACING_ENABLED` 가 false 가 아니면 Langfuse 로 기록한다.
    - 아니거나 SDK 를 만들지 못하면 기록 없이 동작한다(경고 로그만 남긴다).
    - 주소는 SDK 가 `LANGFUSE_BASE_URL`(없으면 `LANGFUSE_HOST`)에서 읽는다.
    """
    if client is not None:
        return _SafeTracer(LangfuseTracer(client))
    public = os.environ.get(ENV_PUBLIC_KEY, "").strip()
    secret = os.environ.get(ENV_SECRET_KEY, "").strip()
    if not public or not secret or os.environ.get(ENV_TRACING_ENABLED, "true").strip().lower() == "false":
        return _SafeTracer(NoopTracer())
    try:
        from langfuse import Langfuse

        sdk = Langfuse(public_key=public, secret_key=secret, mask_otel_spans=_mask_spans)
        return _SafeTracer(LangfuseTracer(sdk, public_key=public))
    except Exception:  # noqa: BLE001 - 기록을 못 켜도 서비스는 떠야 한다
        logger.warning("Langfuse 를 초기화하지 못해 기록 없이 동작한다", exc_info=True)
        return _SafeTracer(NoopTracer())


__all__ = [
    "LangfuseTracer",
    "NoopTracer",
    "RequestTrace",
    "TraceStep",
    "Tracer",
    "create_tracer",
    "guard",
    "redact",
    "STEP_CACHE",
    "STEP_HISTORY",
    "STEP_SESSION",
    "summarize_context",
    "summarize_history",
    "summarize_response",
    "summarize_retrieved",
]
