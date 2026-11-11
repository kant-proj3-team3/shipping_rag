"""멀티턴(G3): 같은 세션의 이전 대화에서 프롬프트에 넣을 부분을 고른다.

방식
====
세션 이력의 앞선 질문과 답을 **프롬프트에 직접 넣는다**. 질문을 독립 질문으로 다시 쓰는 단계는 없다.
그래서 후속 질문("그럼 초과하면 하루에 얼마야?")의 **검색은 여전히 원문 질문으로** 이뤄진다. 이력은 모델이 지시어와
되물은 조건에 대한 답을 이해하는 데만 쓰이고, 검색 품질은 좋아지지 않는다(알려진 한계).

무엇을 넣나
-----------
- 최근 `HISTORY_MAX_TURNS`(기본 3)턴의 **질문과 답**만 넣는다. 출처·문맥(검색 자료)은 넣지 않는다.
  이전 답변은 근거가 아니라 대화 맥락일 뿐이라는 규칙은 프롬프트(`prompts._HISTORY_RULES`)가 모델에게 알린다.
- 기록된 질문은 이미 이메일·API 키 모양이 가려진 값이다(`qa.py` 가 기록할 때 `redact`).
- `error` 응답은 세션에 기록되지 않으므로 이력에도 없다.

토큰 예산
---------
이력은 **자기 상한**(`HISTORY_MAX_TOKENS`, 기본 2,000)을 따로 갖는다. 문맥 예산(`CONTEXT_MAX_TOKENS`)은 그대로라서
`build_context` 는 바뀌지 않고, 입력 전체는 `시스템 + 이력(≤ 상한) + 질문 + 문맥(≤ 문맥 상한)` 이 된다.
상한은 턴마다 `HISTORY_MAX_TOKENS // HISTORY_MAX_TURNS` 로 나눠, 한 턴이 길면 **그 턴의 답을 잘라**(뒤에 `…`) 맞춘다.
질문만으로 그 몫을 넘는 턴은 넣지 않는다. 토큰 수는 문맥 빌더와 같은 보수적 근사(1글자 = 1토큰)로 센다.

장애
----
이력 조회가 실패하면 호출자(`qa.py`)가 이력 없이 단발로 답하고 경고와 트레이스 표시를 남긴다. 이 모듈은 예외를 그대로 낸다.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Protocol

from backend.context import TokenCounter, approx_token_count
from backend.prompts import HistoryTurn, format_turn
from common.types import SessionInfo, SessionTurn

ENV_HISTORY_MAX_TURNS = "HISTORY_MAX_TURNS"
ENV_HISTORY_MAX_TOKENS = "HISTORY_MAX_TOKENS"
# 임시 기본값. 팀이 정하면 환경변수로 바꾼다(코드 수정 없음).
DEFAULT_HISTORY_MAX_TURNS = 3
DEFAULT_HISTORY_MAX_TOKENS = 2_000

_ELLIPSIS = "…"


class HistorySource(Protocol):
    """이력을 읽는 저장소(`PersistentSessionStore`·목업 저장소). 블로킹 호출이어도 된다: 이 모듈이 스레드로 부른다."""

    def get(self, session_id: str, limit: int) -> SessionInfo | None: ...


def history_max_turns() -> int:
    """넣을 최근 턴 수. 0 이면 멀티턴을 끈다. 없거나 잘못된(음수·숫자 아님) 값이면 기본값."""
    raw = os.environ.get(ENV_HISTORY_MAX_TURNS, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HISTORY_MAX_TURNS
    return value if value >= 0 else DEFAULT_HISTORY_MAX_TURNS


def history_max_tokens() -> int:
    """이력 전용 토큰 상한. 없거나 잘못된(0 이하·숫자 아님) 값이면 기본값."""
    raw = os.environ.get(ENV_HISTORY_MAX_TOKENS, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HISTORY_MAX_TOKENS
    return value if value > 0 else DEFAULT_HISTORY_MAX_TOKENS


def _fit_turn(question: str, answer: str, budget: int, count_tokens: TokenCounter) -> HistoryTurn | None:
    """한 턴을 예산에 맞춘다. 길면 답을 잘라 `…` 를 붙이고, 질문만으로 넘으면 None(넣지 않는다)."""
    if count_tokens(format_turn(question, answer)) <= budget:
        return HistoryTurn(question, answer)
    if count_tokens(format_turn(question, _ELLIPSIS)) > budget:
        return None
    lo, hi = 0, len(answer)  # 예산 안에 들어가는 가장 긴 답의 앞부분(이진 탐색)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(format_turn(question, answer[:mid].rstrip() + _ELLIPSIS)) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return HistoryTurn(question, answer[:lo].rstrip() + _ELLIPSIS)


def select_history(
    turns: Sequence[SessionTurn],
    *,
    max_turns: int,
    max_tokens: int,
    count_tokens: TokenCounter = approx_token_count,
) -> list[HistoryTurn]:
    """세션의 턴(오래된 것 → 최신 순)에서 프롬프트에 넣을 이전 대화를 고른다. 순서는 그대로다."""
    if max_turns <= 0 or max_tokens <= 0 or not turns:
        return []
    per_turn = max_tokens // max_turns  # 턴마다 같은 몫. 합계는 항상 max_tokens 이하다
    selected: list[HistoryTurn] = []
    for turn in turns[-max_turns:]:
        fitted = _fit_turn(turn.question, turn.answer, per_turn, count_tokens)
        if fitted is not None:
            selected.append(fitted)
    return selected


async def load_history(
    source: HistorySource,
    session_id: str,
    *,
    max_turns: int | None = None,
    max_tokens: int | None = None,
    count_tokens: TokenCounter = approx_token_count,
) -> list[HistoryTurn]:
    """세션 이력을 읽어 프롬프트에 넣을 이전 대화를 고른다. 없는 세션이면 빈 목록이다. 조회 실패는 그대로 던진다."""
    turns_limit = history_max_turns() if max_turns is None else max_turns
    if turns_limit <= 0:
        return []
    info = await asyncio.to_thread(source.get, session_id, turns_limit)  # 저장소가 블로킹이라 루프 밖에서 부른다
    if info is None:
        return []
    return select_history(
        info.turns,
        max_turns=turns_limit,
        max_tokens=history_max_tokens() if max_tokens is None else max_tokens,
        count_tokens=count_tokens,
    )


__all__ = [
    "HistorySource",
    "history_max_tokens",
    "history_max_turns",
    "load_history",
    "select_history",
]
