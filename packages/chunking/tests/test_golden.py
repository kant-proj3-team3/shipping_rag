"""골든셋 단위 테스트. 임시 평가 파일로 돈다."""

import json
from pathlib import Path

import pytest

import chunking
from chunking.golden import EvaluationGoldenProvider
from common.errors import IngestError
from common.interfaces import GoldenDatasetProvider
from common.types import Split

# ── 골든셋 ────────────────────────────────────────────────────────────
def _raw(i, book="IS01", page=1):
    return {
        "id": i, "question": f"{i} 질문", "expected_action": "answer", "reference_answer": "답",
        "required_facts": ["사실"], "evidence_groups": [[{"book_id": book, "page": page, "quote": "원문"}]],
    }


def _eval_dir(tmp_path, dev, add=None, questions=True) -> Path:
    d = tmp_path / "evaluation"
    d.mkdir()
    files = {"development": dev, "additional": add if add is not None else [_raw("A-01")]}
    for name, items in files.items():
        (d / f"{name}.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        if questions:
            qs = [{"id": r["id"], "question": r["question"]} for r in items]
            (d / f"{name}_questions.json").write_text(json.dumps(qs, ensure_ascii=False), encoding="utf-8")
    return d


def test_golden_provider_maps_files(tmp_path):
    provider = EvaluationGoldenProvider(_eval_dir(tmp_path, [_raw("D-01")]), documents_dir=tmp_path / "no-docs")
    assert isinstance(provider, GoldenDatasetProvider)
    items = provider.load()
    assert [i.id for i in items] == ["D-01", "A-01"]  # security 는 기본 제외
    assert items[0].split is Split.DEVELOPMENT and items[0].evidence_groups[0][0].book_id == "IS01"
    assert items[0].grading.required_facts == ["사실"]
    assert provider.fingerprint() == provider.fingerprint()
    assert provider.fingerprint([Split.DEVELOPMENT]) != provider.fingerprint()


def test_golden_provider_rejects_duplicate_ids(tmp_path):
    provider = EvaluationGoldenProvider(_eval_dir(tmp_path, [_raw("X")], add=[_raw("X")]), documents_dir=tmp_path / "no")
    with pytest.raises(IngestError):
        provider.load()


def test_golden_provider_checks_question_files(tmp_path):
    d = _eval_dir(tmp_path, [_raw("D-01")])
    (d / "development_questions.json").write_text(json.dumps([{"id": "D-01", "question": "다른 질문"}]), encoding="utf-8")
    with pytest.raises(IngestError):
        EvaluationGoldenProvider(d, documents_dir=tmp_path / "no").load()


def test_golden_provider_requires_security_file_when_asked(tmp_path):
    provider = EvaluationGoldenProvider(_eval_dir(tmp_path, [_raw("D-01")]), documents_dir=tmp_path / "no")
    with pytest.raises(IngestError):
        provider.load([Split.SECURITY])


# ── 진입점 ────────────────────────────────────────────────────────────
def test_entrypoint_switches_to_real_golden_provider(monkeypatch):
    monkeypatch.setenv("CHUNKING_IMPL", "real")
    assert isinstance(chunking.create_golden_provider(), EvaluationGoldenProvider)


def test_default_golden_provider_is_mock(monkeypatch):
    monkeypatch.delenv("CHUNKING_IMPL", raising=False)
    assert not isinstance(chunking.create_golden_provider(), EvaluationGoldenProvider)
