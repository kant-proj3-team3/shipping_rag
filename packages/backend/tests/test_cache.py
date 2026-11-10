"""H: Redis 답변 캐시. 키 구성·적중·비적중 조건·오류 미저장·이력 우회·장애 격리를 가짜 LLM·메모리 Redis 로 확인한다."""

import asyncio
import json
import unicodedata
from dataclasses import fields, replace
from datetime import UTC, datetime

import fakeredis
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from backend.cache import (
    DEFAULT_CACHE_TIMEOUT_S,
    DEFAULT_CACHE_TTL_S,
    ENV_CACHE_ENABLED,
    ENV_CACHE_TIMEOUT,
    ENV_CACHE_TTL,
    KEY_PREFIX,
    CacheKey,
    RedisAnswerCache,
    cache_enabled,
    cache_timeout_seconds,
    cache_ttl_seconds,
    create_answer_cache,
    normalize_question,
)
from backend.chain import AnswerChain, ChainConfig
from backend.prompts import ModelOutput, PromptVariant
from backend.qa import BackendQAService
from backend.session import RedisSessionStore
from common.types import (
    AnswerStatus,
    Chunk,
    IndexManifest,
    QAResult,
    QueryMeta,
    QueryRequest,
    QueryResponse,
    RequestContext,
    RetrievalMode,
    RetrievalResult,
    RetrievedChunk,
)

MANIFEST = IndexManifest(
    index_name="idx", embedder_id="emb", embedding_dim=4, document_count=1, chunk_count=1,
    fingerprint="fp-1", max_chunk_tokens=8, created_at=datetime.now(UTC),
)
SID = "session-0001"


# ── 준비물 ──
def _good(text: str = "무료기간은 3일입니다.") -> str:
    return json.dumps({"status": "answered", "answer": text, "reason": "표", "source_ids": ["S1"]}, ensure_ascii=False)


class ScriptedLLM(Runnable):
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        self.calls += 1
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        raw = AIMessage(content=item)
        raw.usage_metadata = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
        return {"raw": raw, "parsed": ModelOutput.model_validate_json(item), "parsing_error": None}


class FakeRetriever:
    supported_modes = list(RetrievalMode)

    def __init__(self, chunks=None, index=MANIFEST):
        self.index = index
        self.chunks = chunks if chunks is not None else [
            Chunk(chunk_id="c1", book_id="IS01", file_name="IS01.pdf", page_start=4, page_end=4, text="무료기간은 3일이다.")
        ]
        self.requests = []

    async def retrieve(self, request, ctx):
        self.requests.append(request)
        return RetrievalResult(
            mode=request.mode, k=request.k, chunks=[RetrievedChunk(rank=i, score=1.0, chunk=c) for i, c in enumerate(self.chunks, 1)]
        )


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


def _redis():
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


def _store(client=None):
    return RedisSessionStore(client or _redis(), ttl_s=3600)


class Env:
    """한 테스트 안에서 서비스 여러 개가 같은 캐시·저장소를 공유할 때 쓰는 묶음."""

    def __init__(self, *llm_items, chunks=None):
        self.client = _redis()
        self.cache = RedisAnswerCache(self.client, ttl_s=60)
        self.store = _store()
        self.llm = ScriptedLLM(*(llm_items or (_good(),)))
        self.retriever = FakeRetriever(chunks)
        self.tracer = FakeTracer()

    def service(self, *, config=None, variant=PromptVariant.BASE, cache="default", llm=None) -> BackendQAService:
        chain = AnswerChain(llm or self.llm, config or ChainConfig(timeout_s=1.0, max_retries=0))
        return BackendQAService(
            self.retriever, chain, self.store, history=self.store, tracer=self.tracer, variant=variant,
            cache=self.cache if cache == "default" else cache,
        )

    def ask(self, service, question="보관료 무료기간은?", *, session_id=None, mode=None, request_id="req-1") -> QAResult:
        return asyncio.run(
            service.answer(
                QueryRequest(question=question, session_id=session_id, retrieval_mode=mode), RequestContext(request_id=request_id)
            )
        )

    def keys(self) -> list[str]:
        return sorted(self.client.keys(KEY_PREFIX + "*"))


# ── 키 ──
BASE_KEY = CacheKey(
    question="질문", retrieval_mode="hybrid", k=5, index_name="idx", embedder_id="emb", fingerprint="fp-1",
    prompt_version="v2", model="gpt-6-luna", reasoning_effort="medium", temperature=None, context_max_tokens=12000,
)

CHANGED = {
    "question": "다른 질문", "retrieval_mode": "naive", "k": 3, "index_name": "idx2", "embedder_id": "emb2",
    "fingerprint": "fp-2", "prompt_version": "v2+guarded", "model": "other-model", "reasoning_effort": "low",
    "temperature": 0.0, "context_max_tokens": 6000,
}


@pytest.mark.parametrize("name", [f.name for f in fields(CacheKey)])
def test_every_input_that_can_change_the_answer_changes_the_key(name):
    assert replace(BASE_KEY, **{name: CHANGED[name]}).digest() != BASE_KEY.digest()


def test_key_is_stable_and_in_its_own_namespace():
    assert BASE_KEY.digest() == replace(BASE_KEY).digest()
    assert BASE_KEY.digest().startswith("rag:answer:") and not BASE_KEY.digest().startswith("rag:session:")  # 세션 키와 분리


def test_question_is_normalized_for_the_key():
    composed = "보관료 무료기간은?"
    assert normalize_question("  " + unicodedata.normalize("NFD", composed) + "\n") == composed


# ── 적중 ──
def test_second_identical_question_is_served_from_cache_with_the_same_schema():
    env = Env(_good("무료기간은 3일입니다."))
    service = env.service()
    first = env.ask(service, request_id="req-1")
    second = env.ask(service, request_id="req-2")

    assert env.llm.calls == 1 and len(env.retriever.requests) == 1  # 검색도 모델 호출도 하지 않았다
    assert first.response.meta.cache_hit is False and first.response.meta.input_tokens == 7
    r = second.response
    assert r.meta.cache_hit is True and r.request_id == "req-2"  # 새 request_id
    assert r.meta.input_tokens is None and r.meta.output_tokens is None  # 이번 요청에서 모델을 부르지 않았다(0 이 아니라 None)
    assert r.meta.latency_ms is not None and r.meta.trace_id == "trace-1"
    assert (r.status, r.answer, r.reason, r.citations) == (
        first.response.status, first.response.answer, first.response.reason, first.response.citations,
    )
    assert second.final_context == first.final_context and second.final_context  # 평가 입력도 같은 스키마로 돌려준다


def test_abstained_for_empty_retrieval_is_cached_too():
    env = Env(chunks=[])
    service = env.service()
    assert env.ask(service).response.status is AnswerStatus.ABSTAINED
    assert env.ask(service).response.meta.cache_hit is True
    assert len(env.retriever.requests) == 1 and env.llm.calls == 0


def test_keys_have_a_ttl_and_stay_in_the_answer_namespace():
    env = Env()
    env.ask(env.service())
    assert len(env.keys()) == 1
    assert 0 < env.client.ttl(env.keys()[0]) <= 60  # 모든 키에 TTL 이 있다
    assert env.client.keys("rag:session:*") == []  # 세션 키 공간을 건드리지 않았다


# ── 비적중 조건 ──
def test_reindexing_the_same_name_does_not_serve_old_answers():
    env = Env(_good("옛 답"), _good("새 답"))
    service = env.service()
    assert env.ask(service).response.answer == "옛 답"

    env.retriever.index = MANIFEST.model_copy(update={"fingerprint": "fp-2"})  # 같은 이름으로 재색인
    again = env.ask(service)
    assert again.response.answer == "새 답" and again.response.meta.cache_hit is False and env.llm.calls == 2


def test_prompt_version_change_does_not_hit():
    env = Env(_good("기본 프롬프트"), _good("방어 프롬프트"))
    env.ask(env.service())
    guarded = env.ask(env.service(variant=PromptVariant.GUARDED))
    assert guarded.response.meta.cache_hit is False and guarded.response.answer == "방어 프롬프트"


@pytest.mark.parametrize(
    "config",
    [
        ChainConfig(model="other-model", timeout_s=1.0, max_retries=0),
        ChainConfig(reasoning_effort="low", timeout_s=1.0, max_retries=0),
        ChainConfig(reasoning_effort="none", temperature=0.0, timeout_s=1.0, max_retries=0),
    ],
)
def test_model_settings_change_does_not_hit(config):
    env = Env(_good("첫 답"), _good("둘째 답"))
    env.ask(env.service())
    other = env.ask(env.service(config=config))
    assert other.response.meta.cache_hit is False and env.llm.calls == 2


def test_retrieval_mode_change_does_not_hit():
    env = Env(_good("하이브리드"), _good("나이브"))
    service = env.service()
    env.ask(service, mode=RetrievalMode.HYBRID)
    assert env.ask(service, mode=RetrievalMode.NAIVE).response.meta.cache_hit is False
    assert env.ask(service, mode=RetrievalMode.HYBRID).response.meta.cache_hit is True  # 같은 모드는 적중한다


def test_different_question_does_not_hit():
    env = Env(_good("답1"), _good("답2"))
    service = env.service()
    env.ask(service, "질문 하나")
    assert env.ask(service, "질문 둘").response.meta.cache_hit is False


# ── 오류는 저장하지 않는다 ──
def test_errors_are_never_cached():
    env = Env(RuntimeError("boom"), _good("정상 답"))
    service = env.service()
    failed = env.ask(service)
    assert failed.response.status is AnswerStatus.ERROR and env.keys() == []  # 저장하지 않았다

    ok = env.ask(service)  # 같은 질문: 실패가 고정되지 않고 새로 만든다
    assert ok.response.status is AnswerStatus.ANSWERED and ok.response.meta.cache_hit is False
    assert len(env.keys()) == 1


def test_put_refuses_an_error_result_and_get_never_returns_one():
    env = Env()
    err = QAResult(
        response=QueryResponse(
            request_id="r", status=AnswerStatus.ERROR, answer="실패", reason="x", error_code="model_failed",
            meta=QueryMeta(retrieval_mode=RetrievalMode.HYBRID),
        )
    )
    assert env.cache.put("rag:answer:x", err) is False and env.client.get("rag:answer:x") is None


# ── 끄기 ──
def test_without_a_cache_every_question_is_generated_again():
    env = Env()
    service = env.service(cache=None)
    env.ask(service)
    again = env.ask(service)
    assert env.llm.calls == 2 and again.response.meta.cache_hit is False and env.keys() == []


@pytest.mark.parametrize("raw, expected", [(None, True), ("", True), ("true", True), ("1", True), ("false", False), (" FALSE ", False), ("0", False), ("off", False), ("no", False)])
def test_cache_enabled_environment(monkeypatch, raw, expected):
    monkeypatch.delenv(ENV_CACHE_ENABLED, raising=False)
    if raw is not None:
        monkeypatch.setenv(ENV_CACHE_ENABLED, raw)
    assert cache_enabled() is expected


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "1.5"])
def test_invalid_ttl_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv(ENV_CACHE_TTL, raw)
    assert cache_ttl_seconds() == DEFAULT_CACHE_TTL_S


def test_ttl_is_read_from_environment(monkeypatch):
    monkeypatch.setenv(ENV_CACHE_TTL, "120")
    assert cache_ttl_seconds() == 120 and RedisAnswerCache(_redis())._ttl_s == 120


@pytest.mark.parametrize("raw", ["", "abc", "0", "-1"])
def test_invalid_cache_timeout_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv(ENV_CACHE_TIMEOUT, raw)
    assert cache_timeout_seconds() == DEFAULT_CACHE_TIMEOUT_S


def test_cache_client_has_its_own_short_timeout_and_does_not_connect(monkeypatch):
    # 캐시는 느려지면 없는 것보다 나쁘다: 세션 저장소(REDIS_TIMEOUT_S 기본 2초)와 별개로 짧게 준다.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # 아무도 듣지 않는 포트
    monkeypatch.setenv("REDIS_TIMEOUT_S", "2")
    cache = create_answer_cache()  # 생성만으로는 연결하지 않는다
    kwargs = cache._client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == DEFAULT_CACHE_TIMEOUT_S == kwargs["socket_connect_timeout"]
    monkeypatch.setenv(ENV_CACHE_TIMEOUT, "0.2")
    assert create_answer_cache()._client.connection_pool.connection_kwargs["socket_timeout"] == 0.2


# ── 이력(멀티턴) ──
def test_requests_with_history_bypass_the_cache():
    env = Env(_good("답1"), _good("답2"), _good("답3"))
    service = env.service()
    env.ask(service, "질문 A", session_id=SID)  # 이력이 비어 있는 첫 질문: 캐시를 쓴다
    assert len(env.keys()) == 1

    follow_up = env.ask(service, "질문 B", session_id=SID)  # 이전 대화가 프롬프트에 들어간다: 읽지도 쓰지도 않는다
    assert follow_up.response.meta.cache_hit is False and len(env.keys()) == 1

    repeat = env.ask(service, "질문 A", session_id=SID)  # 같은 질문이라도 이력이 있으니 캐시에서 내보내지 않는다
    assert repeat.response.meta.cache_hit is False and env.llm.calls == 3


def test_first_turn_of_a_session_uses_the_cache_and_a_hit_is_still_recorded_in_the_session():
    env = Env(_good("공통 답"))
    service = env.service()
    env.ask(service, session_id="session-aaaa")
    hit = env.ask(service, session_id="session-bbbb")  # 다른 세션의 같은 질문

    assert hit.response.meta.cache_hit is True and env.llm.calls == 1
    info = env.store.get("session-bbbb", 20)  # 적중해도 대화 이력에는 남아야 한다
    assert info is not None and info.turn_count == 1 and info.turns[0].answer == "공통 답"


# ── 트레이스 ──
def test_trace_shows_the_cache_step_and_skips_retrieval_on_a_hit():
    env = Env()
    service = env.service()
    env.ask(service)
    env.ask(service)

    miss, hit = env.tracer.traces
    assert [s.name for s in miss.steps][:2] == ["cache-lookup", "retrieve"] and miss.steps[0].output == {"hit": False}
    assert miss.annotations["cache_hit"] is False
    assert [s.name for s in hit.steps] == ["cache-lookup"] and hit.steps[0].output == {"hit": True}  # 검색·문맥·모델 단계가 없다
    assert hit.annotations["cache_hit"] is True and hit.annotations["model_called"] is False


# ── 장애 격리 ──
class SpyCache:
    """읽기·쓰기 호출을 세고, 원하는 쪽을 실패시킨다."""

    def __init__(self, *, fail_get=False, fail_put=False):
        self.fail_get, self.fail_put = fail_get, fail_put
        self.gets = self.puts = 0

    def get(self, key):
        self.gets += 1
        if self.fail_get:
            raise ConnectionError("redis down")
        return None

    def put(self, key, result):
        self.puts += 1
        if self.fail_put:
            raise ConnectionError("redis down")
        return True


def test_read_failure_answers_without_cache_and_skips_the_write(caplog):
    env = Env()
    spy = SpyCache(fail_get=True)
    with caplog.at_level("WARNING"):
        result = env.ask(env.service(cache=spy))

    assert result.response.status is AnswerStatus.ANSWERED  # 응답은 실패하지 않는다
    assert spy.gets == 1 and spy.puts == 0  # 읽기에 실패하면 쓰기는 시도하지 않는다(Redis 가 죽었을 때 timeout 을 두 번 치르지 않게)
    assert any("답변 캐시를 읽지 못해" in r.message for r in caplog.records)
    step = env.tracer.traces[0].steps[0]
    assert step.name == "cache-lookup" and step.error == "cache_unavailable"
    assert env.tracer.traces[0].annotations["cache_error"] is True


def test_write_failure_does_not_fail_the_answer(caplog):
    env = Env()
    spy = SpyCache(fail_put=True)
    with caplog.at_level("WARNING"):
        result = env.ask(env.service(cache=spy))
    assert result.response.status is AnswerStatus.ANSWERED and spy.puts == 1
    assert env.tracer.traces[0].annotations["cache_write_error"] is True
    assert any("답변 캐시에 저장하지 못했다" in r.message for r in caplog.records)


def test_unreadable_entry_is_a_miss_and_gets_overwritten():
    env = Env(_good("처음 답"), _good("다시 만든 답"))
    service = env.service()
    env.ask(service)
    (key,) = env.keys()

    env.client.set(key, "{깨진 JSON")  # 깨진 항목
    rebuilt = env.ask(service)
    assert rebuilt.response.answer == "다시 만든 답" and rebuilt.response.meta.cache_hit is False  # 실패하지 않고 다시 만든다
    assert env.ask(service).response.meta.cache_hit is True  # 덮어썼다


@pytest.mark.parametrize("entry", [{"v": 0, "result": {}}, {"v": 1, "result": {"response": "형식이 틀림"}}, {"no": "version"}])
def test_old_or_malformed_entries_are_misses(entry):
    env = Env(_good("처음 답"), _good("다시 만든 답"))
    service = env.service()
    env.ask(service)
    (key,) = env.keys()

    env.client.set(key, json.dumps(entry))
    assert env.ask(service).response.meta.cache_hit is False and env.llm.calls == 2


def test_roundtrip_preserves_the_result():
    env = Env()
    result = env.ask(env.service())
    (key,) = env.keys()
    assert env.cache.get(key) == result
