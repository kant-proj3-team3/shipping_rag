import asyncio
import json
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from backend.chain import AnswerChain, ChainConfig, ModelCallError, ModelTimeoutError
from backend.context import ENV_CONTEXT_MAX_TOKENS
from backend.mock.session import InMemorySessionStore
from backend.prompts import ModelOutput
from backend.qa import BackendQAService, error_code_for
from common.errors import ContractError, IndexNotReadyError, IngestError, InvalidInputError, RetrievalError
from common.interfaces import QAService
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


# ── 준비물 ──
def _rc(n: int, *, ps: int = 1, pe: int | None = None, text: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        rank=n,
        score=1.0 / n,
        chunk=Chunk(
            chunk_id=f"c{n}",
            book_id=f"IS0{n}",
            file_name=f"IS0{n}.pdf",
            page_start=ps,
            page_end=pe if pe is not None else ps,
            text=text or f"본문 {n}",
        ),
    )


class FakeRetriever:
    """결과 목록 또는 던질 예외를 돌려주는 가짜 검색기. 받은 요청을 기록한다."""

    supported_modes = list(RetrievalMode)

    def __init__(self, result: list[RetrievedChunk] | Exception):
        self.result = result
        self.requests: list[RetrievalRequest] = []

    @property
    def index(self) -> IndexManifest:  # QAService 는 쓰지 않는다
        raise NotImplementedError

    async def retrieve(self, request: RetrievalRequest, ctx: RequestContext) -> RetrievalResult:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return RetrievalResult(mode=request.mode, k=request.k, chunks=self.result)


def _json(status="answered", source_ids=("S1",), answer="3일", reason="표 2") -> str:
    return json.dumps(
        {"status": status, "answer": answer, "reason": reason, "source_ids": list(source_ids)}, ensure_ascii=False
    )


def _msg(text: str, usage: tuple[int, int] | None = (10, 5)) -> dict:
    raw = AIMessage(content=text)
    if usage is not None:
        raw.usage_metadata = {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)}
    try:
        return {"raw": raw, "parsed": ModelOutput.model_validate_json(text), "parsing_error": None}
    except ValidationError as e:
        return {"raw": raw, "parsed": None, "parsing_error": e}


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


def _service(retriever, llm, store=None, **kw):
    cfg = ChainConfig(timeout_s=1.0, max_retries=0, max_calls=3)
    store = store if store is not None else InMemorySessionStore()
    return BackendQAService(retriever, AnswerChain(llm, cfg), store, **kw), store


def _ask(service, question="체선료 면제 기간은?", **kw):
    return asyncio.run(service.answer(QueryRequest(question=question, **kw), RequestContext(request_id="req-1")))


# ── 정상 / 되묻기 / 보류 ──
def test_answered_has_code_built_citations_and_final_context():
    llm = FakeLLM(_msg(_json(source_ids=("S1", "S2"))))
    svc, _ = _service(FakeRetriever([_rc(1), _rc(2, ps=3, pe=4)]), llm)
    res = _ask(svc)
    r = res.response
    assert r.status is AnswerStatus.ANSWERED and r.error_code is None
    assert [(c.source_id, c.file_name, c.page) for c in r.citations] == [
        ("S1", "IS01.pdf", 1),
        ("S2", "IS02.pdf", 3),
        ("S2", "IS02.pdf", 4),
    ]
    assert [i.source_id for i in res.final_context] == ["S1", "S2"]
    assert r.request_id == "req-1"
    assert r.meta.input_tokens == 10 and r.meta.output_tokens == 5
    assert r.meta.latency_ms is not None and r.meta.trace_id is None and r.meta.cost_usd is None


def test_needs_clarification_is_passed_through():
    llm = FakeLLM(_msg(_json(status="needs_clarification", source_ids=(), answer="어느 선박인가요?")))
    res = _ask(_service(FakeRetriever([_rc(1)]), llm)[0])
    assert res.response.status is AnswerStatus.NEEDS_CLARIFICATION
    assert res.response.answer == "어느 선박인가요?" and res.response.citations == []


def test_model_abstained_is_not_an_error():
    llm = FakeLLM(_msg(_json(status="abstained", source_ids=(), answer="근거 부족")))
    res = _ask(_service(FakeRetriever([_rc(1)]), llm)[0])
    assert res.response.status is AnswerStatus.ABSTAINED and res.response.error_code is None
    assert [i.source_id for i in res.final_context] == ["S1"]  # 모델에 전달한 문맥은 그대로 남긴다


def test_default_mode_and_k_and_request_mode():
    retr = FakeRetriever([_rc(1)])
    svc, _ = _service(retr, FakeLLM(_msg(_json()), _msg(_json())), k=7)
    _ask(svc)
    _ask(svc, retrieval_mode=RetrievalMode.NAIVE)
    assert [(q.mode, q.k) for q in retr.requests] == [(RetrievalMode.HYBRID, 7), (RetrievalMode.NAIVE, 7)]
    assert all(q.query == "체선료 면제 기간은?" for q in retr.requests)  # 서비스에는 질문만 전달한다


# ── 빈 문맥 ──
def test_empty_retrieval_abstains_without_calling_model():
    llm = FakeLLM()
    res = _ask(_service(FakeRetriever([]), llm)[0])
    assert res.response.status is AnswerStatus.ABSTAINED and res.response.error_code is None
    assert llm.calls == 0 and res.final_context == []
    assert res.response.meta.latency_ms is not None
    assert res.response.meta.input_tokens is None  # 호출하지 않았으므로 0 이 아니라 None


def test_context_budget_dropping_everything_abstains_without_calling_model(monkeypatch):
    monkeypatch.setenv(ENV_CONTEXT_MAX_TOKENS, "5")  # 첫 청크 블록도 못 담는 예산
    llm = FakeLLM()
    res = _ask(_service(FakeRetriever([_rc(1, text="x" * 100)]), llm)[0])
    assert res.response.status is AnswerStatus.ABSTAINED
    assert llm.calls == 0 and res.final_context == []


# ── 오류 매핑 ──
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (InvalidInputError("secret-key-123"), ErrorCode.INVALID_INPUT),
        (IndexNotReadyError("http://qdrant:6333"), ErrorCode.INDEX_NOT_READY),
        (RetrievalError("boom"), ErrorCode.RETRIEVAL_FAILED),
        (ContractError("x"), ErrorCode.INTERNAL),
        (IngestError("x"), ErrorCode.INTERNAL),  # ingest_failed 는 API 응답에 쓰지 않는다
        (RuntimeError("Traceback sk-abc"), ErrorCode.INTERNAL),
    ],
)
def test_retrieval_exceptions_map_to_error_codes(exc, code):
    llm = FakeLLM()
    res = _ask(_service(FakeRetriever(exc), llm)[0])
    r = res.response
    assert r.status is AnswerStatus.ERROR and r.error_code is code
    assert llm.calls == 0 and r.meta.latency_ms is not None
    # 사용자 문구에 예외 메시지가 새지 않는다
    for secret in ("secret-key-123", "qdrant:6333", "Traceback", "sk-abc", "boom"):
        assert secret not in r.answer and secret not in r.reason


@pytest.mark.parametrize(
    ("exc", "code"),
    [(asyncio.TimeoutError(), ErrorCode.MODEL_TIMEOUT), (RuntimeError("sk-leak"), ErrorCode.MODEL_FAILED)],
)
def test_model_failures_map_to_error_codes(exc, code):
    llm = FakeLLM(exc)
    res = _ask(_service(FakeRetriever([_rc(1)]), llm)[0])
    r = res.response
    assert r.status is AnswerStatus.ERROR and r.error_code is code
    assert "sk-leak" not in r.answer + r.reason
    assert r.meta.latency_ms is not None
    assert r.meta.input_tokens is None and r.meta.output_tokens is None  # 사용량 미확인은 None


def test_error_code_for_chain_exceptions():
    assert error_code_for(ModelTimeoutError()) is ErrorCode.MODEL_TIMEOUT
    assert error_code_for(ModelCallError()) is ErrorCode.MODEL_FAILED


def test_invalid_output_after_regeneration_limit(monkeypatch):
    monkeypatch.setenv("OUTPUT_MAX_REGENERATIONS", "1")
    bad = _msg(_json(source_ids=("S99",), answer="비밀 답변 본문"))
    llm = FakeLLM(bad, bad)
    res = _ask(_service(FakeRetriever([_rc(1)]), llm)[0])
    r = res.response
    assert r.status is AnswerStatus.ERROR and r.error_code is ErrorCode.OUTPUT_INVALID
    assert llm.calls == 2  # 첫 생성 + 재생성 1회
    assert "비밀 답변 본문" not in r.answer + r.reason  # 모델 원문을 사용자 문구에 넣지 않는다
    assert r.meta.input_tokens == 20 and r.meta.output_tokens == 10  # 확인된 토큰은 합산해 남긴다
    assert [i.source_id for i in res.final_context] == ["S1"]


def test_unreadable_output_is_output_invalid():
    unreadable = _msg("not json")
    llm = FakeLLM(unreadable, unreadable)
    res = _ask(_service(FakeRetriever([_rc(1)]), llm)[0])
    assert res.response.error_code is ErrorCode.OUTPUT_INVALID


def test_regeneration_recovers_and_sums_tokens(monkeypatch):
    monkeypatch.setenv("OUTPUT_MAX_REGENERATIONS", "1")
    llm = FakeLLM(_msg(_json(source_ids=("S9",))), _msg(_json(source_ids=("S1",))))
    r = _ask(_service(FakeRetriever([_rc(1)]), llm)[0]).response
    assert r.status is AnswerStatus.ANSWERED
    assert r.meta.input_tokens == 20 and r.meta.output_tokens == 10


def test_unknown_usage_stays_none_not_zero():
    llm = FakeLLM(_msg(_json(), usage=None))
    r = _ask(_service(FakeRetriever([_rc(1)]), llm)[0]).response
    assert r.status is AnswerStatus.ANSWERED
    assert r.meta.input_tokens is None and r.meta.output_tokens is None


def test_model_output_cannot_choose_error_status():
    # 모델이 error 를 골라도 스키마가 거부하므로 응답의 error 는 코드가 만든 것뿐이다.
    llm = FakeLLM(_msg(_json(status="error", source_ids=())), _msg(_json(status="error", source_ids=())))
    r = _ask(_service(FakeRetriever([_rc(1)]), llm)[0]).response
    assert r.status is AnswerStatus.ERROR and r.error_code is ErrorCode.OUTPUT_INVALID


# ── 세션 기록 ──
def test_session_records_non_error_only():
    store = InMemorySessionStore()
    sid = "session-0001"
    ok, _ = _service(FakeRetriever([_rc(1)]), FakeLLM(_msg(_json())), store)
    _ask(ok, session_id=sid)
    empty, _ = _service(FakeRetriever([]), FakeLLM(), store)
    _ask(empty, session_id=sid)
    broken, _ = _service(FakeRetriever(RetrievalError("x")), FakeLLM(), store)
    _ask(broken, session_id=sid)

    info = store.get(sid, 20)
    assert info is not None and info.turn_count == 2  # error 는 기록하지 않는다
    assert [t.status for t in info.turns] == [AnswerStatus.ANSWERED, AnswerStatus.ABSTAINED]
    assert isinstance(info.turns[0].asked_at, datetime)


def test_no_session_id_records_nothing():
    svc, store = _service(FakeRetriever([_rc(1)]), FakeLLM(_msg(_json())))
    _ask(svc)
    assert store.get("session-0001", 20) is None


def test_session_store_failure_does_not_fail_the_answer():
    class BrokenStore:
        def append(self, session_id, turn):
            raise ConnectionError("redis down")

    svc = BackendQAService(
        FakeRetriever([_rc(1)]), AnswerChain(FakeLLM(_msg(_json())), ChainConfig(max_retries=0)), BrokenStore()
    )
    r = _ask(svc, session_id="session-0001").response
    assert r.status is AnswerStatus.ANSWERED


# ── 인터페이스 ──
def test_satisfies_qaservice_protocol():
    svc, _ = _service(FakeRetriever([]), FakeLLM())
    assert isinstance(svc, QAService)
