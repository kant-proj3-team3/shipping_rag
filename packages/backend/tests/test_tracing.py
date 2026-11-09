import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

import backend.tracing as tracing
from backend.chain import AnswerChain, ChainConfig
from backend.context import ENV_CONTEXT_MAX_TOKENS
from backend.mock.session import InMemorySessionStore
from backend.prompts import ModelOutput
from backend.qa import BackendQAService
from backend.tracing import LangfuseTracer, NoopTracer, create_tracer, guard, redact
from common.errors import RetrievalError
from common.types import (
    AnswerStatus,
    Chunk,
    ErrorCode,
    IndexManifest,
    QueryRequest,
    RequestContext,
    RetrievalMode,
    RetrievalRequest,
    RetrievalResult,
    RetrievedChunk,
)


# ── 준비물(test_qa.py 와 같은 모양) ──
def _rc(n: int, text: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        rank=n,
        score=1.0 / n,
        chunk=Chunk(
            chunk_id=f"c{n}", book_id=f"IS0{n}", file_name=f"IS0{n}.pdf", page_start=n, page_end=n, text=text or f"본문 {n}"
        ),
    )


class FakeRetriever:
    supported_modes = list(RetrievalMode)

    def __init__(self, result: list[RetrievedChunk] | Exception):
        self.result = result

    @property
    def index(self) -> IndexManifest:
        raise NotImplementedError

    async def retrieve(self, request: RetrievalRequest, ctx: RequestContext) -> RetrievalResult:
        if isinstance(self.result, Exception):
            raise self.result
        return RetrievalResult(mode=request.mode, k=request.k, chunks=self.result)


def _msg(source_ids=("S1",), status="answered") -> dict:
    text = json.dumps({"status": status, "answer": "3일", "reason": "표 2", "source_ids": list(source_ids)}, ensure_ascii=False)
    raw = AIMessage(content=text)
    raw.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    return {"raw": raw, "parsed": ModelOutput.model_validate_json(text), "parsing_error": None}


class FakeLLM(Runnable):
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _service(retriever, llm, tracer, **kw):
    chain = AnswerChain(llm, ChainConfig(timeout_s=1.0, max_retries=0, max_calls=3))
    return BackendQAService(retriever, chain, InMemorySessionStore(), tracer=tracer, **kw)


def _ask(service, question="체선료 면제 기간은?"):
    return asyncio.run(service.answer(QueryRequest(question=question), RequestContext(request_id="req-1")))


# ── 기록을 모으는 가짜 트레이서 ──
class _Recorder:
    """RequestTrace 구현: 호출을 전부 기록한다. 콜백으로 sentinel 핸들러를 돌려줘 체인에 전달되는지 본다."""

    def __init__(self, trace_id: str | None = "trace-1"):
        self._trace_id = trace_id
        self.steps: dict[str, dict[str, Any]] = {}
        self.metadata: dict[str, Any] = {}
        self.ended: Any = None
        self.aborted = False
        self.handler = _NameHandler()

    @property
    def trace_id(self):
        return self._trace_id

    def callbacks(self):
        return [self.handler]

    def step(self, name, input=None):
        record = {"input": input, "output": None, "error": None, "ended": False}
        self.steps[name] = record

        class _S:
            def end(_, output=None, *, error=None):
                record.update(output=output, error=error, ended=True)

        return _S()

    def annotate(self, **metadata):
        self.metadata.update(metadata)

    def end(self, response, final_context):
        self.ended = (response, list(final_context))

    def abort(self):
        self.aborted = True


class _NameHandler(BaseCallbackHandler):
    """LangChain 이 시작한 단계 이름을 모은다(콜백이 체인까지 전달되는지 확인)."""

    def __init__(self):
        self.names: list[str] = []

    def on_chain_start(self, serialized, inputs, *, run_id, name=None, **kwargs):
        self.names.append(name or "")


class _Tracer:
    def __init__(self, trace: _Recorder):
        self.trace = trace
        self.started: list[tuple] = []

    def start(self, request_id, question, mode, **metadata):
        self.started.append((request_id, question, mode, metadata))
        return self.trace


# ── 정상 요청 ──
def test_answered_request_is_traced_with_retrieval_context_and_final_response():
    rec = _Recorder()
    tracer = _Tracer(rec)
    res = _ask(_service(FakeRetriever([_rc(1), _rc(2)]), FakeLLM(_msg(("S1", "S2"))), tracer))
    r = res.response

    assert tracer.started[0][:3] == ("req-1", "체선료 면제 기간은?", RetrievalMode.HYBRID)
    assert r.meta.trace_id == "trace-1"  # 성공하면 trace_id 가 채워진다
    # 검색 결과: 순위·점수·chunk_id
    retrieve = rec.steps["retrieve"]
    assert retrieve["ended"] and retrieve["error"] is None
    assert [(x["rank"], x["chunk_id"]) for x in retrieve["output"]["results"]] == [(1, "c1"), (2, "c2")]
    assert retrieve["output"]["results"][0]["score"] == pytest.approx(1.0)
    # 문맥: S번호↔chunk_id, 제외 없음
    ctx = rec.steps["build-context"]["output"]
    assert ctx["final_context"] == [{"source_id": "S1", "chunk_id": "c1"}, {"source_id": "S2", "chunk_id": "c2"}]
    assert ctx["dropped_chunk_ids"] == [] and (ctx["count_before"], ctx["count_after"]) == (2, 2)
    # 최종 응답과 호출 정보
    response, final_context = rec.ended
    assert response.request_id == "req-1" and [i.source_id for i in final_context] == ["S1", "S2"]
    assert rec.metadata["model_called"] is True and rec.metadata["model_calls"] == 1
    # 체인에 콜백이 전달돼 모델 호출 단계가 같은 trace 에 붙는다
    assert "generate-answer" in rec.handler.names
    assert not rec.aborted


def test_search_miss_and_context_drop_are_distinguishable(monkeypatch):
    # c1 은 예산 안, c2 는 검색됐지만 문맥 축소로 빠진다 → retrieve 에는 있고 final_context 에는 없다
    monkeypatch.setenv(ENV_CONTEXT_MAX_TOKENS, "80")
    rec = _Recorder()
    _ask(_service(FakeRetriever([_rc(1, text="a" * 10), _rc(2, text="b" * 500)]), FakeLLM(_msg()), _Tracer(rec)))
    retrieved_ids = [x["chunk_id"] for x in rec.steps["retrieve"]["output"]["results"]]
    ctx = rec.steps["build-context"]["output"]
    assert retrieved_ids == ["c1", "c2"]
    assert [x["chunk_id"] for x in ctx["final_context"]] == ["c1"]
    assert ctx["dropped_chunk_ids"] == ["c2"]


# ── abstained / error ──
def test_empty_retrieval_is_traced_without_model_call():
    rec = _Recorder()
    llm = FakeLLM()
    res = _ask(_service(FakeRetriever([]), llm, _Tracer(rec)))
    assert res.response.status is AnswerStatus.ABSTAINED and llm.calls == 0
    assert res.response.meta.trace_id == "trace-1"
    assert rec.steps["retrieve"]["output"]["count"] == 0
    assert rec.metadata["model_called"] is False
    assert rec.ended is not None and rec.ended[0].status is AnswerStatus.ABSTAINED


def test_retrieval_error_is_traced_and_step_marked_failed():
    rec = _Recorder()
    res = _ask(_service(FakeRetriever(RetrievalError("boom")), FakeLLM(), _Tracer(rec)))
    r = res.response
    assert r.status is AnswerStatus.ERROR and r.error_code is ErrorCode.RETRIEVAL_FAILED
    assert r.meta.trace_id == "trace-1"  # 오류 응답에도 trace_id 가 있어 추적할 수 있다
    assert rec.steps["retrieve"]["error"] == "retrieval_failed" and rec.steps["retrieve"]["ended"]
    assert "build-context" not in rec.steps
    assert rec.metadata["model_called"] is False
    assert rec.ended[0].error_code is ErrorCode.RETRIEVAL_FAILED


def test_model_failure_is_traced_as_model_called():
    rec = _Recorder()
    res = _ask(_service(FakeRetriever([_rc(1)]), FakeLLM(RuntimeError("sk-leak")), _Tracer(rec)))
    assert res.response.error_code is ErrorCode.MODEL_FAILED
    assert rec.metadata["model_called"] is True
    assert rec.ended[0].error_code is ErrorCode.MODEL_FAILED


def test_output_invalid_records_validation_failure_without_model_text():
    rec = _Recorder()
    bad = _msg(("S99",))
    res = _ask(_service(FakeRetriever([_rc(1)]), FakeLLM(bad, bad), _Tracer(rec)))
    assert res.response.error_code is ErrorCode.OUTPUT_INVALID
    assert rec.metadata["model_calls"] == 2 and rec.metadata["regenerations"] == 1
    assert "S99" in rec.metadata["validation_failure"]  # 짧은 사유만. 모델이 쓴 답변 본문은 없다
    assert "3일" not in rec.metadata["validation_failure"]


def test_cancellation_aborts_trace_and_propagates():
    class Hang:
        supported_modes = list(RetrievalMode)

        async def retrieve(self, request, ctx):
            raise asyncio.CancelledError

    rec = _Recorder()
    with pytest.raises(asyncio.CancelledError):
        _ask(_service(Hang(), FakeLLM(), _Tracer(rec)))
    assert rec.aborted and rec.ended is None


# ── 장애 격리 ──
class _ExplodingTrace:
    @property
    def trace_id(self):
        raise RuntimeError("trace_id boom")

    def callbacks(self):
        raise RuntimeError("callbacks boom")

    def step(self, name, input=None):
        raise RuntimeError("step boom")

    def annotate(self, **metadata):
        raise RuntimeError("annotate boom")

    def end(self, response, final_context):
        raise RuntimeError("end boom")

    def abort(self):
        raise RuntimeError("abort boom")


class _ExplodingTracer:
    def __init__(self, fail_start: bool):
        self.fail_start = fail_start

    def start(self, request_id, question, mode, **metadata):
        if self.fail_start:
            raise ConnectionError("langfuse down")
        return _ExplodingTrace()


@pytest.mark.parametrize("fail_start", [True, False])
def test_tracer_failures_do_not_break_the_response(fail_start):
    res = _ask(_service(FakeRetriever([_rc(1)]), FakeLLM(_msg()), _ExplodingTracer(fail_start)))
    assert res.response.status is AnswerStatus.ANSWERED and res.response.error_code is None
    assert res.response.meta.trace_id is None  # 기록하지 못했으면 None
    assert [c.source_id for c in res.response.citations] == ["S1"]


def test_tracer_failures_do_not_hide_error_responses():
    res = _ask(_service(FakeRetriever(RetrievalError("x")), FakeLLM(), _ExplodingTracer(False)))
    assert res.response.error_code is ErrorCode.RETRIEVAL_FAILED


def test_default_service_has_no_tracing():
    res = _ask(_service(FakeRetriever([_rc(1)]), FakeLLM(_msg()), None))
    assert res.response.meta.trace_id is None and res.response.status is AnswerStatus.ANSWERED


def test_guard_is_idempotent():
    g = guard(NoopTracer())
    assert guard(g) is g


# ── create_tracer ──
def test_create_tracer_without_keys_is_noop(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    trace = create_tracer().start("req-1", "q", RetrievalMode.HYBRID)
    assert trace.trace_id is None and trace.callbacks() == []


def test_create_tracer_respects_disable_flag(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    assert create_tracer().start("req-1", "q", RetrievalMode.HYBRID).trace_id is None


def test_create_tracer_survives_sdk_init_failure(monkeypatch):
    import langfuse

    def boom(*a, **k):
        raise ValueError("bad config")

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-aaaaaaaaaaaaaaaa")
    monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)
    monkeypatch.setattr(langfuse, "Langfuse", boom)
    assert create_tracer().start("req-1", "q", RetrievalMode.HYBRID).trace_id is None


# ── 마스킹 ──
def test_redact_masks_email_and_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "my-custom-secret-value")
    text = "a.b@example.com sk-proj-abcdefghijklmnop0123 pk-lf-0123456789abcdef Bearer abcdefgh12345 my-custom-secret-value 체선료"
    out = redact(text)
    for leaked in ("a.b@example.com", "abcdefghijklmnop0123", "0123456789abcdef", "abcdefgh12345", "my-custom-secret-value"):
        assert leaked not in out
    assert "체선료" in out and "[EMAIL]" in out


def test_mask_spans_returns_patches_only_for_changed_attributes():
    spans = {
        "a": SimpleNamespace(attributes={"input": "문의 demo@example.com", "n": 1, "clean": "ok"}),
        "b": SimpleNamespace(attributes={"input": "no secrets"}),
    }
    result = tracing._mask_spans(params=SimpleNamespace(spans=spans))
    assert set(result.span_patches) == {"a"}
    assert result.span_patches["a"].set_attributes == {"input": "문의 [EMAIL]"}


# ── 실제 Langfuse SDK 를 메모리 exporter 에 연결해 호출 형태를 확인(네트워크 없음) ──
@pytest.fixture
def real_sdk():
    import uuid

    from langfuse import Langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    # SDK 는 public key 별로 리소스(tracer provider·exporter)를 하나만 두고 재사용한다. 테스트마다 키를 달리해야
    # 앞 테스트의 exporter 로 span 이 새지 않는다.
    public = f"pk-lf-{uuid.uuid4().hex}"
    client = Langfuse(
        public_key=public,
        secret_key=f"sk-lf-{uuid.uuid4().hex}",
        base_url="http://127.0.0.1:9",
        span_exporter=exporter,
        mask_otel_spans=tracing._mask_spans,
    )
    client.test_public_key = public  # type: ignore[attr-defined]
    yield client, exporter
    # shutdown() 은 서버 연결을 기다릴 수 있어 부르지 않는다(요청 경로에서도 flush 를 부르지 않는다)


def _spans(client, exporter):
    client._resources.tracer_provider.force_flush(5000)
    return {s.name: s for s in exporter.get_finished_spans()}


def test_real_sdk_groups_steps_and_model_calls_under_one_trace(real_sdk):
    client, exporter = real_sdk
    tracer = guard(LangfuseTracer(client, public_key=client.test_public_key))
    svc = _service(FakeRetriever([_rc(1)]), FakeLLM(_msg()), tracer)
    res = _ask(svc, question="문의 demo@example.com 체선료?")

    spans = _spans(client, exporter)
    root = spans["qa-query"]
    trace_hex = format(root.context.trace_id, "032x")
    assert res.response.meta.trace_id == trace_hex == client.create_trace_id(seed="req-1")  # request_id 로 찾는다
    for name in ("retrieve", "build-context", "generate-answer"):
        assert format(spans[name].context.trace_id, "032x") == trace_hex  # 한 trace 에 모인다
        assert spans[name].parent.span_id == root.context.span_id  # root 아래에 붙는다
    attrs = dict(root.attributes)
    assert json.loads(attrs["langfuse.observation.metadata.request_id"]) == "req-1"
    assert "[EMAIL]" in attrs["langfuse.observation.input"] and "demo@example.com" not in attrs["langfuse.observation.input"]
    output = json.loads(attrs["langfuse.observation.output"])
    assert output["status"] == "answered" and output["citations"][0]["source_id"] == "S1"


def test_real_sdk_error_request_is_marked_error_level(real_sdk):
    client, exporter = real_sdk
    tracer = guard(LangfuseTracer(client, public_key=client.test_public_key))
    res = _ask(_service(FakeRetriever(RetrievalError("x")), FakeLLM(), tracer))
    spans = _spans(client, exporter)
    assert dict(spans["qa-query"].attributes)["langfuse.observation.level"] == "ERROR"
    assert dict(spans["retrieve"].attributes)["langfuse.observation.level"] == "ERROR"
    assert res.response.meta.trace_id is not None
