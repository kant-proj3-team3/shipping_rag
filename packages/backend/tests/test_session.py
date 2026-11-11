"""G: Redis 세션. 메모리 Redis(fakeredis)로 저장 구조·순서·만료·장애 격리를 확인한다(실제 Redis 서버는 쓰지 않는다)."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from backend.chain import AnswerChain, ChainConfig
from backend.prompts import ModelOutput
from backend.qa import BackendQAService
from backend.session import (
    ENV_REDIS_TIMEOUT,
    ENV_REDIS_URL,
    ENV_SESSION_MAX_TURNS,
    ENV_SESSION_TTL,
    KEY_PREFIX,
    RedisSessionService,
    RedisSessionStore,
    create_redis_session_store,
    session_max_turns,
    session_ttl_seconds,
)
from common.errors import RetrievalError
from common.interfaces import SessionService
from common.types import (
    AnswerStatus,
    Chunk,
    QueryRequest,
    RequestContext,
    RetrievalMode,
    RetrievalResult,
    RetrievedChunk,
    SessionTurn,
)

SID = "session-0001"
T0 = datetime(2026, 11, 9, 9, 0, 0, tzinfo=UTC)


# ── 준비물 ──
def _client(**kw):
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=kw.pop("decode_responses", True), **kw)


def _turn(n: int, status: AnswerStatus = AnswerStatus.ANSWERED) -> SessionTurn:
    return SessionTurn(
        request_id=f"req-{n}",
        asked_at=T0 + timedelta(minutes=n),
        question=f"질문 {n}",
        retrieval_mode=RetrievalMode.HYBRID,
        status=status,
        answer=f"답 {n}",
    )


def _store(client=None, **kw) -> RedisSessionStore:
    return RedisSessionStore(client if client is not None else _client(), ttl_s=kw.pop("ttl_s", 3600), **kw)


class FakeRetriever:
    supported_modes = list(RetrievalMode)

    def __init__(self, result):
        self.result = result

    @property
    def index(self):
        raise NotImplementedError

    async def retrieve(self, request, ctx):
        if isinstance(self.result, Exception):
            raise self.result
        return RetrievalResult(mode=request.mode, k=request.k, chunks=self.result)


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        rank=1,
        score=1.0,
        chunk=Chunk(chunk_id="c1", book_id="IS01", file_name="IS01.pdf", page_start=1, page_end=1, text="본문"),
    )


class FakeLLM(Runnable):
    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        text = json.dumps(
            {"status": "answered", "answer": "3일", "reason": "표", "source_ids": ["S1"]}, ensure_ascii=False
        )
        raw = AIMessage(content=text)
        raw.usage_metadata = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        return {"raw": raw, "parsed": ModelOutput.model_validate_json(text), "parsing_error": None}


def _service(retriever, store) -> BackendQAService:
    return BackendQAService(retriever, AnswerChain(FakeLLM(), ChainConfig(timeout_s=1.0, max_retries=0)), store)


def _ask(service, **kw):
    return asyncio.run(service.answer(QueryRequest(question="체선료는?", **kw), RequestContext(request_id="req-1")))


# ── 저장·조회 ──
def test_roundtrip_fields_order_and_counts():
    store = _store(ttl_s=600)
    for n in (1, 2, 3):
        store.append(SID, _turn(n))

    info = store.get(SID, 20)
    assert info is not None and info.session_id == SID
    assert [t.request_id for t in info.turns] == ["req-1", "req-2", "req-3"]  # 오래된 것 → 최신
    assert info.turn_count == 3
    assert info.created_at == T0 + timedelta(minutes=1)  # 첫 턴 시각
    assert info.last_active_at == T0 + timedelta(minutes=3)
    assert info.expires_at == info.last_active_at + timedelta(seconds=600)
    assert info.turns[0] == _turn(1)  # 저장했다 읽어도 같다


def test_limit_returns_most_recent_in_order_but_counts_all():
    store = _store()
    for n in range(1, 6):
        store.append(SID, _turn(n))

    info = store.get(SID, 2)
    assert [t.request_id for t in info.turns] == ["req-4", "req-5"]
    assert info.turn_count == 5


def test_limit_zero_returns_no_turns_but_keeps_count():
    store = _store()
    store.append(SID, _turn(1))
    info = store.get(SID, 0)
    assert info.turns == [] and info.turn_count == 1


def test_missing_session_is_none():
    assert _store().get("session-9999", 20) is None


def test_invalid_session_id_never_touches_redis():
    client = _client()
    store = _store(client)
    for bad in ("short", "has space 12345", "a:b:c:d:e:f:g:h", "x" * 129, "session-0001\n"):
        assert store.get(bad, 20) is None
        with pytest.raises(ValueError):
            store.append(bad, _turn(1))
    assert client.keys("*") == []


def test_keys_use_prefix_and_two_keys_per_session():
    client = _client()
    _store(client).append(SID, _turn(1))
    assert sorted(client.keys("*")) == [f"{KEY_PREFIX}{SID}:meta", f"{KEY_PREFIX}{SID}:turns"]


def test_sessions_are_isolated():
    store = _store()
    store.append("session-aaaa", _turn(1))
    store.append("session-bbbb", _turn(2))
    assert [t.request_id for t in store.get("session-aaaa", 20).turns] == ["req-1"]
    assert [t.request_id for t in store.get("session-bbbb", 20).turns] == ["req-2"]


def test_works_with_bytes_responses_client():
    store = _store(_client(decode_responses=False))
    store.append(SID, _turn(1))
    info = store.get(SID, 20)
    assert info.turn_count == 1 and info.turns[0].request_id == "req-1"


# ── 만료 ──
def test_every_key_has_ttl_and_append_refreshes_it():
    client = _client()
    store = _store(client, ttl_s=600)
    store.append(SID, _turn(1))
    meta, turns = f"{KEY_PREFIX}{SID}:meta", f"{KEY_PREFIX}{SID}:turns"
    assert 0 < client.ttl(meta) <= 600 and 0 < client.ttl(turns) <= 600

    client.expire(meta, 30)
    client.expire(turns, 30)
    store.append(SID, _turn(2))
    assert client.ttl(meta) > 30 and client.ttl(turns) > 30  # 마지막 활동 기준으로 다시 건다


def test_get_does_not_extend_ttl():
    client = _client()
    store = _store(client, ttl_s=600)
    store.append(SID, _turn(1))
    client.expire(f"{KEY_PREFIX}{SID}:meta", 30)
    client.expire(f"{KEY_PREFIX}{SID}:turns", 30)
    store.get(SID, 20)
    assert client.ttl(f"{KEY_PREFIX}{SID}:meta") <= 30
    assert client.ttl(f"{KEY_PREFIX}{SID}:turns") <= 30


def test_expired_session_is_none():
    client = _client()
    store = _store(client)
    store.append(SID, _turn(1))
    client.pexpire(f"{KEY_PREFIX}{SID}:meta", 1)
    client.pexpire(f"{KEY_PREFIX}{SID}:turns", 1)
    time.sleep(0.05)
    assert store.get(SID, 20) is None


def test_after_expiry_a_new_session_starts_from_zero():
    client = _client()
    store = _store(client)
    store.append(SID, _turn(1))
    client.delete(f"{KEY_PREFIX}{SID}:meta", f"{KEY_PREFIX}{SID}:turns")
    store.append(SID, _turn(2))
    info = store.get(SID, 20)
    assert info.turn_count == 1 and [t.request_id for t in info.turns] == ["req-2"]


# ── 보관 상한 ──
def test_max_turns_trims_old_turns_but_turn_count_stays_total():
    store = _store(max_turns=3)
    for n in range(1, 6):
        store.append(SID, _turn(n))
    info = store.get(SID, 20)
    assert [t.request_id for t in info.turns] == ["req-3", "req-4", "req-5"]
    assert info.turn_count == 5  # 전체 개수는 줄지 않는다
    assert info.created_at == T0 + timedelta(minutes=1)


def test_unreadable_turn_is_skipped_not_fatal():
    client = _client()
    store = _store(client)
    store.append(SID, _turn(1))
    client.rpush(f"{KEY_PREFIX}{SID}:turns", "{깨진 JSON")
    store.append(SID, _turn(2))
    info = store.get(SID, 20)
    assert [t.request_id for t in info.turns] == ["req-1", "req-2"]
    assert info.turn_count == 2


# ── 서비스 인터페이스 ──
def test_service_satisfies_protocol_and_reads_through_thread():
    store = _store()
    store.append(SID, _turn(1))
    service = RedisSessionService(store)
    assert isinstance(service, SessionService)
    info = asyncio.run(service.get(SID, 20))
    assert info is not None and info.turn_count == 1
    assert asyncio.run(service.get("session-9999")) is None


def test_get_failure_is_raised_not_turned_into_none():
    class Broken:
        def pipeline(self, **kw):
            raise ConnectionError("redis down")

    service = RedisSessionService(RedisSessionStore(Broken(), ttl_s=10))
    with pytest.raises(ConnectionError):  # "없음"(404)과 "조회 실패"를 섞지 않는다
        asyncio.run(service.get(SID, 20))


# ── QAService 와의 연결 ──
def test_qa_records_non_error_turns_and_skips_errors():
    store = _store()
    _ask(_service(FakeRetriever([_chunk()]), store), session_id=SID)  # answered
    _ask(_service(FakeRetriever([]), store), session_id=SID)  # abstained
    _ask(_service(FakeRetriever(RetrievalError("x")), store), session_id=SID)  # error

    info = store.get(SID, 20)
    assert info.turn_count == 2
    assert [t.status for t in info.turns] == [AnswerStatus.ANSWERED, AnswerStatus.ABSTAINED]
    assert info.turns[0].citations and info.turns[0].citations[0].file_name == "IS01.pdf"


def test_qa_stores_question_with_emails_and_keys_masked():
    # 영구 저장하므로 이메일·키 모양 문자열은 가려서 기록한다(계약 v0.1.1). 응답은 그대로다.
    store = _store()
    request = QueryRequest(
        question="담당자 kim@example.com 에게 체선료를 문의하면? 키는 sk-abcdefghijklmnopqrstuv 입니다.",
        session_id=SID,
    )
    result = asyncio.run(
        _service(FakeRetriever([_chunk()]), store).answer(request, RequestContext(request_id="req-1"))
    )
    assert result.response.status is AnswerStatus.ANSWERED
    stored = store.get(SID, 20).turns[0].question
    assert "kim@example.com" not in stored and "[EMAIL]" in stored
    assert "sk-abcdefghijklmnopqrstuv" not in stored and "[SECRET]" in stored
    assert "체선료를 문의하면" in stored  # 나머지 문장은 그대로


def test_qa_without_session_id_records_nothing():
    client = _client()
    _ask(_service(FakeRetriever([_chunk()]), _store(client)))
    assert client.keys("*") == []


def test_redis_down_does_not_fail_the_answer():
    class Broken:
        def pipeline(self, **kw):
            raise ConnectionError("redis down")

    svc = _service(FakeRetriever([_chunk()]), RedisSessionStore(Broken(), ttl_s=10))
    r = _ask(svc, session_id=SID).response
    assert r.status is AnswerStatus.ANSWERED and r.error_code is None


def test_slow_store_does_not_block_the_event_loop():
    class SlowStore:
        def append(self, session_id, turn):
            time.sleep(0.3)  # 멈춘 Redis 를 흉내 낸다

    svc = _service(FakeRetriever([_chunk()]), SlowStore())

    async def run():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        await svc.answer(QueryRequest(question="체선료는?", session_id=SID), RequestContext(request_id="req-1"))
        beat.cancel()
        return ticks

    assert asyncio.run(run()) >= 5  # 기록하는 0.3초 동안에도 다른 작업이 돈다


# ── 생성·설정 ──
def test_create_session_store_does_not_connect(monkeypatch):
    monkeypatch.setenv(ENV_REDIS_URL, "redis://127.0.0.1:1/0")  # 아무도 듣지 않는 포트
    monkeypatch.setenv(ENV_REDIS_TIMEOUT, "0.5")
    store = create_redis_session_store()  # 생성만으로는 실패하지 않는다(앱 기동이 Redis 를 기다리지 않는다)
    kwargs = store._client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 0.5 and kwargs["socket_connect_timeout"] == 0.5
    assert kwargs["decode_responses"] is True
    with pytest.raises(Exception):  # 첫 명령에서 실패한다
        store.get(SID, 20)


def test_create_session_store_accepts_injected_client():
    client = _client()
    store = create_redis_session_store(client=client)
    store.append(SID, _turn(1))
    assert store.get(SID, 20).turn_count == 1


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_invalid_env_falls_back_to_defaults(monkeypatch, raw):
    monkeypatch.setenv(ENV_SESSION_TTL, raw)
    monkeypatch.setenv(ENV_SESSION_MAX_TURNS, raw)
    assert session_ttl_seconds() == 24 * 60 * 60
    assert session_max_turns() == 200


def test_env_overrides(monkeypatch):
    monkeypatch.setenv(ENV_SESSION_TTL, "120")
    monkeypatch.setenv(ENV_SESSION_MAX_TURNS, "7")
    store = create_redis_session_store(client=_client())
    assert store._ttl_s == 120 and store._max_turns == 7
