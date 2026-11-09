import pytest

from backend.context import (
    DEFAULT_CONTEXT_MAX_TOKENS,
    ENV_CONTEXT_MAX_TOKENS,
    build_context,
    context_max_tokens,
)
from backend.prompts import render_prompt
from common.types import Chunk, RetrievedChunk


def _rc(rank: int, text: str = "본문", *, ps: int = 1, pe: int | None = None, title: str | None = "문서") -> RetrievedChunk:
    return RetrievedChunk(
        rank=rank,
        score=1.0 / rank,
        chunk=Chunk(
            chunk_id=f"c{rank}",
            book_id="IS01",
            file_name="IS01.pdf",
            title=title,
            page_start=ps,
            page_end=pe if pe is not None else ps,
            text=text,
        ),
    )


# ── 빈 입력 ──
def test_empty_input_gives_empty_context():
    out = build_context([], max_tokens=100)
    assert out.is_empty
    assert out.items == [] and out.text == ""
    assert out.count_before == 0 and out.count_after == 0 and out.dropped_chunk_ids == []


def test_first_chunk_over_budget_gives_empty_context():
    out = build_context([_rc(1, "가" * 500)], max_tokens=50)
    assert out.is_empty
    assert out.dropped_chunk_ids == ["c1"]
    assert (out.count_before, out.count_after) == (1, 0)


# ── 예산 경계 ──
def test_all_kept_within_budget_and_ids_sequential():
    out = build_context([_rc(1), _rc(2), _rc(3)], max_tokens=10_000)
    assert [i.source_id for i in out.items] == ["S1", "S2", "S3"]
    assert out.dropped_chunk_ids == []
    assert (out.count_before, out.count_after) == (3, 3)


def test_budget_boundary_exact_fit_and_one_less():
    rcs = [_rc(1, "가" * 20), _rc(2, "나" * 20)]
    full = build_context(rcs, max_tokens=10_000)
    exact = build_context(rcs, max_tokens=full.token_count)
    assert exact.count_after == 2
    less = build_context(rcs, max_tokens=full.token_count - 1)
    assert less.count_after == 1
    assert less.dropped_chunk_ids == ["c2"]


def test_drops_lowest_rank_first_and_never_skips_to_smaller_later_chunk():
    rcs = [_rc(1, "가" * 10), _rc(2, "나" * 500), _rc(3, "다" * 5)]
    out = build_context(rcs, max_tokens=120)
    assert [i.chunk.chunk_id for i in out.items] == ["c1"]
    assert out.dropped_chunk_ids == ["c2", "c3"]  # 작은 c3 로 건너뛰지 않는다


def test_chunks_are_never_cut_in_the_middle():
    text = "가" * 100
    out = build_context([_rc(1, text), _rc(2, "나" * 100)], max_tokens=150)
    assert [i.chunk.text for i in out.items] == [text]
    assert "나" not in out.text


def test_custom_token_counter_is_used():
    out = build_context([_rc(1), _rc(2)], max_tokens=1, count_tokens=lambda s: 1 if s != "\n\n" else 0)
    assert out.count_after == 1
    assert out.token_count == 1


def test_invalid_budget_rejected():
    with pytest.raises(ValueError):
        build_context([_rc(1)], max_tokens=0)


# ── 여러 페이지 / 표기 ──
def test_multi_page_chunk_keeps_page_range():
    out = build_context([_rc(1, ps=3, pe=5), _rc(2, ps=7)], max_tokens=10_000)
    assert "p.3-5" in out.text
    assert "p.7" in out.text and "p.7-" not in out.text


def test_header_has_file_name_and_page_but_not_title():
    # 제목은 청커가 본문에 이미 넣으므로 헤더에서 반복하지 않는다
    for title in ("보관료 안내", None):
        text = build_context([_rc(1, "본문", title=title)], max_tokens=10_000).text
        assert text == "[S1] IS01.pdf p.1\n본문"


# ── 순서 / 일관성 ──
def test_order_follows_rank_even_if_input_unsorted():
    out = build_context([_rc(3), _rc(1), _rc(2)], max_tokens=10_000)
    assert [i.chunk.chunk_id for i in out.items] == ["c1", "c2", "c3"]


def test_items_and_text_come_from_same_chunks():
    rcs = [_rc(i, f"내용{i}" * 30) for i in range(1, 6)]
    full = build_context(rcs, max_tokens=10_000)
    out = build_context(rcs, max_tokens=full.token_count - 1)
    kept_ids = {i.chunk.chunk_id for i in out.items}
    for r in rcs:
        assert (r.chunk.text.strip() in out.text) == (r.chunk.chunk_id in kept_ids)
    for item in out.items:
        assert f"[{item.source_id}]" in out.text
    assert out.count_after + len(out.dropped_chunk_ids) == out.count_before


def test_text_feeds_render_prompt_unchanged():
    out = build_context([_rc(1, "보관료는 1일당 10,000원")], max_tokens=10_000)
    assert "보관료는 1일당 10,000원" in render_prompt("질문", out.text).user


# ── 환경변수 ──
def test_context_max_tokens_env(monkeypatch):
    monkeypatch.delenv(ENV_CONTEXT_MAX_TOKENS, raising=False)
    assert context_max_tokens() == DEFAULT_CONTEXT_MAX_TOKENS
    monkeypatch.setenv(ENV_CONTEXT_MAX_TOKENS, "5000")
    assert context_max_tokens() == 5000
    for bad in ("abc", "0", "-3", ""):
        monkeypatch.setenv(ENV_CONTEXT_MAX_TOKENS, bad)
        assert context_max_tokens() == DEFAULT_CONTEXT_MAX_TOKENS
