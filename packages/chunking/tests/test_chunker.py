"""청킹 단위 테스트 (pdfplumber 구조 → Chunk). PDF 없이 가짜 페이지 구역으로 돈다."""

from chunking.chunker import chunk_page, pack_items
from chunking.pdf_parser import PageStructure, _clean_cell, join_lines
from common.types import Chunk

# ── 청킹 ──────────────────────────────────────────────────────────────
def _page(page=9, rows=8) -> PageStructure:
    return PageStructure(
        page=page,
        title="N1 터미널 보관료 요율 자료집",
        section="기본 요율 행",
        subtitle="기본 요율 원문",
        intro="20GP는 무료기간 3일이다. 40GP는 무료기간 4일이다.",
        table_title="기본 요율 원문 — 업무 확인 대장",
        header=["업무 기록번호", "대상", "확인 항목", "일자·원자료", "처리 상태"],
        rows=[[f"IS12-009-0{i}", "해솔무역 40GP / N1", "STD / 2027-01-01", "기본 4일 USD 68/일", "확인"] for i in range(1, rows + 1)],
        memo="접수일이나 청구일을 실제 양하일로 해석하지 않는다.",
        summary="이 표의 20GP·STD 행을 사용한다. 반출일 미확인이어도 조회할 수 있다.",
        table_count=1,
    )


def test_chunk_page_order_ids_and_schema():
    chunks = chunk_page("IS12", "IS12.pdf", _page())
    assert [c.metadata["kind"] for c in chunks] == ["intro", "table", "memo", "summary"]
    assert [c.chunk_id for c in chunks] == [f"IS12-p9-c{i}" for i in range(1, 5)]
    for c in chunks:
        assert c.page_start == c.page_end == 9 and c.title == "N1 터미널 보관료 요율 자료집"
        assert c.text.startswith("[N1 터미널 보관료 요율 자료집 > 기본 요율 행 > 기본 요율 원문]")
        Chunk.model_validate(c.model_dump(mode="json"))  # payload 로 저장했다가 그대로 복원된다


def test_chunk_ids_are_deterministic():
    a = chunk_page("IS12", "IS12.pdf", _page())
    b = chunk_page("IS12", "IS12.pdf", _page())
    assert a == b


def test_long_table_is_split_by_rows_with_header_repeated():
    chunks = [c for c in chunk_page("IS12", "IS12.pdf", _page(rows=30), max_chars=400) if c.metadata["kind"] == "table"]
    assert len(chunks) > 1
    for c in chunks:
        lines = c.text.split("\n")
        assert lines[2] == "업무 기록번호 | 대상 | 확인 항목 | 일자·원자료 | 처리 상태"  # 맥락 줄, 표 제목 다음에 머리글
        assert all(line.startswith("IS12-009-") for line in lines[3:])  # 행이 중간에 잘리지 않는다


def test_pack_items_keeps_single_oversized_item_whole():
    assert pack_items(["가" * 50], ["head"], max_chars=10) == ["head\n" + "가" * 50]


def test_join_lines_rule():
    assert join_lines(["무료기", "간은 3일", "USD", "68"]) == "무료기간은 3일 USD 68"


def test_clean_cell_joins_email_wrapped_by_cell_width():
    # 칸 폭 때문에 꺾인 이메일은 붙이고, 서로 다른 값은 지금처럼 공백으로 잇는다
    assert _clean_cell("vgm@gaonroute.exa\nmple") == "vgm@gaonroute.example"
    assert _clean_cell("docs@gaonroute.\nexample") == "docs@gaonroute.example"
    assert _clean_cell("GR26-P0670\nP26-20-0670") == "GR26-P0670 P26-20-0670"
    assert _clean_cell("20GP\n최초 2026-10-25") == "20GP 최초 2026-10-25"
    assert _clean_cell("vgm@gaonroute.example\n접수 완료") == "vgm@gaonroute.example 접수 완료"
    assert _clean_cell(None) == ""
