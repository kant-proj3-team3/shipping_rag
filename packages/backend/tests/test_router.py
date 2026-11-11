"""I: 라우터를 **실제 QAService**(가짜 LLM·메모리 Redis)로 확인한다. 정상·검증 오류·근거 부족·모델 오류·세션·멀티턴을 HTTP 로 구분한다.

`test_backend_mock.py` 는 목업 서비스, 여기는 실제 `BackendQAService` 를 TestClient 로 부른다.
"""

import asyncio
import json
from datetime import UTC, datetime

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from backend.cache import RedisAnswerCache
from backend.chain import AnswerChain, ChainConfig
from backend.factory import create_real_qa_service, create_real_session_service
from backend.prompts import ModelOutput
from backend.router import build_router
from backend.session import PersistentSessionStore, RedisSessionStore, create_session_store
from backend.tracing import NoopTracer
from common.api import ERROR_HTTP_STATUS
from common.errors import IndexNotReadyError, InvalidInputError, RetrievalError
from common.types import (
    Chunk,
    ErrorCode,
    IndexManifest,
    RetrievalMode,
    RetrievalResult,
    RetrievedChunk,
    SessionInfo,
)

MANIFEST = IndexManifest(
    index_name="idx-test", embedder_id="embed-test", embedding_dim=4, document_count=1, chunk_count=1,
    fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
)
SID = "session-0001"


def _good(text: str = "무료기간은 3일입니다.") -> str:
    return json.dumps({"status": "answered", "answer": text, "reason": "표", "source_ids": ["S1"]}, ensure_ascii=False)


class ScriptedLLM(Runnable):
    """준비된 항목을 차례로 낸다(마지막은 반복). 문자열=정상 출력, None=읽을 수 없는 출력, 예외=호출 실패, 함수=느린 호출."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls: list = []

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        self.calls.append(messages)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            await item()
        if item is None or callable(item):
            return {"raw": AIMessage(content="JSON 이 아니다"), "parsed": None, "parsing_error": ValueError("x")}
        raw = AIMessage(content=item)
        raw.usage_metadata = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        return {"raw": raw, "parsed": ModelOutput.model_validate_json(item), "parsing_error": None}

    def user(self, call: int) -> str:
        return self.calls[call][1].content


class FakeRetriever:
    supported_modes = list(RetrievalMode)
    index = MANIFEST

    def __init__(self, chunks=None, exc=None):
        self.exc = exc
        self.chunks = chunks if chunks is not None else [
            Chunk(chunk_id="c1", book_id="IS01", file_name="IS01.pdf", page_start=4, page_end=4, text="무료기간은 3일이다.")
        ]
        self.requests = []

    async def retrieve(self, request, ctx):
        self.requests.append(request)
        if self.exc:
            raise self.exc
        return RetrievalResult(
            mode=request.mode, k=request.k, chunks=[RetrievedChunk(rank=i, score=1.0, chunk=c) for i, c in enumerate(self.chunks, 1)]
        )


class FakeDb:
    """`PostgresSessionStore` 와 같은 약속을 메모리에서 지킨다(실제 SQL 은 test_session_db.py 가 확인한다)."""

    def __init__(self):
        self.sessions: dict[str, list] = {}

    def append(self, session_id, turn):
        turns = self.sessions.setdefault(session_id, [])
        turns.append(turn)
        return len(turns)

    def get(self, session_id, limit):
        turns = self.sessions.get(session_id)
        if not turns:
            return None
        return SessionInfo(
            session_id=session_id, created_at=turns[0].asked_at, last_active_at=turns[-1].asked_at, expires_at=None,
            turn_count=len(turns), turns=turns[-limit:] if limit > 0 else [],
        )


def _store() -> PersistentSessionStore:
    """서비스가 실제로 쓰는 조합(DB 원본 + Redis 캐시). Redis 단독 저장소는 TTL 로 expires_at 을 계산하므로 계약과 다르다."""
    cache = RedisSessionStore(fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True), ttl_s=3600)
    return PersistentSessionStore(FakeDb(), cache)


def _make(*llm_items, retriever=None, timeout_s=1.0, raise_server_exceptions=True, cache=None):
    llm = ScriptedLLM(*(llm_items or (_good(),)))
    retriever = retriever or FakeRetriever()
    store = _store()
    qa = create_real_qa_service(
        retriever,
        chain=AnswerChain(llm, ChainConfig(timeout_s=timeout_s, max_retries=0)),
        store=store,  # type: ignore[arg-type]
        tracer=NoopTracer(),  # 개발자 환경에 Langfuse 키가 있어도 테스트가 기록을 보내지 않게 한다
        # 기본은 캐시 끔(None): 안 주면 환경변수를 따라 개발자 PC 의 실제 Redis 에 붙어 테스트끼리 같은 질문을 공유한다.
        cache=cache,
    )
    app = FastAPI()
    app.include_router(build_router(qa, create_real_session_service(store=store), MANIFEST))  # type: ignore[arg-type]
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), llm, retriever


# ── 정상 ──
def test_answered_response_has_code_filled_citations_and_meta():
    client, llm, _ = _make()
    res = client.post("/query", json={"question": "보관료 무료기간은?"})
    body = res.json()

    assert res.status_code == 200 and body["status"] == "answered" and body["error_code"] is None
    assert body["answer"] == "무료기간은 3일입니다."
    assert body["citations"] == [{"source_id": "S1", "book_id": "IS01", "file_name": "IS01.pdf", "page": 4}]  # 코드가 Chunk 에서 채운다
    assert body["request_id"]  # 서버가 만든다
    assert body["meta"]["input_tokens"] == 3 and body["meta"]["output_tokens"] == 2  # 확인된 값만
    assert body["meta"]["latency_ms"] is not None and body["meta"]["cache_hit"] is False
    assert body["meta"]["retrieval_mode"] == "hybrid"  # 요청에 없으면 서버 기본값


def test_final_context_is_never_exposed():
    client, _, _ = _make()
    assert "final_context" not in client.post("/query", json={"question": "질문"}).json()


def test_each_request_gets_its_own_request_id():
    client, _, _ = _make()
    ids = {client.post("/query", json={"question": "질문"}).json()["request_id"] for _ in range(3)}
    assert len(ids) == 3


def test_requested_retrieval_mode_is_used():
    client, _, retriever = _make()
    res = client.post("/query", json={"question": "질문", "retrieval_mode": "naive"})
    assert res.json()["meta"]["retrieval_mode"] == "naive" and retriever.requests[0].mode is RetrievalMode.NAIVE


# ── 요청 검증(422): 서비스까지 가지 않는다 ──
@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "가" * 501},
        {"question": "질문", "retrieval_mode": "banana"},
        {"question": "질문", "session_id": "짧음"},
        {"question": "질문", "session_id": "bad id!bad id!"},
        {},
    ],
)
def test_invalid_requests_are_422_and_never_reach_the_service(payload):
    client, llm, retriever = _make()
    assert client.post("/query", json=payload).status_code == 422
    assert llm.calls == [] and retriever.requests == []


# ── 근거 부족: 오류가 아니라 정상 응답(200) ──
def test_empty_retrieval_is_a_200_abstained_without_calling_the_model():
    client, llm, _ = _make(retriever=FakeRetriever(chunks=[]))
    res = client.post("/query", json={"question": "자료에 없는 질문"})
    body = res.json()
    assert res.status_code == 200 and body["status"] == "abstained" and body["error_code"] is None
    assert body["citations"] == [] and llm.calls == []  # 모델을 부르지 않았다


def test_needs_clarification_is_a_200():
    text = json.dumps(
        {"status": "needs_clarification", "answer": "기준일을 알려 주세요.", "reason": "기준일이 없다", "source_ids": []},
        ensure_ascii=False,
    )
    client, _, _ = _make(text)
    res = client.post("/query", json={"question": "보관료는?"})
    assert res.status_code == 200 and res.json()["status"] == "needs_clarification"


# ── 처리 실패: status=error 와 ERROR_HTTP_STATUS 의 HTTP 상태 ──
async def _slow():
    await asyncio.sleep(1)


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"llm": (RuntimeError("boom"),)}, ErrorCode.MODEL_FAILED),
        ({"llm": (_slow,), "timeout_s": 0.05}, ErrorCode.MODEL_TIMEOUT),
        ({"llm": (None,)}, ErrorCode.OUTPUT_INVALID),
        ({"llm": (_good(),), "retriever_exc": RetrievalError("x")}, ErrorCode.RETRIEVAL_FAILED),
        ({"llm": (_good(),), "retriever_exc": IndexNotReadyError("x")}, ErrorCode.INDEX_NOT_READY),
        ({"llm": (_good(),), "retriever_exc": InvalidInputError("x")}, ErrorCode.INVALID_INPUT),
        ({"llm": (_good(),), "retriever_exc": ValueError("예상 못 한 오류")}, ErrorCode.INTERNAL),
    ],
)
def test_failures_are_status_error_with_the_contract_http_status(kwargs, code):
    retriever = FakeRetriever(exc=kwargs["retriever_exc"]) if "retriever_exc" in kwargs else None
    client, _, _ = _make(*kwargs["llm"], retriever=retriever, timeout_s=kwargs.get("timeout_s", 1.0))
    res = client.post("/query", json={"question": "질문"})
    body = res.json()

    assert res.status_code == ERROR_HTTP_STATUS[code]
    assert body["status"] == "error" and body["error_code"] == code.value
    assert body["citations"] == []
    assert "boom" not in res.text and "예상 못 한 오류" not in res.text  # 내부 예외 메시지가 사용자 응답에 나가지 않는다


def test_a_failed_turn_is_not_recorded_in_the_session():
    client, _, _ = _make(RuntimeError("boom"))
    assert client.post("/query", json={"question": "질문", "session_id": SID}).status_code == 502
    assert client.get(f"/session/{SID}").status_code == 404  # error 는 기록하지 않는다


# ── 헬스 ──
def test_health_reports_the_index():
    client, _, _ = _make()
    body = client.get("/health").json()
    assert body["index_ready"] is True and body["index_name"] == "idx-test" and body["embedder_id"] == "embed-test"
    assert set(body["supported_modes"]) == {m.value for m in RetrievalMode}


# ── 세션 ──
def test_session_roundtrip_over_http():
    client, _, _ = _make(_good("답1"), _good("답2"))
    client.post("/query", json={"question": "질문1", "session_id": SID})
    client.post("/query", json={"question": "질문2", "session_id": SID})

    res = client.get(f"/session/{SID}")
    body = res.json()
    assert res.status_code == 200 and body["turn_count"] == 2 and body["expires_at"] is None
    assert [t["question"] for t in body["turns"]] == ["질문1", "질문2"]  # 오래된 것 → 최신
    assert client.get(f"/session/{SID}", params={"limit": 1}).json()["turns"][0]["question"] == "질문2"


def test_unknown_session_is_404_with_api_error():
    client, _, _ = _make()
    res = client.get("/session/session-9999")
    assert res.status_code == 404
    assert res.json() == {"error_code": "session_not_found", "message": "세션을 찾을 수 없습니다."}


@pytest.mark.parametrize("path", ["/session/short", "/session/session-0001?limit=0", "/session/session-0001?limit=101"])
def test_invalid_session_requests_are_422(path):
    client, _, _ = _make()
    assert client.get(path).status_code == 422


def test_session_read_failure_is_500_not_404():
    class Broken:
        def get(self, session_id, limit):
            raise ConnectionError("store down")

    app = FastAPI()
    qa = create_real_qa_service(FakeRetriever(), chain=object(), store=_store(), tracer=NoopTracer(), cache=None)  # type: ignore[arg-type]
    app.include_router(build_router(qa, create_real_session_service(store=Broken()), MANIFEST))  # type: ignore[arg-type]
    # "없음"(404)과 "조회 실패"를 섞지 않는다: 클라이언트가 세션이 사라졌다고 오해해 새 세션을 시작하지 않게
    assert TestClient(app, raise_server_exceptions=False).get(f"/session/{SID}").status_code == 500


def test_recorded_question_is_masked_in_the_session_read_back():
    client, _, _ = _make()
    client.post("/query", json={"question": "담당자 kim@example.com 에게 문의하면?", "session_id": SID})
    stored = client.get(f"/session/{SID}").json()["turns"][0]["question"]
    assert "kim@example.com" not in stored and "[EMAIL]" in stored


# ── 멀티턴(HTTP) ──
def test_follow_up_question_over_http_carries_the_previous_turn():
    client, llm, retriever = _make(_good("무료기간은 3일입니다."), _good("초과하면 하루 10,000원입니다."))
    client.post("/query", json={"question": "보관료 무료기간은?", "session_id": SID})
    res = client.post("/query", json={"question": "그럼 초과하면 하루에 얼마야?", "session_id": SID})

    assert res.status_code == 200 and res.json()["status"] == "answered"
    assert "[이전 대화]" not in llm.user(0)
    assert "질문: 보관료 무료기간은?\n답변: 무료기간은 3일입니다." in llm.user(1)
    assert retriever.requests[1].query == "그럼 초과하면 하루에 얼마야?"  # 검색은 원문 질문(알려진 한계)


def test_query_without_session_id_is_single_turn_and_records_nothing():
    client, llm, _ = _make(_good("답1"), _good("답2"))
    client.post("/query", json={"question": "질문1"})
    client.post("/query", json={"question": "질문2"})
    assert "[이전 대화]" not in llm.user(1)


# ── 답변 캐시(HTTP) ──
def _memory_cache():
    return RedisAnswerCache(fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True), ttl_s=60)


def test_repeated_question_is_served_from_the_cache_over_http():
    client, llm, retriever = _make(cache=_memory_cache())
    first = client.post("/query", json={"question": "보관료 무료기간은?"})
    second = client.post("/query", json={"question": "보관료 무료기간은?"})

    assert first.json()["meta"]["cache_hit"] is False and second.json()["meta"]["cache_hit"] is True
    assert len(llm.calls) == 1 and len(retriever.requests) == 1  # 적중하면 검색도 모델 호출도 하지 않는다
    a, b = first.json(), second.json()
    assert (b["status"], b["answer"], b["citations"]) == (a["status"], a["answer"], a["citations"])  # 같은 스키마
    assert b["request_id"] != a["request_id"] and b["meta"]["input_tokens"] is None  # 새 요청, 토큰은 None
    assert "final_context" not in b  # 적중해도 평가 입력은 응답에 내보내지 않는다


def test_a_failed_answer_is_not_cached_over_http():
    client, llm, _ = _make(RuntimeError("boom"), _good(), cache=_memory_cache())
    assert client.post("/query", json={"question": "질문"}).status_code == 502
    ok = client.post("/query", json={"question": "질문"})  # 같은 질문: 실패가 고정되지 않는다
    assert ok.status_code == 200 and ok.json()["meta"]["cache_hit"] is False


def test_cache_hit_still_records_the_turn_in_the_session_over_http():
    client, _, _ = _make(cache=_memory_cache())
    client.post("/query", json={"question": "질문", "session_id": "session-aaaa"})
    hit = client.post("/query", json={"question": "질문", "session_id": "session-bbbb"})  # 다른 세션의 같은 첫 질문

    assert hit.json()["meta"]["cache_hit"] is True
    assert client.get("/session/session-bbbb").json()["turn_count"] == 1  # 적중해도 대화 이력에는 남는다


# ── 조립 통로: 기본 세션 저장소 팩토리가 연결 없이 만들어진다 ──
def test_default_session_store_factory_does_not_connect():
    assert create_session_store() is not None
