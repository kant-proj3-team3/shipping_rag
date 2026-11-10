"""세션: 질의응답 턴을 기록하고(QAService) 조회한다(SessionService).

두 겹으로 저장한다 (G2)
=======================

::

    기록  ──▶ PostgreSQL(원본, session_db.py) ──성공하면──▶ Redis 캐시 무효화
    조회  ──▶ Redis 캐시 ──없으면──▶ PostgreSQL ──▶ Redis 캐시를 채운다

- **DB 가 원본이다.** 이력은 만료되지 않는다(`SessionInfo.expires_at` 은 항상 None, 404 는 한 번도 기록되지 않은 세션뿐).
  Redis 는 조회를 빠르게 하는 캐시일 뿐이고, TTL 은 캐시 수명이다.
- **쓰기: DB 먼저, 캐시는 무효화(삭제).** Redis 만 증분 갱신하면 TTL 이 지난 뒤 카운터가 1부터 다시 시작해 이력이 잘린 채
  보인다. 그래서 캐시를 고치지 않고 지우고, 다음 조회가 DB 에서 읽어 채운다.
- **DB 기록이 실패하면 그 턴은 Redis 에도 남기지 않는다.** DB 에 없는 턴이 캐시에만 남아 둘이 어긋나는 것을 막는다.
  예외는 그대로 낸다(응답을 막지 않는 일은 QAService 가 한다). 따라서 DB 장애 중의 턴은 저장되지 않는다.
- **조회: DB 가 꺼져도 캐시에 있으면 읽힌다.** 캐시가 없고 DB 도 실패하면 예외다("없음"과 섞지 않는다).
  캐시 조회·채우기·무효화의 실패는 경고만 남기고 DB 로 간다.
- 알려진 한계: 조회가 DB 에서 읽는 사이에 같은 세션에 기록이 들어오면 캐시가 한 턴 뒤처진 채 채워질 수 있다
  (다음 기록의 무효화나 TTL 까지). 같은 세션에서 동시에 질문하는 일은 드물다고 보고 잠금을 두지 않았다.

Redis 저장 구조 (세션 하나당 키 두 개, 둘 다 같은 TTL)
=======================================================

::

    rag:session:{id}:meta   hash   created_at, last_active_at, turn_count (전체 개수)
    rag:session:{id}:turns  list   SessionTurn JSON, 오래된 것 → 최신 순 (최근 SESSION_MAX_TURNS 개만 보관)

- 기록(`append`)은 한 트랜잭션(MULTI/EXEC)으로 두 키를 함께 갱신하고 TTL 을 다시 건다(마지막 활동 기준으로 만료).
  조회(`get`)는 TTL 을 연장하지 않는다. (`PersistentSessionStore` 는 캐시에 `append` 대신 `invalidate`·`fill` 을 쓴다.)
- `turn_count` 는 목록 길이가 아니라 meta 의 카운터다. 보관 상한을 넘겨 오래된 턴이 잘려도 전체 개수는 유지된다.
- `expires_at` 은 `last_active_at + TTL` 이다(Redis 단독 저장소의 값. `PersistentSessionStore` 는 계약에 맞춰 None 으로 바꾼다).
- `session_id` 는 키에 들어가므로 `SESSION_ID_PATTERN` 에 맞는 값만 쓴다(키 주입 방지).
  `get` 은 맞지 않으면 None, `append` 는 ValueError 다(QAService 가 기록 실패로 처리한다).
- 모든 키에 TTL 이 있다(compose 의 Redis 는 `volatile-lru` 라서 TTL 없는 키는 지워지지 않는다).

장애 처리
---------
- 연결은 첫 명령 때 만들어진다. Redis 가 꺼져 있어도 객체 생성과 앱 기동은 실패하지 않는다.
- 소켓 timeout(`REDIS_TIMEOUT_S`)이 있어 Redis 가 멈춰도 오래 붙잡히지 않는다.
- `append` 가 실패하면 예외를 그대로 낸다. 기록 실패를 응답 실패로 만들지 않는 일은 QAService 가 한다.
- `get` 이 실패하면 예외를 그대로 낸다. "없음"(None → 404)과 "조회 실패"를 섞지 않는다. 클라이언트가 세션이 없어졌다고
  오해해 새 세션을 시작하지 않게 하려는 것이다.
- 클라이언트가 동기라서 비동기 경로에서는 `asyncio.to_thread` 로 이벤트 루프 밖에서 부른다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.session_db import create_postgres_store
from common.types import SESSION_ID_PATTERN, SessionInfo, SessionTurn

logger = logging.getLogger(__name__)

ENV_REDIS_URL = "REDIS_URL"
ENV_SESSION_TTL = "SESSION_TTL_SECONDS"
ENV_SESSION_MAX_TURNS = "SESSION_MAX_TURNS"
ENV_REDIS_TIMEOUT = "REDIS_TIMEOUT_S"

# 기본값은 임시이며 팀이 정하면 환경변수로 바꾼다.
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_SESSION_TTL_S = 24 * 60 * 60
DEFAULT_SESSION_MAX_TURNS = 200
DEFAULT_REDIS_TIMEOUT_S = 2.0

KEY_PREFIX = "rag:session:"

_SESSION_ID = re.compile(SESSION_ID_PATTERN)


def _meta_key(session_id: str) -> str:
    return f"{KEY_PREFIX}{session_id}:meta"


def _turns_key(session_id: str) -> str:
    return f"{KEY_PREFIX}{session_id}:turns"


def _text(value: Any) -> str:
    """decode_responses 설정과 무관하게 문자열로 읽는다."""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def session_ttl_seconds() -> int:
    return _env_int(ENV_SESSION_TTL, DEFAULT_SESSION_TTL_S)


def session_max_turns() -> int:
    return _env_int(ENV_SESSION_MAX_TURNS, DEFAULT_SESSION_MAX_TURNS)


class RedisSessionStore:
    """동기 저장소. QAService 의 `SessionRecorder`(append)와 조회(get)를 모두 맡는다. 클라이언트는 주입받는다."""

    def __init__(self, client: Any, *, ttl_s: int | None = None, max_turns: int | None = None) -> None:
        self._client = client
        self._ttl_s = ttl_s if ttl_s is not None else session_ttl_seconds()
        self._max_turns = max_turns if max_turns is not None else session_max_turns()

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def invalidate(self, session_id: str) -> None:
        """캐시를 지운다(DB 에 새 턴이 기록된 뒤). 형식에 맞지 않는 ID 는 키가 없으므로 아무것도 하지 않는다."""
        if not _SESSION_ID.fullmatch(session_id):
            return
        self._client.delete(_meta_key(session_id), _turns_key(session_id))

    def fill(self, session_id: str, info: SessionInfo) -> None:
        """DB 에서 읽은 세션을 캐시로 채운다. 전체 턴 수는 DB 의 값을 그대로 쓰고, 턴은 최근 `max_turns` 개만 둔다."""
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("세션 ID 형식이 맞지 않는다")
        meta_key, turns_key = _meta_key(session_id), _turns_key(session_id)
        turns = info.turns[-self._max_turns :]
        pipe = self._client.pipeline(transaction=True)
        pipe.delete(meta_key, turns_key)
        pipe.hset(
            meta_key,
            mapping={
                "created_at": info.created_at.isoformat(),
                "last_active_at": info.last_active_at.isoformat(),
                "turn_count": info.turn_count,
            },
        )
        if turns:
            pipe.rpush(turns_key, *[t.model_dump_json() for t in turns])
        pipe.expire(meta_key, self._ttl_s)
        pipe.expire(turns_key, self._ttl_s)
        pipe.execute()

    def append(self, session_id: str, turn: SessionTurn) -> None:
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("세션 ID 형식이 맞지 않는다")
        meta_key, turns_key = _meta_key(session_id), _turns_key(session_id)
        asked_at = turn.asked_at.isoformat()
        pipe = self._client.pipeline(transaction=True)
        pipe.hsetnx(meta_key, "created_at", asked_at)  # 첫 턴의 시각이 세션 생성 시각
        pipe.hset(meta_key, "last_active_at", asked_at)
        pipe.hincrby(meta_key, "turn_count", 1)
        pipe.rpush(turns_key, turn.model_dump_json())
        pipe.ltrim(turns_key, -self._max_turns, -1)
        pipe.expire(meta_key, self._ttl_s)
        pipe.expire(turns_key, self._ttl_s)
        pipe.execute()

    def get(self, session_id: str, limit: int) -> SessionInfo | None:
        if not _SESSION_ID.fullmatch(session_id):
            return None
        pipe = self._client.pipeline(transaction=True)  # 두 키를 같은 시점에 읽는다
        pipe.hgetall(_meta_key(session_id))
        pipe.lrange(_turns_key(session_id), -max(limit, 1), -1)
        raw_meta, raw_turns = pipe.execute()
        if not raw_meta:
            return None  # 없거나 만료
        meta: Mapping[str, str] = {_text(k): _text(v) for k, v in raw_meta.items()}
        turns = self._parse_turns(session_id, raw_turns) if limit > 0 else []  # limit<=0 이면 이력 없이 개수만
        last_active = datetime.fromisoformat(meta["last_active_at"])
        return SessionInfo(
            session_id=session_id,
            created_at=datetime.fromisoformat(meta["created_at"]),
            last_active_at=last_active,
            expires_at=last_active + timedelta(seconds=self._ttl_s),
            turn_count=int(meta["turn_count"]),
            turns=turns,
        )

    @staticmethod
    def _parse_turns(session_id: str, raw_turns: list[Any]) -> list[SessionTurn]:
        turns: list[SessionTurn] = []
        for raw in raw_turns:
            try:
                turns.append(SessionTurn.model_validate_json(_text(raw)))
            except ValueError:
                # 계약이 바뀌기 전에 저장된 턴 등. 한 건 때문에 세션 전체를 못 읽게 하지 않고, 읽을 수 없는 턴만 건너뛴다.
                logger.warning("읽을 수 없는 세션 턴을 건너뛴다 session_id=%s", session_id, exc_info=True)
        return turns


class SessionBackend(Protocol):
    """`PersistentSessionStore` 가 원본(DB)에 요구하는 것. `PostgresSessionStore` 가 만족한다."""

    def append(self, session_id: str, turn: SessionTurn) -> int: ...

    def get(self, session_id: str, limit: int) -> SessionInfo | None: ...


class PersistentSessionStore:
    """DB(원본) + Redis(조회 캐시). QAService 의 `SessionRecorder`(append)와 조회(get)를 모두 맡는다."""

    def __init__(self, db: SessionBackend, cache: RedisSessionStore) -> None:
        self._db = db
        self._cache = cache

    def append(self, session_id: str, turn: SessionTurn) -> None:
        # DB 가 실패하면 그대로 예외를 낸다. 캐시에는 쓰지 않는다(DB 에 없는 턴이 캐시에만 남지 않게).
        self._db.append(session_id, turn)
        try:
            self._cache.invalidate(session_id)
        except Exception:  # noqa: BLE001 - 캐시 장애가 기록 실패가 되지 않게 한다. 캐시는 TTL 이나 다음 기록 때 바로잡힌다
            logger.warning("세션 캐시를 무효화하지 못했다 session_id=%s", session_id, exc_info=True)

    def get(self, session_id: str, limit: int) -> SessionInfo | None:
        cached = self._from_cache(session_id, limit)
        if cached is not None:
            return cached
        return self._from_db(session_id, limit)

    def _from_cache(self, session_id: str, limit: int) -> SessionInfo | None:
        try:
            cached = self._cache.get(session_id, limit)
        except Exception:  # noqa: BLE001 - 캐시를 못 읽으면 DB 에서 읽는다
            logger.warning("세션 캐시 조회 실패. DB 에서 읽는다 session_id=%s", session_id, exc_info=True)
            return None
        if cached is None:
            return None
        if limit > 0 and len(cached.turns) < min(limit, cached.turn_count):
            return None  # 캐시에 보관된 턴이 요청보다 적다(보관 상한). DB 에서 읽는다
        return cached.model_copy(update={"expires_at": None})  # 만료 없음(Redis TTL 은 캐시 수명일 뿐이다)

    def _from_db(self, session_id: str, limit: int) -> SessionInfo | None:
        # 캐시를 채울 수 있게 보관 상한만큼 읽고, 요청한 limit 개만 돌려준다.
        full = self._db.get(session_id, max(limit, self._cache.max_turns))
        if full is None:
            return None
        try:
            self._cache.fill(session_id, full)
        except Exception:  # noqa: BLE001 - 캐시를 못 채워도 응답은 나간다
            logger.warning("세션 캐시를 채우지 못했다 session_id=%s", session_id, exc_info=True)
        turns = full.turns[-limit:] if limit > 0 else []
        return full.model_copy(update={"turns": turns})


class SessionQueryService:
    """`common.interfaces.SessionService` 구현. 동기 저장소 호출을 이벤트 루프 밖에서 한다."""

    def __init__(self, store: Any) -> None:  # get(session_id, limit) 을 가진 저장소(Redis 단독·PersistentSessionStore)
        self._store = store

    async def get(self, session_id: str, limit: int = 20) -> SessionInfo | None:
        return await asyncio.to_thread(self._store.get, session_id, limit)


RedisSessionService = SessionQueryService  # G 단계의 이름(호환 별칭)


def create_redis_session_store(*, client: Any | None = None) -> RedisSessionStore:
    """환경변수(`REDIS_URL`, `SESSION_TTL_SECONDS`, `SESSION_MAX_TURNS`, `REDIS_TIMEOUT_S`)로 Redis 저장소를 만든다.

    `from_url` 은 연결하지 않는다. 첫 명령 때 연결하므로 Redis 가 아직 없어도 여기서는 실패하지 않는다.
    """
    if client is None:
        import redis

        timeout = _env_float(ENV_REDIS_TIMEOUT, DEFAULT_REDIS_TIMEOUT_S)
        url = os.environ.get(ENV_REDIS_URL, "").strip() or DEFAULT_REDIS_URL
        client = redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=timeout, socket_connect_timeout=timeout
        )
    return RedisSessionStore(client)


def create_session_store(*, redis_client: Any | None = None, db: SessionBackend | None = None) -> PersistentSessionStore:
    """DB(원본) + Redis(캐시) 저장소를 만든다. 둘 다 환경변수로 설정하고 연결은 첫 사용 때 만들어진다.

    `DATABASE_URL`(기본 localhost 의 compose postgres)과 Redis 설정은 각 저장소의 문서를 본다. 둘 다 아직 없어도
    여기서는 실패하지 않는다.
    """
    return PersistentSessionStore(
        db if db is not None else create_postgres_store(), create_redis_session_store(client=redis_client)
    )


__all__ = [
    "PersistentSessionStore",
    "RedisSessionService",
    "RedisSessionStore",
    "SessionQueryService",
    "create_redis_session_store",
    "create_session_store",
    "session_max_turns",
    "session_ttl_seconds",
]
