"""G2: DB(원본) + Redis(조회 캐시) 조합 저장소. 메모리 가짜 DB와 메모리 Redis 로 쓰기 순서·캐시 정합성·장애 격리를 확인한다.

실제 PostgreSQL SQL 은 `test_session_db.py` 가 확인한다(DB 가 있을 때만).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest

from backend.session import (
    PersistentSessionStore,
    RedisSessionStore,
    SessionQueryService,
    create_session_store,
)
from common.interfaces import SessionService
from common.types import AnswerStatus, RetrievalMode, SessionInfo, SessionTurn

SID = "session-0001"
T0 = datetime(2026, 11, 9, 9, 0, 0, tzinfo=UTC)


def _turn(n: int) -> SessionTurn:
    return SessionTurn(
        request_id=f"req-{n}",
        asked_at=T0 + timedelta(minutes=n),
        question=f"질문 {n}",
        retrieval_mode=RetrievalMode.HYBRID,
        status=AnswerStatus.ANSWERED,
        answer=f"답 {n}",
    )


class FakeDb:
    """`PostgresSessionStore` 와 같은 약속(append → 전체 턴 수, get → 최근 limit 개, 만료 없음)을 메모리에서 지킨다."""

    def __init__(self) -> None:
        self.sessions: dict[str, list[SessionTurn]] = {}
        self.get_calls = 0
        self.fail_append = False
        self.fail_get = False

    def append(self, session_id: str, turn: SessionTurn) -> int:
        if self.fail_append:
            raise ConnectionError("db down")
        turns = self.sessions.setdefault(session_id, [])
        turns.append(turn)
        return len(turns)

    def get(self, session_id: str, limit: int) -> SessionInfo | None:
        self.get_calls += 1
        if self.fail_get:
            raise ConnectionError("db down")
        turns = self.sessions.get(session_id)
        if not turns:
            return None
        return SessionInfo(
            session_id=session_id,
            created_at=turns[0].asked_at,
            last_active_at=turns[-1].asked_at,
            expires_at=None,
            turn_count=len(turns),
            turns=turns[-limit:] if limit > 0 else [],
        )


def _redis_client():
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


def _setup(max_turns: int = 200):
    db, client = FakeDb(), _redis_client()
    cache = RedisSessionStore(client, ttl_s=3600, max_turns=max_turns)
    return PersistentSessionStore(db, cache), db, cache, client


def _ids(info: SessionInfo) -> list[str]:
    return [t.request_id for t in info.turns]


# ── 쓰기 ──
def test_append_writes_db_and_invalidates_cache():
    store, db, cache, _ = _setup()
    store.append(SID, _turn(1))
    store.get(SID, 20)  # 캐시를 채운다
    assert cache.get(SID, 20) is not None

    store.append(SID, _turn(2))
    assert cache.get(SID, 20) is None  # 무효화됐다
    assert len(db.sessions[SID]) == 2
    assert _ids(store.get(SID, 20)) == ["req-1", "req-2"]  # 다음 조회는 새 턴을 본다


def test_db_failure_raises_and_leaves_cache_untouched():
    store, db, cache, _ = _setup()
    store.append(SID, _turn(1))
    store.get(SID, 20)  # 캐시: req-1

    db.fail_append = True
    with pytest.raises(ConnectionError):
        store.append(SID, _turn(2))
    # DB 에 없는 턴이 캐시에만 남지 않는다
    assert _ids(cache.get(SID, 20)) == ["req-1"]
    assert len(db.sessions[SID]) == 1


def test_cache_invalidate_failure_does_not_fail_the_write(monkeypatch):
    store, db, cache, _ = _setup()

    def boom(session_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "invalidate", boom)
    store.append(SID, _turn(1))  # 예외 없이 끝난다
    assert len(db.sessions[SID]) == 1


# ── 읽기 ──
def test_read_through_fills_cache_and_second_read_skips_db():
    store, db, cache, _ = _setup()
    db.append(SID, _turn(1))
    db.append(SID, _turn(2))

    first = store.get(SID, 20)
    assert _ids(first) == ["req-1", "req-2"] and db.get_calls == 1
    assert cache.get(SID, 20) is not None  # 채워졌다

    second = store.get(SID, 20)
    assert _ids(second) == ["req-1", "req-2"]
    assert db.get_calls == 1  # DB 를 다시 읽지 않았다


def test_expires_at_is_always_none_on_both_paths():
    store, db, _, _ = _setup()
    db.append(SID, _turn(1))
    assert store.get(SID, 20).expires_at is None  # DB 경로
    assert store.get(SID, 20).expires_at is None  # 캐시 경로(Redis 단독이라면 TTL 로 계산된 값이 나왔을 것이다)


def test_unknown_session_is_none_and_not_cached():
    store, _, cache, _ = _setup()
    assert store.get("session-9999", 20) is None
    assert cache.get("session-9999", 20) is None


def test_limit_zero_returns_count_only():
    store, db, _, _ = _setup()
    db.append(SID, _turn(1))
    db.append(SID, _turn(2))
    info = store.get(SID, 0)
    assert info.turns == [] and info.turn_count == 2


def test_history_survives_redis_expiry_and_new_turn():
    """회귀: Redis 키가 TTL 로 사라진 뒤 새 턴이 오면 Redis 단독 저장소는 카운터가 1부터 다시 시작해 이력이 잘린다."""
    store, _, _, client = _setup()
    for n in (1, 2, 3):
        store.append(SID, _turn(n))
    store.get(SID, 20)  # 캐시를 채운다

    client.flushall()  # TTL 만료를 흉내 낸다
    store.append(SID, _turn(4))

    info = store.get(SID, 20)
    assert info.turn_count == 4
    assert _ids(info) == ["req-1", "req-2", "req-3", "req-4"]


def test_cache_with_fewer_turns_than_requested_falls_back_to_db():
    store, db, _, _ = _setup(max_turns=2)  # 캐시는 최근 2개만 보관한다
    for n in range(1, 6):
        db.append(SID, _turn(n))

    assert _ids(store.get(SID, 5)) == ["req-1", "req-2", "req-3", "req-4", "req-5"]
    calls = db.get_calls
    assert _ids(store.get(SID, 5)) == ["req-1", "req-2", "req-3", "req-4", "req-5"]
    assert db.get_calls == calls + 1  # 캐시(2개)로는 모자라 다시 DB 를 읽었다

    assert _ids(store.get(SID, 2)) == ["req-4", "req-5"]
    assert db.get_calls == calls + 1  # 2개면 캐시로 충분하다
    assert store.get(SID, 2).turn_count == 5  # 캐시가 상한으로 잘려도 전체 개수는 DB 의 값이다


# ── 장애 격리 ──
def test_cache_read_failure_falls_back_to_db(monkeypatch):
    store, db, cache, _ = _setup()
    db.append(SID, _turn(1))

    def boom(session_id, limit):
        raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "get", boom)
    assert _ids(store.get(SID, 20)) == ["req-1"]


def test_cache_fill_failure_does_not_break_read(monkeypatch):
    store, db, cache, _ = _setup()
    db.append(SID, _turn(1))

    def boom(session_id, info):
        raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "fill", boom)
    assert _ids(store.get(SID, 20)) == ["req-1"]


def test_cache_hit_is_served_while_db_is_down():
    store, db, _, _ = _setup()
    db.append(SID, _turn(1))
    store.get(SID, 20)  # 캐시를 채운다

    db.fail_get = True
    assert _ids(store.get(SID, 20)) == ["req-1"]


def test_db_failure_on_cache_miss_is_raised_not_turned_into_none():
    store, db, _, _ = _setup()
    db.append(SID, _turn(1))
    db.fail_get = True
    with pytest.raises(ConnectionError):  # "없음"(404)과 "조회 실패"를 섞지 않는다
        store.get(SID, 20)


# ── 서비스·생성 ──
def test_service_reads_through_persistent_store():
    store, db, _, _ = _setup()
    db.append(SID, _turn(1))
    service = SessionQueryService(store)
    assert isinstance(service, SessionService)
    assert asyncio.run(service.get(SID, 20)).turn_count == 1
    assert asyncio.run(service.get("session-9999")) is None


def test_create_session_store_wires_db_and_redis_without_connecting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")  # 아무도 듣지 않는 포트
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    store = create_session_store()  # 생성만으로는 실패하지 않는다(앱 기동이 DB·Redis 를 기다리지 않는다)
    assert isinstance(store, PersistentSessionStore)


def test_create_session_store_accepts_injected_parts():
    db, client = FakeDb(), _redis_client()
    store = create_session_store(db=db, redis_client=client)
    store.append(SID, _turn(1))
    assert store.get(SID, 20).turn_count == 1
