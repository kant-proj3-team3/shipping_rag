"""목업 세션: 프로세스 메모리에 저장한다 (실제 구현은 PostgreSQL 원본 + Redis 캐시). 만료가 없어 `expires_at` 은 항상 None 이다."""

from __future__ import annotations

from datetime import UTC, datetime

from common.types import SessionInfo, SessionTurn


class InMemorySessionStore:
    def __init__(self) -> None:
        self._turns: dict[str, list[SessionTurn]] = {}
        self._created: dict[str, datetime] = {}

    def append(self, session_id: str, turn: SessionTurn) -> None:
        self._created.setdefault(session_id, datetime.now(UTC))
        self._turns.setdefault(session_id, []).append(turn)

    def get(self, session_id: str, limit: int) -> SessionInfo | None:
        turns = self._turns.get(session_id)
        if not turns:
            return None
        return SessionInfo(
            session_id=session_id,
            created_at=self._created[session_id],
            last_active_at=turns[-1].asked_at,
            expires_at=None,
            turn_count=len(turns),
            turns=turns[-limit:],  # 오래된 것 → 최신 순, 최근 limit 개
        )


class MockSessionService:
    def __init__(self, store: InMemorySessionStore) -> None:
        self._store = store

    async def get(self, session_id: str, limit: int = 20) -> SessionInfo | None:
        return self._store.get(session_id, limit)
