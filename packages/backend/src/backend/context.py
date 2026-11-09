"""검색 결과를 모델 문맥으로 바꾼다.

여기서 만든 ContextItem 목록이 곧 final_context 이고, 모델에 주는 문자열도 같은 목록에서 만든다.
토큰 예산은 문맥 전용이다. 예산을 인자로 받으므로 나중에 대화 이력 등이 입력에 들어와도
호출자가 남은 예산을 계산해 넘기면 이 모듈은 바뀌지 않는다.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from common.types import Chunk, ContextItem, RetrievedChunk

ENV_CONTEXT_MAX_TOKENS = "CONTEXT_MAX_TOKENS"
# 임시 기본값. 팀이 정하면 환경변수로 바꾼다(코드 수정 없음).
DEFAULT_CONTEXT_MAX_TOKENS = 12_000

TokenCounter = Callable[[str], int]


def approx_token_count(text: str) -> int:
    """의존성 없는 보수적 근사: 1글자를 1토큰으로 센다(한국어에서 실제보다 크게 잡힌다)."""
    return len(text)


def context_max_tokens() -> int:
    """환경변수에서 문맥 예산을 읽는다. 없거나 잘못된 값이면 기본값."""
    raw = os.environ.get(ENV_CONTEXT_MAX_TOKENS, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CONTEXT_MAX_TOKENS
    return value if value > 0 else DEFAULT_CONTEXT_MAX_TOKENS


@dataclass(frozen=True)
class ContextBuild:
    """문맥 빌더 결과. items 와 text 는 같은 청크 집합에서 만들어진다."""

    items: list[ContextItem] = field(default_factory=list)  # final_context
    text: str = ""  # 모델에 주는 문맥 문자열
    dropped_chunk_ids: list[str] = field(default_factory=list)  # 예산 때문에 제외된 chunk_id (rank 순)
    count_before: int = 0  # 예산 적용 전 청크 수
    count_after: int = 0  # 예산 적용 후 청크 수
    token_count: int = 0  # text 의 토큰 수(주입된 카운터 기준)

    @property
    def is_empty(self) -> bool:
        return not self.items


def _page_label(chunk: Chunk) -> str:
    if chunk.page_start == chunk.page_end:
        return f"p.{chunk.page_start}"
    return f"p.{chunk.page_start}-{chunk.page_end}"


def _header(source_id: str, chunk: Chunk) -> str:
    """출처 표기(파일명·페이지). 여러 페이지에 걸친 청크는 범위를 그대로 남긴다.

    문서 제목은 넣지 않는다: 청커가 본문 첫 줄에 `[제목 > 섹션 > 소제목]`을 이미 붙인다.
    """
    return f"[{source_id}] {chunk.file_name} {_page_label(chunk)}"


def _render_block(source_id: str, chunk: Chunk) -> str:
    return f"{_header(source_id, chunk)}\n{chunk.text.strip()}"


_SEPARATOR = "\n\n"


def build_context(
    retrieved: Sequence[RetrievedChunk],
    *,
    max_tokens: int,
    count_tokens: TokenCounter = approx_token_count,
) -> ContextBuild:
    """rank 순으로 청크를 담고, 예산을 넘는 첫 청크부터 뒤(낮은 순위)는 모두 제외한다.

    - 청크는 통째로 유지하거나 통째로 뺀다(중간에서 자르지 않는다). 표 제목·단위·각주·적용일은 청크 본문에 있다.
    - source_id 는 최종 유지된 청크에 S1 부터 연속으로 붙는다.
    - 빈 입력, 또는 첫 청크부터 예산을 넘으면 빈 문맥이다(호출자는 모델을 부르지 않고 abstained 로 처리한다).
    """
    if max_tokens < 1:
        raise ValueError("max_tokens 는 1 이상이어야 한다")

    ordered = sorted(retrieved, key=lambda r: r.rank)  # 안정 정렬: 같은 rank 는 입력 순서 유지
    items: list[ContextItem] = []
    blocks: list[str] = []
    used = 0
    kept = 0

    for r in ordered:
        source_id = f"S{kept + 1}"
        block = _render_block(source_id, r.chunk)
        cost = count_tokens(block) + (count_tokens(_SEPARATOR) if blocks else 0)
        if used + cost > max_tokens:
            break
        items.append(ContextItem(source_id=source_id, chunk=r.chunk))
        blocks.append(block)
        used += cost
        kept += 1

    dropped = [r.chunk.chunk_id for r in ordered[kept:]]
    return ContextBuild(
        items=items,
        text=_SEPARATOR.join(blocks),
        dropped_chunk_ids=dropped,
        count_before=len(ordered),
        count_after=kept,
        token_count=used,
    )
