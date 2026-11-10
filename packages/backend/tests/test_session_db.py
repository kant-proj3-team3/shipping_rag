"""G2: PostgreSQL 세션 저장소를 **실제 PostgreSQL** 로 확인한다.

`TEST_DATABASE_URL` 이 없으면 건너뛴다(CI 에는 DB 서비스가 없다). 로컬에서는 compose 의 postgres 로 돌린다::

    docker compose up -d postgres
    TEST_DATABASE_URL=postgresql://rag:rag@localhost:5432/rag uv run pytest packages/backend/tests/test_session_db.py

테스트가 쓰는 세션 ID 는 매번 새로 만들고 끝나면 지운다(개발 DB 의 다른 데이터는 건드리지 않는다).
"""

import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.session_db import PostgresSessionStore, _LazyPool, create_postgres_store
from common.types import AnswerStatus, RetrievalMode, SessionTurn

URL = os.environ.get("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 이 없어 실제 PostgreSQL 테스트를 건너뛴다")

T0 = datetime(2026, 11, 9, 9, 0, 0, tzinfo=UTC)


def _turn(n: int, **kw) -> SessionTurn:
    return SessionTurn(
        request_id=f"req-{n}",
        asked_at=T0 + timedelta(minutes=n),
        question=f"질문 {n}",
        retrieval_mode=RetrievalMode.HYBRID,
        status=AnswerStatus.ANSWERED,
        answer=f"답 {n}",
        **kw,
    )


@pytest.fixture
def pool():
    p = _LazyPool(URL, timeout_s=5.0, max_size=8)
    yield p
    p.close()


@pytest.fixture
def store(pool):
    return create_postgres_store(pool=pool)


@pytest.fixture
def sid(pool, store):
    session_id = f"t{uuid.uuid4().hex}"  # 33자, 세션 ID 형식에 맞다
    yield session_id
    store.get(session_id, 0)  # 스키마가 있는지 보장한다
    with pool.connection() as conn:
        conn.execute("DELETE FROM rag_sessions WHERE session_id = %s", (session_id,))  # 턴은 CASCADE 로 지워진다


# ── 저장·조회 ──
def test_roundtrip_fields_order_and_counts(store, sid):
    for n in (1, 2, 3):
        assert store.append(sid, _turn(n)) == n  # 기록은 전체 턴 수(순번)를 돌려준다

    info = store.get(sid, 20)
    assert info is not None and info.session_id == sid
    assert [t.request_id for t in info.turns] == ["req-1", "req-2", "req-3"]  # 오래된 것 → 최신
    assert info.turn_count == 3
    assert info.created_at == T0 + timedelta(minutes=1)  # 첫 턴 시각
    assert info.last_active_at == T0 + timedelta(minutes=3)
    assert info.expires_at is None  # 만료가 없다
    assert info.turns[0] == _turn(1)  # 저장했다 읽어도 같다(시각은 같은 시점이다)


def test_limit_returns_most_recent_in_order_but_counts_all(store, sid):
    for n in range(1, 6):
        store.append(sid, _turn(n))
    info = store.get(sid, 2)
    assert [t.request_id for t in info.turns] == ["req-4", "req-5"]
    assert info.turn_count == 5


def test_limit_zero_returns_no_turns_but_keeps_count(store, sid):
    store.append(sid, _turn(1))
    info = store.get(sid, 0)
    assert info.turns == [] and info.turn_count == 1


def test_missing_session_is_none(store):
    assert store.get(f"none{uuid.uuid4().hex}", 20) is None


def test_invalid_session_id_is_rejected_without_touching_db(store):
    assert store.get("짧음", 20) is None
    with pytest.raises(ValueError):
        store.append("bad id!", _turn(1))


def test_history_persists_across_stores_and_pools(store, sid):
    store.append(sid, _turn(1))
    store.append(sid, _turn(2))

    # 새 풀·새 저장소로 읽는다(프로세스를 다시 띄운 것과 같다). Redis 는 관여하지 않는다.
    other_pool = _LazyPool(URL, timeout_s=5.0, max_size=2)
    try:
        info = create_postgres_store(pool=other_pool).get(sid, 20)
    finally:
        other_pool.close()
    assert [t.request_id for t in info.turns] == ["req-1", "req-2"]


def test_unreadable_turn_is_skipped_not_fatal(pool, store, sid):
    store.append(sid, _turn(1))
    with pool.connection() as conn:  # 계약이 바뀌기 전에 저장된 턴을 흉내 낸다
        conn.execute("UPDATE rag_session_turns SET turn = '{\"깨짐\": 1}'::jsonb WHERE session_id = %s", (sid,))
    store.append(sid, _turn(2))

    info = store.get(sid, 20)
    assert [t.request_id for t in info.turns] == ["req-2"]  # 읽을 수 없는 턴만 건너뛴다
    assert info.turn_count == 2


# ── 동시성·스키마 ──
def test_concurrent_appends_get_unique_sequence_numbers(pool, store, sid):
    threads = [
        threading.Thread(target=lambda i=i: [store.append(sid, _turn(i * 10 + j)) for j in range(5)])
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.get(sid, 0).turn_count == 40
    with pool.connection() as conn:
        seqs = [r[0] for r in conn.execute("SELECT seq FROM rag_session_turns WHERE session_id = %s ORDER BY seq", (sid,))]
    assert seqs == list(range(1, 41))  # 겹치거나 빠진 순번이 없다


def test_schema_setup_is_idempotent_and_safe_when_first_used_concurrently():
    pools = [_LazyPool(URL, timeout_s=5.0, max_size=2) for _ in range(4)]
    errors: list[BaseException] = []

    def first_use(pool):
        try:
            create_postgres_store(pool=pool).get(f"none{uuid.uuid4().hex}", 0)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=first_use, args=(p,)) for p in pools]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for p in pools:
        p.close()
    assert errors == []


# ── 장애 ──
def test_unreachable_db_does_not_fail_creation_but_fails_fast_on_use(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")  # 아무도 듣지 않는 포트
    monkeypatch.setenv("DATABASE_TIMEOUT_S", "1")
    store = create_postgres_store()  # 생성만으로는 실패하지 않는다(앱 기동이 DB 를 기다리지 않는다)
    assert isinstance(store, PostgresSessionStore)

    started = time.monotonic()
    with pytest.raises(Exception):  # 풀 timeout 이나 연결 오류
        store.append("session-0001", _turn(1))
    assert time.monotonic() - started < 10  # 멈춰 있지 않는다
