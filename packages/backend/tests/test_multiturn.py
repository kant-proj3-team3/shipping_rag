"""G3: 멀티턴. QAService 가 같은 세션의 이전 대화를 프롬프트에 넣는지, 실패·끄기·재생성·트레이스까지 확인한다.

모델은 가짜(Runnable)이고 세션 저장소는 메모리 Redis(fakeredis)라서 외부 서비스가 필요 없다.
"""

import asyncio
import json
from datetime import UTC, datetime

import fakeredis
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from backend.chain import AnswerChain, ChainConfig
from backend.context import build_context
from backend.history import ENV_HISTORY_MAX_TURNS
from backend.prompts import HistoryTurn, ModelOutput
from backend.qa import BackendQAService
from backend.session import RedisSessionStore
from backend.validate import generate_validated
from common.types import (
    AnswerStatus,
    Chunk,
    QueryRequest,
    RequestContext,
    RetrievalMode,
    RetrievalResult,
    RetrievedChunk,
)

SID = "session-0001"


# ── 준비물 ──
def _answer(text: str, sources: tuple[str, ...] = ("S1",)) -> str:
    return json.dumps({"status": "answered", "answer": text, "reason": "표", "source_ids": list(sources)}, ensure_ascii=False)


class RecordingLLM(Runnable):
    """호출마다 받은 메시지를 기록하고, 준비된 응답을 차례로 돌려준다(마지막 응답은 계속 반복한다)."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: list[list] = []

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        self.calls.append(messages)
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        raw = AIMessage(content=text)
        raw.usage_metadata = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        return {"raw": raw, "parsed": ModelOutput.model_validate_json(text), "parsing_error": None}

    def system(self, call: int) -> str:
        return self.calls[call][0].content

    def user(self, call: int) -> str:
        return self.calls[call][1].content


class FakeRetriever:
    supported_modes = list(RetrievalMode)

    def __init__(self, chunks):
        self.chunks = chunks
        self.requests = []

    @property
    def index(self):
        raise NotImplementedError

    async def retrieve(self, request, ctx):
        self.requests.append(request)
        return RetrievalResult(mode=request.mode, k=request.k, chunks=self.chunks)


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        rank=1,
        score=1.0,
        chunk=Chunk(chunk_id="c1", book_id="IS01", file_name="IS01.pdf", page_start=1, page_end=1, text="무료기간은 3일이다."),
    )


def _store() -> RedisSessionStore:
    return RedisSessionStore(fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True), ttl_s=3600)


def _service(llm, store, *, history=True, tracer=None, retriever=None) -> BackendQAService:
    chain = AnswerChain(llm, ChainConfig(timeout_s=1.0, max_retries=0))
    return BackendQAService(
        retriever or FakeRetriever([_chunk()]), chain, store, history=store if history else None, tracer=tracer
    )


def _ask(service, question: str, session_id: str | None = SID):
    return asyncio.run(
        service.answer(QueryRequest(question=question, session_id=session_id), RequestContext(request_id="req-1"))
    )


# ── 이전 대화가 프롬프트에 들어간다 ──
def test_second_question_carries_the_previous_turn():
    llm = RecordingLLM(_answer("무료기간은 3일입니다."), _answer("초과하면 하루 10,000원입니다."))
    retriever = FakeRetriever([_chunk()])
    service = _service(llm, _store(), retriever=retriever)

    _ask(service, "보관료 무료기간은?")
    result = _ask(service, "그럼 초과하면 하루에 얼마야?")

    assert result.response.status is AnswerStatus.ANSWERED
    assert "[이전 대화]" not in llm.user(0) and "이전 대화 사용 규칙" not in llm.system(0)  # 첫 질문은 단발
    second = llm.user(1)
    assert "질문: 보관료 무료기간은?\n답변: 무료기간은 3일입니다." in second
    assert second.index("[이전 대화]") < second.index("[질문]") < second.index("[검색 자료]")
    assert "이전 대화 사용 규칙" in llm.system(1)
    # 검색은 여전히 원문 질문으로 한다(알려진 한계: 후속 질문의 검색은 이력의 도움을 받지 못한다)
    assert [r.query for r in retriever.requests] == ["보관료 무료기간은?", "그럼 초과하면 하루에 얼마야?"]
    # 이력은 검색 자료가 아니다: final_context 와 출처는 이번 요청의 문맥뿐이다
    assert [i.source_id for i in result.final_context] == ["S1"]
    assert [c.file_name for c in result.response.citations] == ["IS01.pdf"]


def test_clarification_flow_uses_the_clarifying_question_as_context():
    clarify = json.dumps(
        {"status": "needs_clarification", "answer": "어느 기준일로 계산할까요?", "reason": "기준일이 없다", "source_ids": []},
        ensure_ascii=False,
    )
    llm = RecordingLLM(clarify, _answer("2024년 3월 기준 3일입니다."))
    service = _service(llm, _store())

    first = _ask(service, "무료기간은?")
    _ask(service, "2024년 3월이요")

    assert first.response.status is AnswerStatus.NEEDS_CLARIFICATION
    assert "답변: 어느 기준일로 계산할까요?" in llm.user(1)  # 되물은 질문이 이전 대화로 들어간다


def test_turns_are_limited_to_the_most_recent(monkeypatch):
    monkeypatch.setenv(ENV_HISTORY_MAX_TURNS, "2")
    llm = RecordingLLM(*[_answer(f"답{n}") for n in range(1, 5)])
    service = _service(llm, _store())
    for n in range(1, 5):
        _ask(service, f"질문{n}")

    last = llm.user(3)
    assert "질문2" in last and "질문3" in last and "질문1" not in last


def test_masked_question_is_what_the_model_sees_in_history():
    llm = RecordingLLM(_answer("답1"), _answer("답2"))
    service = _service(llm, _store())
    _ask(service, "담당자 kim@example.com 에게 문의하면?")
    _ask(service, "그럼 언제까지?")
    assert "kim@example.com" not in llm.user(1) and "[EMAIL]" in llm.user(1)


# ── 이력을 쓰지 않는 경우 ──
def test_no_session_id_is_single_turn():
    llm = RecordingLLM(_answer("답"))
    service = _service(llm, _store())
    _ask(service, "질문", session_id=None)
    assert "[이전 대화]" not in llm.user(0)


def test_without_history_source_stays_single_turn_even_with_session_id():
    llm = RecordingLLM(_answer("답1"), _answer("답2"))
    service = _service(llm, _store(), history=False)
    _ask(service, "질문1")
    _ask(service, "질문2")
    assert "[이전 대화]" not in llm.user(1)


def test_turned_off_by_environment(monkeypatch):
    monkeypatch.setenv(ENV_HISTORY_MAX_TURNS, "0")
    llm = RecordingLLM(_answer("답1"), _answer("답2"))
    service = _service(llm, _store())
    _ask(service, "질문1")
    _ask(service, "질문2")
    assert "[이전 대화]" not in llm.user(1)


def test_other_sessions_history_is_not_used():
    llm = RecordingLLM(_answer("답1"), _answer("답2"))
    service = _service(llm, _store())
    _ask(service, "다른 대화의 질문", session_id="session-9999")
    _ask(service, "새 대화의 질문", session_id=SID)
    assert "다른 대화의 질문" not in llm.user(1)


# ── 장애 ──
class BrokenHistory:
    def get(self, session_id, limit):
        raise ConnectionError("db and redis down")


def test_history_read_failure_answers_single_turn_instead_of_failing(caplog):
    llm = RecordingLLM(_answer("답"))
    chain = AnswerChain(llm, ChainConfig(timeout_s=1.0, max_retries=0))
    service = BackendQAService(FakeRetriever([_chunk()]), chain, _store(), history=BrokenHistory())

    with caplog.at_level("WARNING"):
        result = _ask(service, "질문")

    assert result.response.status is AnswerStatus.ANSWERED  # 응답은 실패하지 않는다
    assert "[이전 대화]" not in llm.user(0)
    assert any("세션 이력을 읽지 못해" in r.message for r in caplog.records)


# ── 재생성 ──
def test_regeneration_keeps_the_same_history():
    llm = RecordingLLM(_answer("범위 밖 출처", sources=("S9",)), _answer("제대로 된 답"))
    chain = AnswerChain(llm, ChainConfig(timeout_s=1.0, max_retries=0, max_calls=3))
    context = build_context([_chunk()], max_tokens=1000)
    history = [HistoryTurn("앞선 질문", "앞선 답")]

    outcome = asyncio.run(generate_validated(chain, "질문", context, history=history, max_regen=1))

    assert outcome.ok and outcome.regenerations == 1 and outcome.calls == 2
    assert "질문: 앞선 질문\n답변: 앞선 답" in llm.user(0) and "질문: 앞선 질문\n답변: 앞선 답" in llm.user(1)


def test_history_cannot_make_an_out_of_context_source_valid():
    # 이전 답변이 S3 을 인용했더라도 이번 요청의 문맥(S1)에 없으면 거부한다. 검증은 이번 문맥만 기준이다.
    llm = RecordingLLM(_answer("이전 답을 믿고 인용", sources=("S3",)))
    chain = AnswerChain(llm, ChainConfig(timeout_s=1.0, max_retries=0, max_calls=1))
    context = build_context([_chunk()], max_tokens=1000)
    outcome = asyncio.run(
        generate_validated(chain, "질문", context, history=[HistoryTurn("앞선 질문", "S3 에 있다고 했다")], max_regen=0)
    )
    assert not outcome.ok and "S3" in (outcome.failure or "")


# ── 트레이스 ──
class FakeStep:
    def __init__(self, name, input):
        self.name, self.input, self.output, self.error = name, input, None, None

    def end(self, output=None, *, error=None):
        self.output, self.error = output, error


class FakeTrace:
    trace_id = "trace-1"

    def __init__(self):
        self.steps: list[FakeStep] = []
        self.annotations: dict = {}

    def callbacks(self):
        return []

    def step(self, name, input=None):
        step = FakeStep(name, input)
        self.steps.append(step)
        return step

    def annotate(self, **metadata):
        self.annotations.update(metadata)

    def end(self, response, final_context):
        pass

    def abort(self):
        pass


class FakeTracer:
    def __init__(self):
        self.traces: list[FakeTrace] = []

    def start(self, request_id, question, mode, **metadata):
        trace = FakeTrace()
        self.traces.append(trace)
        return trace


def test_trace_has_a_history_step_before_retrieval():
    tracer = FakeTracer()
    service = _service(RecordingLLM(_answer("답1"), _answer("답2")), _store(), tracer=tracer)
    _ask(service, "질문1")
    _ask(service, "질문2")

    first, second = tracer.traces
    assert [s.name for s in second.steps][:2] == ["load-history", "retrieve"]
    assert second.steps[0].output == {"count": 1, "max_turns": 3}  # 본문은 넣지 않고 개수만
    assert second.annotations["history_turns"] == 1
    assert first.steps[0].output == {"count": 0, "max_turns": 3}  # 첫 질문: 읽었지만 이력이 없다


def test_trace_marks_history_failure_without_failing_the_request():
    tracer = FakeTracer()
    chain = AnswerChain(RecordingLLM(_answer("답")), ChainConfig(timeout_s=1.0, max_retries=0))
    service = BackendQAService(FakeRetriever([_chunk()]), chain, _store(), history=BrokenHistory(), tracer=tracer)
    _ask(service, "질문")

    trace = tracer.traces[0]
    assert trace.steps[0].name == "load-history" and trace.steps[0].error == "history_unavailable"
    assert trace.annotations["history_error"] is True and trace.annotations["history_turns"] == 0


def test_no_history_step_when_there_is_no_session():
    tracer = FakeTracer()
    service = _service(RecordingLLM(_answer("답")), _store(), tracer=tracer)
    _ask(service, "질문", session_id=None)
    assert "load-history" not in [s.name for s in tracer.traces[0].steps]
