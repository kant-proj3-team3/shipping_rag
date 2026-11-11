"""I: 진입점(`create_*`)의 목업/실제 전환과 실제 구현 조립(factory.py).

외부 서비스(OpenAI·PostgreSQL·Redis·Langfuse)에 연결하지 않는다. 연결은 첫 사용 때 만들어지므로 조립만으로는 실패하지 않아야 한다.
"""

import logging
import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend
from backend.cache import RedisAnswerCache
from backend.chain import AnswerChain, ModelCallError
from backend.factory import (
    LazyAnswerChain,
    create_real_qa_service,
    create_real_session_service,
    shared_session_store,
)
from backend.mock import MockAnswerEvaluator, MockQAService, MockSessionService
from backend.qa import BackendQAService
from backend.session import PersistentSessionStore, SessionQueryService
from common.types import Chunk, IndexManifest, RetrievalMode, RetrievalResult, RetrievedChunk

MANIFEST = IndexManifest(
    index_name="t", embedder_id="e", embedding_dim=4, document_count=1, chunk_count=1,
    fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
)


class FakeRetriever:
    supported_modes = list(RetrievalMode)
    index = MANIFEST

    async def retrieve(self, request, ctx):
        chunk = Chunk(chunk_id="c1", book_id="B1", file_name="B1.pdf", page_start=1, page_end=1, text="본문")
        return RetrievalResult(mode=request.mode, k=request.k, chunks=[RetrievedChunk(rank=1, score=1.0, chunk=chunk)])


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # 개발자의 환경변수(키·실제 서버)가 테스트에 끼지 않게 한다
    for name in ("BACKEND_IMPL", "OPENAI_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    # 답변 캐시는 기본 켜짐이라 안 끄면 개발자 PC 의 실제 Redis 에 붙는다. 캐시 연결을 확인하는 테스트만 따로 켠다.
    monkeypatch.setenv("CACHE_ENABLED", "false")
    shared_session_store.cache_clear()
    yield
    shared_session_store.cache_clear()


# ── 전환 ──
@pytest.mark.parametrize("raw", [None, "", "mock", " MOCK ", "banana"])
def test_default_and_unknown_values_give_mocks(monkeypatch, raw):
    if raw is not None:
        monkeypatch.setenv("BACKEND_IMPL", raw)
    assert isinstance(backend.create_qa_service(FakeRetriever()), MockQAService)
    assert isinstance(backend.create_session_service(), MockSessionService)


@pytest.mark.parametrize("raw", ["real", " Real "])
def test_real_gives_real_services(monkeypatch, raw):
    monkeypatch.setenv("BACKEND_IMPL", raw)
    assert isinstance(backend.create_qa_service(FakeRetriever()), BackendQAService)
    assert isinstance(backend.create_session_service(), SessionQueryService)


def test_answer_evaluator_stays_mock_until_stage_j(monkeypatch):
    monkeypatch.setenv("BACKEND_IMPL", "real")
    assert isinstance(backend.create_answer_evaluator(None), MockAnswerEvaluator)


# ── 세션 저장소 공유 ──
def test_qa_and_session_services_share_one_store_and_history_reads_from_it(monkeypatch):
    monkeypatch.setenv("BACKEND_IMPL", "real")
    qa = backend.create_qa_service(FakeRetriever())
    session = backend.create_session_service()

    assert qa._sessions is session._store is shared_session_store()  # 연결·풀이 두 벌이 되지 않는다
    assert qa._history is qa._sessions  # 멀티턴: 기록하는 저장소에서 이전 대화를 읽는다
    assert isinstance(qa._sessions, PersistentSessionStore)


def test_shared_store_is_created_once():
    assert shared_session_store() is shared_session_store()


def test_injected_parts_are_used_instead_of_the_shared_store():
    store = object()
    qa = create_real_qa_service(FakeRetriever(), chain=object(), store=store, tracer=object())  # type: ignore[arg-type]
    assert qa._sessions is store and qa._history is store
    assert create_real_session_service(store=store)._store is store  # type: ignore[arg-type]


# ── 모델 클라이언트는 시작 때 미리 만든다(warm-up) ──
def test_real_service_builds_the_model_client_at_startup_not_on_the_first_request(monkeypatch):
    built = []

    def fake_create(llm=None, config=None):
        built.append(1)
        return object()

    monkeypatch.setattr("backend.factory.create_answer_chain", fake_create)
    qa = create_real_qa_service(FakeRetriever(), store=object(), tracer=object())  # type: ignore[arg-type]

    assert built == [1]  # 서비스를 만들 때 이미 만들었다(첫 요청이 약 0.75초를 치르지 않는다)
    qa._chain._get()
    assert built == [1]  # 요청 때 다시 만들지 않는다


def test_warm_up_failure_does_not_stop_the_app_and_is_retried_on_the_first_request(monkeypatch, caplog):
    calls = []

    def fake_create(llm=None, config=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("no key")
        return object()

    monkeypatch.setattr("backend.factory.create_answer_chain", fake_create)
    with caplog.at_level(logging.WARNING):
        qa = create_real_qa_service(FakeRetriever(), store=object(), tracer=object())  # type: ignore[arg-type]  # 예외 없이 만들어진다

    assert any("미리 만들지 못했다" in r.message for r in caplog.records)
    assert qa._chain._chain is None  # 아직 없다
    assert qa._chain._get() is not None and len(calls) == 2  # 첫 요청 때 다시 시도해 만들어진다


def test_warm_up_reports_whether_it_worked():
    ok = LazyAnswerChain(build=lambda cfg: object())
    assert ok.warm_up() is True and ok._chain is not None

    def boom(cfg):
        raise RuntimeError("no key")

    assert LazyAnswerChain(build=boom).warm_up() is False


def test_an_injected_chain_is_not_warmed_up_or_replaced():
    chain = object()
    qa = create_real_qa_service(FakeRetriever(), chain=chain, store=object(), tracer=object())  # type: ignore[arg-type]
    assert qa._chain is chain


# ── 답변 캐시(H) 연결 ──
def test_real_service_wires_the_answer_cache_when_enabled(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    qa = create_real_qa_service(FakeRetriever(), chain=object(), store=object(), tracer=object())  # type: ignore[arg-type]
    assert isinstance(qa._cache, RedisAnswerCache)


def test_real_service_wires_the_answer_cache_by_default(monkeypatch):
    monkeypatch.delenv("CACHE_ENABLED", raising=False)  # 기본은 켜짐
    qa = create_real_qa_service(FakeRetriever(), chain=object(), store=object(), tracer=object())  # type: ignore[arg-type]
    assert isinstance(qa._cache, RedisAnswerCache)


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", " FALSE "])
def test_cache_is_off_when_disabled_by_environment(monkeypatch, raw):
    monkeypatch.setenv("CACHE_ENABLED", raw)
    qa = create_real_qa_service(FakeRetriever(), chain=object(), store=object(), tracer=object())  # type: ignore[arg-type]
    assert qa._cache is None  # 평가를 돌릴 때: 항상 새로 만든다


def test_injected_cache_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    given = object()
    qa = create_real_qa_service(FakeRetriever(), chain=object(), store=object(), tracer=object(), cache=given)  # type: ignore[arg-type]
    assert qa._cache is given
    off = create_real_qa_service(FakeRetriever(), chain=object(), store=object(), tracer=object(), cache=None)  # type: ignore[arg-type]
    assert off._cache is None  # None 은 명시적으로 끈다(환경변수가 켜져 있어도)


def test_entrypoint_in_real_mode_follows_the_cache_environment(monkeypatch):
    monkeypatch.setenv("BACKEND_IMPL", "real")
    assert backend.create_qa_service(FakeRetriever())._cache is None  # fixture 가 CACHE_ENABLED=false 로 둔다
    monkeypatch.setenv("CACHE_ENABLED", "true")
    assert isinstance(backend.create_qa_service(FakeRetriever())._cache, RedisAnswerCache)


# ── 조립은 연결하지 않는다 ──
def test_assembly_does_not_connect_to_anything(monkeypatch):
    monkeypatch.setenv("BACKEND_IMPL", "real")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")  # 아무도 듣지 않는 포트
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    started = time.monotonic()
    backend.create_qa_service(FakeRetriever())  # OPENAI_API_KEY 도 없다
    backend.create_session_service()
    assert time.monotonic() - started < 2  # 앱 기동이 외부 서비스를 기다리지 않는다


# ── 키가 없으면 /query 만 model_failed 로 나가고 앱은 뜬다 ──
def _client() -> TestClient:
    app = FastAPI()
    app.include_router(
        backend.create_router(backend.create_qa_service(FakeRetriever()), backend.create_session_service(), MANIFEST)
    )
    return TestClient(app)


def test_missing_api_key_keeps_health_up_and_fails_only_the_query(monkeypatch, caplog):
    monkeypatch.setenv("BACKEND_IMPL", "real")
    client = _client()

    assert client.get("/health").status_code == 200

    with caplog.at_level(logging.ERROR):
        res = client.post("/query", json={"question": "무료기간은?"})

    body = res.json()
    assert res.status_code == 502 and body["status"] == "error" and body["error_code"] == "model_failed"
    # 원인(키 설정 문제)은 서버 로그에만 남기고 사용자 응답에는 넣지 않는다
    assert "api_key" not in res.text.lower() and "credentials" not in res.text.lower()
    assert any("모델 클라이언트를 만들지 못했다" in r.message for r in caplog.records)


# ── 지연 생성 체인 ──
def test_lazy_chain_builds_once_and_only_when_needed():
    built = []

    def build(config):
        built.append(config)
        return object()

    chain = LazyAnswerChain(build=build)
    assert built == []  # 만들기만으로는 모델 클라이언트를 만들지 않는다
    assert chain.config is chain._config  # 설정은 클라이언트 없이도 읽힌다(검증 단계가 max_calls 를 읽는다)
    assert chain._get() is chain._get() and len(built) == 1


def test_lazy_chain_failure_is_model_call_error_and_retried_next_time(caplog):
    attempts = []

    def build(config):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Missing credentials: secret detail")
        return object()

    chain = LazyAnswerChain(build=build)
    with caplog.at_level(logging.ERROR), pytest.raises(ModelCallError) as err:
        chain._get()
    assert "secret detail" not in str(err.value)  # 원본 문구를 예외 메시지에 넣지 않는다
    assert chain._get() is not None and len(attempts) == 2  # 실패는 기억하지 않고 다시 시도한다


def test_lazy_chain_logs_the_traceback_only_the_first_time(caplog):
    def build(config):
        raise RuntimeError("no key")

    chain = LazyAnswerChain(build=build)
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            with pytest.raises(ModelCallError):
                chain._get()
    records = [r for r in caplog.records if "모델 클라이언트" in r.message]
    assert len(records) == 3 and sum(1 for r in records if r.exc_info) == 1  # 요청마다 스택을 쏟지 않는다


def test_lazy_chain_builds_the_real_chain_offline(monkeypatch):
    # 실제 ChatOpenAI 는 키만 있으면 오프라인으로 만들어진다(호출하지 않는다).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    assert isinstance(LazyAnswerChain()._get(), AnswerChain)
