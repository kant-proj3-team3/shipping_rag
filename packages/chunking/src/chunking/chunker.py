"""페이지 구역 → 검색 청크(common.types.Chunk).

- 청크는 한 페이지 안에서만 만든다 (데이터 확인 결과 표가 페이지를 넘지 않고, 한 페이지가 한 주제로 끝난다).
- 구역 순서대로 설명(intro) → 표(table) → 메모(memo) → 정리(summary) 청크를 만든다.
- 모든 청크 맨 앞에 "[문서 제목 > 장 제목 > 소제목]" 맥락 한 줄을 붙여, 청크 하나만 검색돼도 무슨 내용인지 알게 한다.
  (오버랩 대신 이 방법을 쓴다. 글자 수로 자르면 표 행이 중간에 잘린다)
- 표는 행을 쪼개지 않고 max_chars 를 넘기 직전까지 담고, 넘치면 새 청크에 맥락 줄 + 표 제목 + 머리글을 다시 붙인다.
- 설명·메모·정리는 문장("다." 뒤 공백) 단위로 같은 방식으로 담는다.
"""

from __future__ import annotations

import re

from common.types import Chunk

from .pdf_parser import PageStructure

DEFAULT_MAX_CHARS = 700  # 청크 최대 글자 수 (e5 토크나이저 기준 512토큰을 넘는 청크 0개로 확인)

_SENTENCE_END = re.compile(r"(?<=다\.)\s+")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s]


def format_row(cells: list[str]) -> str:
    return " | ".join(cells)


def pack_items(items: list[str], head: list[str], max_chars: int) -> list[str]:
    """행이나 문장을 쪼개지 않고, max_chars 를 넘기 직전까지 한 청크에 담는다. 각 청크 앞에는 head 를 붙인다."""
    pieces: list[str] = []
    current: list[str] = []
    for item in items:
        candidate = "\n".join(head + current + [item])
        if current and len(candidate) > max_chars:
            pieces.append("\n".join(head + current))
            current = []
        current.append(item)
    if current:
        pieces.append("\n".join(head + current))
    return pieces


def make_chunk_id(book_id: str, page: int, number: int) -> str:
    """결정적 id: 같은 문서·내용·청킹 조건이면 항상 같은 값이다."""
    return f"{book_id}-p{page}-c{number}"


def chunk_page(book_id: str, file_name: str, s: PageStructure, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    context = f"[{s.title} > {s.section} > {s.subtitle}]"

    parts: list[tuple[str, str]] = []
    if s.intro:
        parts += [("intro", p) for p in pack_items(split_sentences(s.intro), [context], max_chars)]
    if s.rows:
        head = [context, s.table_title, format_row(s.header)]
        parts += [("table", p) for p in pack_items([format_row(r) for r in s.rows], head, max_chars)]
    if s.memo:
        parts += [("memo", p) for p in pack_items(split_sentences(s.memo), [context], max_chars)]
    if s.summary:
        parts += [("summary", p) for p in pack_items(split_sentences(s.summary), [context], max_chars)]

    return [
        Chunk(
            chunk_id=make_chunk_id(book_id, s.page, number),
            book_id=book_id,
            file_name=file_name,
            title=s.title or None,
            page_start=s.page,
            page_end=s.page,  # 청크는 한 페이지 안에서만 만든다
            text=text,
            metadata={"section": s.section, "subtitle": s.subtitle, "kind": kind},
        )
        for number, (kind, text) in enumerate(parts, start=1)
    ]
