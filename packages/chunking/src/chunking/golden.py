"""제공 평가 파일 → GoldenItem (GoldenDatasetProvider 계약 구현).

- EVALUATION_DIR(기본 ./data/evaluation)의 정답 파일을 읽는다: development.json · additional.json ·
  security_tasks.json (Basic 에만 있는 expansion_validation.json 은 있으면 읽는다).
- 필드 매핑은 scripts/check_dataset_mapping.py 의 raw_to_golden() 과 같다.
- 점검: id 전체 유일, 질문 파일(*_questions.json)과 id·질문 일치,
  DOCUMENTS_DIR(기본 ./data/documents)가 있으면 근거의 book_id·page 가 실제 PDF 범위 안인지.
  어긋나면 IngestError 로 알린다 (평가 기준이 틀린 채로 점수를 내지 않게).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from common.errors import IngestError
from common.types import EvidenceRef, ExpectedAction, GoldenItem, GradingSpec, SecurityInfo, Split

ANSWER_FILES = {
    Split.DEVELOPMENT: "development.json",
    Split.ADDITIONAL: "additional.json",
    Split.EXPANSION_VALIDATION: "expansion_validation.json",
    Split.SECURITY: "security_tasks.json",
}
QUESTION_FILES = {
    Split.DEVELOPMENT: "development_questions.json",
    Split.ADDITIONAL: "additional_questions.json",
    Split.EXPANSION_VALIDATION: "expansion_validation_questions.json",
    Split.SECURITY: "security_questions.json",
}


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


def _read_json(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestError(f"평가 파일을 읽지 못했다: {path} ({exc})") from exc


class EvaluationGoldenProvider:
    def __init__(self, evaluation_dir: Path | None = None, documents_dir: Path | None = None) -> None:
        self._evaluation_dir = evaluation_dir or Path(os.environ.get("EVALUATION_DIR", "./data/evaluation"))
        self._documents_dir = documents_dir or Path(os.environ.get("DOCUMENTS_DIR", "./data/documents"))
        self._page_counts: dict[str, int] | None = None

    def load(self, splits: Sequence[Split] | None = None) -> list[GoldenItem]:
        wanted = list(splits) if splits is not None else [s for s in Split if s is not Split.SECURITY]
        items: list[GoldenItem] = []
        for split in Split:  # 순서를 고정한다 (fingerprint 가 같은 값이 되도록)
            if split not in wanted:
                continue
            path = self._evaluation_dir / ANSWER_FILES[split]
            if not path.is_file():
                if split is Split.EXPANSION_VALIDATION and splits is None:
                    continue  # Basic 난이도에만 있는 파일
                raise IngestError(f"평가 파일이 없다: {path}")
            split_items = [raw_to_golden(raw, split) for raw in _read_json(path)]
            self._check_questions(split, split_items)
            items += split_items

        ids = [i.id for i in items]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise IngestError(f"중복 문항 id: {duplicated}")
        self._check_evidence_range(items)
        return items

    def fingerprint(self, splits: Sequence[Split] | None = None) -> str:
        payload = json.dumps([i.model_dump(mode="json") for i in self.load(splits)], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ── 점검 ──────────────────────────────────────────────────────────
    def _check_questions(self, split: Split, items: list[GoldenItem]) -> None:
        """질문만 든 *_questions.json 이 있으면 정답 파일과 id·질문이 같은지 확인한다."""
        path = self._evaluation_dir / QUESTION_FILES[split]
        if not path.is_file():
            return
        questions = {q["id"]: q["question"] for q in _read_json(path)}
        answers = {i.id: i.question for i in items}
        if questions != answers:
            mismatched = sorted(k for k in questions.keys() | answers.keys() if questions.get(k) != answers.get(k))
            raise IngestError(f"{path.name} 와 정답 파일의 id·질문이 다르다: {mismatched[:5]}")

    def _check_evidence_range(self, items: list[GoldenItem]) -> None:
        """문서 폴더가 있으면 근거의 book_id·page 가 실제 PDF 범위 안인지 확인한다."""
        if not self._documents_dir.is_dir():
            return
        if self._page_counts is None:
            import pdfplumber

            self._page_counts = {}
            for path in sorted(self._documents_dir.glob("*.pdf")):
                with pdfplumber.open(path) as pdf:
                    self._page_counts[path.stem] = len(pdf.pages)
        for item in items:
            for group in item.evidence_groups:
                for e in group:
                    pages = self._page_counts.get(e.book_id)
                    if pages is None or not 1 <= e.page <= pages:
                        raise IngestError(f"{item.id}: 근거 {e.book_id} {e.page}쪽이 PDF 범위 밖이다")
