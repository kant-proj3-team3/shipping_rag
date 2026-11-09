"""Redis 세션: 질의응답 턴을 기록하고(QAService) 조회한다(SessionService).

저장 구조 (세션 하나당 키 두 개, 둘 다 같은 TTL)
=================================================

::

    rag:session:{id}:meta   hash   created_at, last_active_at, turn_count (전체 개수)
    rag:session:{id}:turns  list   SessionTurn JSON, 오래된 것 → 최신 순 (최근 SESSION_MAX_TURNS 개만 보관)

- 기록(`append`)은 한 트랜잭션(MULTI/EXEC)으로 두 키를 함께 갱신하고 TTL 을 다시 건다(마지막 활동 기준으로 만료).
  조회(`get`)는 TTL 을 연장하지 않는다.
- `turn_count` 는 목록 길이가 아니라 meta 의 카운터다. 보관 상한을 넘겨 오래된 턴이 잘려도 전체 개수는 유지된다.
- `expires_at` 은 `last_active_at + TTL` 이다(기록할 때마다 TTL 을 새로 걸기 때문에 같은 값이다).
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
from typing import Any

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


class RedisSessionService:
    """`common.interfaces.SessionService` 구현. 동기 저장소 호출을 이벤트 루프 밖에서 한다."""

    def __init__(self, store: RedisSessionStore) -> None:
        self._store = store

    async def get(self, session_id: str, limit: int = 20) -> SessionInfo | None:
        return await asyncio.to_thread(self._store.get, session_id, limit)


def create_session_store(*, client: Any | None = None) -> RedisSessionStore:
    """환경변수(`REDIS_URL`, `SESSION_TTL_SECONDS`, `SESSION_MAX_TURNS`, `REDIS_TIMEOUT_S`)로 저장소를 만든다.

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


__all__ = [
    "RedisSessionService",
    "RedisSessionStore",
    "create_session_store",
    "session_max_turns",
    "session_ttl_seconds",
]
