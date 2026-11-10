"""G3: 세션 이력에서 프롬프트에 넣을 이전 대화를 고르는 일(history.py). 선택·예산·환경변수·읽기."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.history import (
    DEFAULT_HISTORY_MAX_TOKENS,
    DEFAULT_HISTORY_MAX_TURNS,
    ENV_HISTORY_MAX_TOKENS,
    ENV_HISTORY_MAX_TURNS,
    history_max_tokens,
    history_max_turns,
    load_history,
    select_history,
)
from backend.prompts import HistoryTurn, format_turn
from common.types import AnswerStatus, RetrievalMode, SessionInfo, SessionTurn

SID = "session-0001"
T0 = datetime(2026, 11, 10, 9, 0, 0, tzinfo=UTC)


def _turn(n: int, question: str | None = None, answer: str | None = None) -> SessionTurn:
    return SessionTurn(
        request_id=f"req-{n}",
        asked_at=T0 + timedelta(minutes=n),
        question=question if question is not None else f"질문 {n}",
        retrieval_mode=RetrievalMode.HYBRID,
        status=AnswerStatus.ANSWERED,
        answer=answer if answer is not None else f"답 {n}",
    )


# ── 선택 ──
def test_selects_most_recent_turns_in_order():
    turns = [_turn(n) for n in range(1, 6)]
    got = select_history(turns, max_turns=3, max_tokens=2000)
    assert got == [HistoryTurn("질문 3", "답 3"), HistoryTurn("질문 4", "답 4"), HistoryTurn("질문 5", "답 5")]


def test_fewer_turns_than_limit_returns_all():
    assert select_history([_turn(1)], max_turns=3, max_tokens=2000) == [HistoryTurn("질문 1", "답 1")]


@pytest.mark.parametrize("max_turns, max_tokens", [(0, 2000), (3, 0), (-1, 2000)])
def test_disabled_or_empty_returns_nothing(max_turns, max_tokens):
    assert select_history([_turn(1)], max_turns=max_turns, max_tokens=max_tokens) == []
    assert select_history([], max_turns=3, max_tokens=2000) == []


# ── 예산 ──
def test_long_answer_is_cut_to_the_per_turn_budget_and_keeps_the_question():
    # 예산 100, 2턴 → 턴마다 50. 형식 머리말("질문: 질문\n답변: ")이 11자라 답은 38자 + "…" 가 된다.
    long = _turn(1, question="질문", answer="가" * 100)
    (got,) = select_history([long], max_turns=2, max_tokens=100)
    assert got.question == "질문"
    assert got.answer == "가" * 38 + "…"
    assert len(format_turn(got.question, got.answer)) == 50


def test_short_turn_is_untouched():
    (got,) = select_history([_turn(1, answer="짧은 답")], max_turns=2, max_tokens=2000)
    assert got.answer == "짧은 답"


def test_turn_whose_question_alone_exceeds_budget_is_skipped():
    big_question = _turn(1, question="가" * 60, answer="답")
    ok = _turn(2, question="질문", answer="답")
    got = select_history([big_question, ok], max_turns=2, max_tokens=100)  # 턴마다 50
    assert got == [HistoryTurn("질문", "답")]


@pytest.mark.parametrize("answer_len", [0, 10, 300, 5000])
@pytest.mark.parametrize("max_turns, max_tokens", [(1, 200), (3, 2000), (5, 900)])
def test_total_never_exceeds_the_budget(answer_len, max_turns, max_tokens):
    turns = [_turn(n, answer="나" * answer_len) for n in range(1, 8)]
    got = select_history(turns, max_turns=max_turns, max_tokens=max_tokens)
    assert sum(len(format_turn(t.question, t.answer)) for t in got) <= max_tokens


def test_custom_counter_is_used():
    # 단어 수로 센다: 형식 머리말까지 포함해 10단어까지만 허용(턴 하나, 예산 10).
    def words(text: str) -> int:
        return len(text.split())

    (got,) = select_history([_turn(1, answer=" ".join(["단어"] * 50))], max_turns=1, max_tokens=10, count_tokens=words)
    assert words(format_turn(got.question, got.answer)) <= 10 and got.answer.endswith("…")


# ── 환경변수 ──
@pytest.mark.parametrize("raw", ["", "abc", "-1", "2.5"])
def test_invalid_turn_limit_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv(ENV_HISTORY_MAX_TURNS, raw)
    assert history_max_turns() == DEFAULT_HISTORY_MAX_TURNS


def test_turn_limit_zero_means_off_and_values_are_read(monkeypatch):
    monkeypatch.setenv(ENV_HISTORY_MAX_TURNS, "0")
    assert history_max_turns() == 0
    monkeypatch.setenv(ENV_HISTORY_MAX_TURNS, "5")
    assert history_max_turns() == 5


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_invalid_token_limit_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv(ENV_HISTORY_MAX_TOKENS, raw)
    assert history_max_tokens() == DEFAULT_HISTORY_MAX_TOKENS


def test_token_limit_is_read(monkeypatch):
    monkeypatch.setenv(ENV_HISTORY_MAX_TOKENS, "500")
    assert history_max_tokens() == 500


# ── 읽기 ──
class FakeSource:
    def __init__(self, turns=None, error=None):
        self.turns = turns
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def get(self, session_id: str, limit: int):
        self.calls.append((session_id, limit))
        if self.error:
            raise self.error
        if self.turns is None:
            return None
        return SessionInfo(
            session_id=session_id,
            created_at=T0,
            last_active_at=T0,
            turn_count=len(self.turns),
            turns=self.turns[-limit:] if limit > 0 else [],
        )


def test_load_reads_only_as_many_turns_as_needed():
    source = FakeSource([_turn(n) for n in range(1, 6)])
    got = asyncio.run(load_history(source, SID, max_turns=2, max_tokens=2000))
    assert source.calls == [(SID, 2)]
    assert [t.question for t in got] == ["질문 4", "질문 5"]


def test_unknown_session_gives_empty_history():
    assert asyncio.run(load_history(FakeSource(None), SID, max_turns=3, max_tokens=2000)) == []


def test_turned_off_does_not_touch_the_source():
    source = FakeSource([_turn(1)])
    assert asyncio.run(load_history(source, SID, max_turns=0, max_tokens=2000)) == []
    assert source.calls == []


def test_defaults_come_from_environment(monkeypatch):
    monkeypatch.setenv(ENV_HISTORY_MAX_TURNS, "1")
    source = FakeSource([_turn(n) for n in range(1, 4)])
    got = asyncio.run(load_history(source, SID))
    assert source.calls == [(SID, 1)] and [t.question for t in got] == ["질문 3"]


def test_read_failure_is_raised_for_the_caller_to_handle():
    with pytest.raises(ConnectionError):
        asyncio.run(load_history(FakeSource(error=ConnectionError("db down")), SID, max_turns=3, max_tokens=2000))
