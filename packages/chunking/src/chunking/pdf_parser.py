"""PDF 페이지를 구역(문서 제목·장 제목·소제목·설명·표·메모·정리)으로 나눈다.

pdfplumber 로 표를 표(행·칸)로 읽고, 글자 크기로 나머지 구역을 구분한다.
pypdf 처럼 글자만 뽑으면 칸 구분과 글자 크기가 사라져 줄 길이·"다." 같은 추측 규칙이 필요했고,
문서마다 예외가 생겼다(표를 못 찾은 페이지 29쪽, 표에 정리 문단이 붙은 페이지 1,100쪽).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# 해운 Intermediate PDF 의 글자 크기 (IS01·IS04·IS12 에서 확인, 50개 문서 공통)
SUBTITLE_SIZE = 15.0  # 16.0: 페이지 소제목
BODY_SIZE = 10.0  # 10.2: 설명·표 제목·정리 본문. 이보다 작으면 메모(8.6, 9.2)
TITLE_SIZE = 8.5  # 문서 제목
SECTION_SIZE = 7.4  # 장 제목
FOOTER_SIZE = 7.5  # 꼬리말 "9 / 80" (버림)
# 8.0(머리말 첫 줄 "IS12 | 팀명")은 어떤 조건에도 걸리지 않아 버려진다.


@dataclass
class PageStructure:
    """한 페이지를 구역별로 나눈 결과. 모듈 내부 중간 데이터다."""

    page: int  # 첫 페이지 = 1
    title: str = ""
    section: str = ""
    subtitle: str = ""
    intro: str = ""
    table_title: str = ""
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    memo: str = ""
    summary: str = ""
    table_count: int = 0


def _is_hangul(char: str) -> bool:
    return "가" <= char <= "힣"


def join_lines(lines: list[str]) -> str:
    """페이지 폭에서 꺾인 줄을 잇는다. 한글-한글 사이는 붙이고 나머지는 공백으로 잇는다.

    PDF 에 줄 끝 공백 정보가 없어 완벽하지 않다(원래 띄어 쓴 "공식 부분"이 "공식부분"이 되는 곳이 있다).
    """
    text = ""
    for line in lines:
        if text and _is_hangul(text[-1]) and _is_hangul(line[0]):
            text += line
        elif text:
            text += " " + line
        else:
            text = line
    return text


_WRAPPED_PART = re.compile(r"[A-Za-z0-9.\-]+")  # 칸 폭 때문에 다음 줄로 넘어간 이메일 조각 ("mple")


def _clean_cell(cell: str | None) -> str:
    """칸 안의 줄을 잇는다.

    칸 안의 줄바꿈은 서로 다른 값(화주와 화물 등)을 나누는 경우가 많아 공백으로 잇는다.
    단, 앞줄 끝 단어가 이메일(@ 포함)이고 다음 줄이 영문·숫자·점 조각이면 칸 폭 때문에 꺾인 것이라
    공백 없이 붙인다 ("vgm@gaonroute.exa" + "mple" → "vgm@gaonroute.example").
    """
    text = ""
    for line in (cell or "").splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        if text and "@" in text.rsplit(" ", 1)[-1] and _WRAPPED_PART.fullmatch(line):
            text += line
        else:
            text = f"{text} {line}" if text else line
    return text


def read_page(page: pdfplumber.page.Page, page_number: int) -> PageStructure:
    tables = page.find_tables()
    table = tables[0] if tables else None
    table_top, table_bottom = (table.bbox[1], table.bbox[3]) if table else (0.0, 0.0)

    s = PageStructure(page=page_number, table_count=len(tables))
    above: list[str] = []
    memo: list[str] = []
    summary: list[str] = []

    for line in page.extract_text_lines():
        text = line["text"].strip()
        size = round(line["chars"][0]["size"], 1)
        if table and line["top"] >= table_top - 1 and line["bottom"] <= table_bottom + 1:
            continue  # 표 안의 글자는 아래에서 표로 따로 읽는다
        if size >= SUBTITLE_SIZE:
            s.subtitle = text
        elif size == TITLE_SIZE:
            s.title = text
        elif size == SECTION_SIZE:
            s.section = text
        elif size >= BODY_SIZE:
            if table and line["top"] >= table_bottom:
                summary.append(text)  # 표 아래 본문 크기 = 정리
            else:
                above.append(text)  # 표 위 본문 크기 = 설명 (+ 표 제목)
        elif table and line["top"] >= table_bottom and size > SECTION_SIZE and size != FOOTER_SIZE:
            memo.append(text)  # 표 아래 작은 글자 = 메모

    if table:
        rows = [[_clean_cell(cell) for cell in row] for row in table.extract()]
        if rows:
            s.header, s.rows = rows[0], rows[1:]
        s.table_title = above.pop() if above else ""  # 표 바로 위 한 줄은 표 제목

    s.intro = join_lines(above) if above else ""
    s.memo = join_lines(memo) if memo else ""
    s.summary = join_lines(summary) if summary else ""
    return s


def read_pdf(path: Path) -> list[PageStructure]:
    """PDF 한 개를 페이지별 구역으로 읽는다. 읽지 못하면 pdfplumber 의 예외가 그대로 올라간다."""
    with pdfplumber.open(path) as pdf:
        return [read_page(page, number) for number, page in enumerate(pdf.pages, start=1)]
