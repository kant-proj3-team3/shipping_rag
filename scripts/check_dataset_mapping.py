"""제공 데이터(PDF + 평가 JSON)가 계약 타입으로 빠짐없이 표현되는지, 근거 인용이 실제 PDF와 맞는지 검사한다.

실행:  python scripts/check_dataset_mapping.py --documents DIR/documents --evaluation DIR/evaluation
(압축 4개를 풀어 documents/ 를 한 폴더로 합친 뒤 실행한다. 개발용 도구이며 pypdf 가 필요하다.)

raw_to_golden() 은 청킹 담당자가 GoldenDatasetProvider 를 구현할 때 그대로 참고할 수 있는 매핑이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

from common.types import (
    EvidenceRef,
    ExpectedAction,
    GoldenItem,
    GradingSpec,
    SecurityInfo,
    Split,
)

# 정답이 든 파일 → split. 질문만 든 *_questions.json 은 짝 검사에만 쓴다.
FILES = {"development": "development.json", "additional": "additional.json", "security": "security_tasks.json"}


def raw_to_golden(raw: dict, split: Split) -> GoldenItem:
    security = None
    if split is Split.SECURITY:
        security = SecurityInfo(
            attack_type=raw["attack_type"],
            external_source_id=raw["external_source_id"],
            source_page=raw["source_page"],
            attack_text=raw["attack_text"],
            bad_claims=raw.get("bad_claims", []),
        )
    return GoldenItem(
        id=raw["id"],
        split=split,
        question=raw["question"],
        expected_action=ExpectedAction(raw["expected_action"]),
        reference_answer=raw.get("reference_answer"),
        evidence_groups=[
            [EvidenceRef(book_id=e["book_id"], page=e["page"], quote=e.get("quote")) for e in group]
            for group in raw.get("evidence_groups", [])
        ],
        grading=GradingSpec(
            required_facts=raw.get("required_facts", []),
            forbidden_claims=raw.get("forbidden_claims", []),
            conditions=raw.get("conditions", []),
            grading_notes=raw.get("grading_notes"),
        ),
        security=security,
    )


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", type=Path, required=True)
    ap.add_argument("--evaluation", type=Path, required=True)
    args = ap.parse_args()

    pages = {p.stem: [(pg.extract_text() or "") for pg in PdfReader(p).pages] for p in sorted(args.documents.glob("*.pdf"))}
    print(f"문서 {len(pages)}개, 페이지 {sum(len(v) for v in pages.values())}개")

    problems: list[str] = []
    items: list[GoldenItem] = []
    for name, fname in FILES.items():
        raws = json.loads((args.evaluation / fname).read_text(encoding="utf-8"))
        qs = json.loads((args.evaluation / f"{name}_questions.json").read_text(encoding="utf-8"))
        if [(x["id"], x["question"]) for x in raws] != [(x["id"], x["question"]) for x in qs]:
            problems.append(f"{name}: 정답 파일과 질문 파일이 다르다")
        for raw in raws:
            try:
                items.append(raw_to_golden(raw, Split(name)))
            except Exception as e:  # noqa: BLE001
                problems.append(f"{raw.get('id')}: 계약 타입으로 표현 불가 — {e}")

    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        problems.append("id 중복")
    for it in items:
        for g in it.evidence_groups:
            for e in g:
                if e.book_id not in pages or not 1 <= e.page <= len(pages[e.book_id]):
                    problems.append(f"{it.id}: 근거 위치가 범위 밖 {e.book_id} p{e.page}")
                elif e.quote and norm(e.quote) not in norm(pages[e.book_id][e.page - 1]):
                    problems.append(f"{it.id}: 인용이 {e.book_id} p{e.page} 에 없다")
        if it.security:
            s = it.security
            if s.external_source_id not in pages or norm(s.attack_text) not in norm(pages[s.external_source_id][s.source_page - 1]):
                problems.append(f"{it.id}: 공격 문구가 {s.external_source_id} p{s.source_page} 에 없다")

    by_split = {n: sum(1 for i in items if i.split.value == n) for n in FILES}
    acts = {a.value: sum(1 for i in items if i.expected_action is a) for a in ExpectedAction}
    groups = [len(i.evidence_groups) for i in items if i.evidence_groups]
    refs = sum(len(g) for i in items for g in i.evidence_groups)
    print(f"문항 {len(items)}개 {by_split} | 동작 {acts}")
    print(f"근거 있는 문항 {len(groups)}개, 그룹 수 최대 {max(groups, default=0)}, 근거 {refs}곳, OR 그룹 {sum(1 for i in items for g in i.evidence_groups if len(g) > 1)}개")
    if problems:
        print("\n문제", len(problems), "건")
        for p in problems[:30]:
            print(" -", p)
        return 1
    print("문제 없음: 모든 문항이 계약 타입으로 표현되고 모든 근거 인용이 실제 페이지와 일치한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
