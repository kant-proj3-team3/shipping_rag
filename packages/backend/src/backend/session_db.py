"""PostgreSQL 세션 저장소(G2): 질의응답 턴을 영구 저장한다. 세션 이력의 원본이다.

테이블 (세션 하나가 `rag_sessions` 한 행, 턴마다 `rag_session_turns` 한 행)
==========================================================================

::

    rag_sessions       session_id(PK), created_at, last_active_at, turn_count
    rag_session_turns  (session_id, seq)(PK), request_id, asked_at, turn(jsonb = SessionTurn)

- 턴은 `SessionTurn` JSON 전체를 `turn` 컬럼에 둔다. 계약 타입에 필드가 늘어도 컬럼을 고치지 않고, 읽을 때
  `SessionTurn` 으로 검증한다. 조회·정렬에 필요한 값(`seq`, `asked_at`, `request_id`)만 컬럼으로 뽑아 둔다.
- `seq` 는 세션 안의 순번(1부터)이고 `rag_sessions.turn_count` 와 같은 값이다. 기록은 한 트랜잭션에서 세션 행을
  upsert 하며 `turn_count` 를 올리고(행 잠금) 그 값을 `seq` 로 쓴다. 같은 세션에 동시에 기록해도 순번이 겹치거나
  빠지지 않는다.
- 만료가 없다. `expires_at` 은 이 저장소가 다루지 않는다(계약: 항상 None).

스키마 관리
-----------
마이그레이션 도구를 쓰지 않는다. 처음 쓸 때 `CREATE TABLE IF NOT EXISTS` 를 실행한다(여러 프로세스가 동시에 처음 쓰는
경우를 위해 advisory lock 을 건다). 연결은 첫 사용 때 만들어지므로 DB 가 꺼져 있어도 객체 생성과 앱 기동은 실패하지
않는다. **스키마가 바뀌는 시점에는 Alembic 같은 도구를 도입한다**(이 방식은 기존 테이블을 고치지 못한다).

장애 처리
---------
- 연결·질의가 `DATABASE_TIMEOUT_S` 안에 끝나지 않으면 예외를 낸다. `append` 의 실패를 응답 실패로 만들지 않는 일은
  QAService 가 한다.
- `get` 이 실패하면 예외를 그대로 낸다. "없음"(None → 404)과 "조회 실패"를 섞지 않는다.
- 클라이언트가 동기라서 비동기 경로에서는 `asyncio.to_thread` 로 이벤트 루프 밖에서 부른다.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

from common.types import SESSION_ID_PATTERN, SessionInfo, SessionTurn

logger = logging.getLogger(__name__)

ENV_DATABASE_URL = "DATABASE_URL"
ENV_DATABASE_TIMEOUT = "DATABASE_TIMEOUT_S"
ENV_DATABASE_POOL_MAX = "DATABASE_POOL_MAX"

# 기본값은 임시이며 팀이 정하면 환경변수로 바꾼다.
DEFAULT_DATABASE_URL = "postgresql://rag:rag@localhost:5432/rag"  # compose 의 postgres 로컬 개발용 기본 계정
DEFAULT_DATABASE_TIMEOUT_S = 2.0
DEFAULT_DATABASE_POOL_MAX = 4

_SESSION_ID = re.compile(SESSION_ID_PATTERN)

# 여러 프로세스가 동시에 스키마를 만들 때 겹치지 않게 하는 advisory lock 번호(임의의 고정값).
_SCHEMA_LOCK_ID = 7_431_020_001

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS rag_sessions (
        session_id      text PRIMARY KEY,
        created_at      timestamptz NOT NULL,
        last_active_at  timestamptz NOT NULL,
        turn_count      integer NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_session_turns (
        session_id  text NOT NULL REFERENCES rag_sessions (session_id) ON DELETE CASCADE,
        seq         integer NOT NULL,
        request_id  text NOT NULL,
        asked_at    timestamptz NOT NULL,
        turn        jsonb NOT NULL,
        PRIMARY KEY (session_id, seq)
    )
    """,
)

_UPSERT_SESSION = """
INSERT INTO rag_sessions (session_id, created_at, last_active_at, turn_count)
VALUES (%s, %s, %s, 1)
ON CONFLICT (session_id) DO UPDATE
    SET last_active_at = GREATEST(rag_sessions.last_active_at, EXCLUDED.last_active_at),
        turn_count     = rag_sessions.turn_count + 1
RETURNING turn_count
"""

_INSERT_TURN = """
INSERT INTO rag_session_turns (session_id, seq, request_id, asked_at, turn)
VALUES (%s, %s, %s, %s, %s::jsonb)
"""

# 세션 행과 최근 limit 개의 턴을 한 문장(= 한 스냅샷)으로 읽는다. 턴이 없거나 limit 이 0 이면 turn 이 NULL 인 한 행이 나온다.
_SELECT = """
SELECT s.created_at, s.last_active_at, s.turn_count, t.turn
FROM rag_sessions s
LEFT JOIN LATERAL (
    SELECT seq, turn FROM rag_session_turns
    WHERE session_id = s.session_id
    ORDER BY seq DESC
    LIMIT %s
) t ON true
WHERE s.session_id = %s
ORDER BY t.seq ASC NULLS LAST
"""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class PostgresSessionStore:
    """동기 저장소. 풀(`.connection()` 컨텍스트를 가진 객체)은 주입받는다."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._schema_ready = False
        self._lock = threading.Lock()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._lock:
            if self._schema_ready:
                return
            with self._pool.connection() as conn:  # 블록을 나갈 때 커밋되고 advisory lock 도 풀린다
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
                for statement in _SCHEMA:
                    conn.execute(statement)
            self._schema_ready = True

    def append(self, session_id: str, turn: SessionTurn) -> int:
        """턴을 기록하고 이 세션의 전체 턴 수(= 방금 기록한 턴의 순번)를 돌려준다."""
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("세션 ID 형식이 맞지 않는다")
        self._ensure_schema()
        with self._pool.connection() as conn:
            row = conn.execute(_UPSERT_SESSION, (session_id, turn.asked_at, turn.asked_at)).fetchone()
            seq = int(row[0])
            conn.execute(_INSERT_TURN, (session_id, seq, turn.request_id, turn.asked_at, turn.model_dump_json()))
        return seq

    def get(self, session_id: str, limit: int) -> SessionInfo | None:
        if not _SESSION_ID.fullmatch(session_id):
            return None
        self._ensure_schema()
        with self._pool.connection() as conn:
            rows = conn.execute(_SELECT, (max(limit, 0), session_id)).fetchall()
        if not rows:
            return None  # 한 번도 기록되지 않은 세션
        created_at, last_active_at, turn_count, _ = rows[0]
        return SessionInfo(
            session_id=session_id,
            created_at=created_at,
            last_active_at=last_active_at,
            expires_at=None,  # 만료가 없다
            turn_count=int(turn_count),
            turns=self._parse_turns(session_id, [r[3] for r in rows]),
        )

    @staticmethod
    def _parse_turns(session_id: str, raw_turns: list[Any]) -> list[SessionTurn]:
        turns: list[SessionTurn] = []
        for raw in raw_turns:
            if raw is None:  # 턴이 없는 세션(LEFT JOIN 의 빈 행)
                continue
            try:
                turns.append(SessionTurn.model_validate(raw))
            except ValueError:
                # 계약이 바뀌기 전에 저장된 턴 등. 한 건 때문에 세션 전체를 못 읽게 하지 않고 그 턴만 건너뛴다.
                logger.warning("읽을 수 없는 세션 턴을 건너뛴다 session_id=%s", session_id, exc_info=True)
        return turns


class _LazyPool:
    """첫 사용 때 풀을 열어 DB 가 꺼져 있어도 객체 생성·앱 기동이 실패하지 않게 한다.

    psycopg_pool 의 `ConnectionPool` 은 만들 때 연결을 시도하는 백그라운드 작업자를 띄우므로, 열기를 미룬다.
    """

    def __init__(self, conninfo: str, *, timeout_s: float, max_size: int) -> None:
        self._conninfo = conninfo
        self._timeout_s = timeout_s
        self._max_size = max_size
        self._pool: Any | None = None
        self._lock = threading.Lock()

    def _open(self) -> Any:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    from psycopg_pool import ConnectionPool

                    pool = ConnectionPool(
                        self._conninfo,
                        min_size=1,
                        max_size=self._max_size,
                        timeout=self._timeout_s,  # 풀에서 연결을 얻을 때까지 기다리는 최대 시간
                        kwargs={"connect_timeout": max(1, int(self._timeout_s))},
                        check=ConnectionPool.check_connection,  # 끊어진 연결을 꺼내 쓰지 않게 한다
                        open=False,
                    )
                    pool.open()
                    self._pool = pool
        return self._pool

    def connection(self) -> Any:
        return self._open().connection()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()


def create_postgres_store(*, pool: Any | None = None) -> PostgresSessionStore:
    """환경변수(`DATABASE_URL`, `DATABASE_TIMEOUT_S`, `DATABASE_POOL_MAX`)로 저장소를 만든다.

    연결은 첫 사용 때 만들어진다. DB 가 아직 없어도 여기서는 실패하지 않는다.
    """
    if pool is None:
        url = os.environ.get(ENV_DATABASE_URL, "").strip() or DEFAULT_DATABASE_URL
        pool = _LazyPool(
            url,
            timeout_s=_env_float(ENV_DATABASE_TIMEOUT, DEFAULT_DATABASE_TIMEOUT_S),
            max_size=_env_int(ENV_DATABASE_POOL_MAX, DEFAULT_DATABASE_POOL_MAX),
        )
    return PostgresSessionStore(pool)


__all__ = ["PostgresSessionStore", "create_postgres_store"]
