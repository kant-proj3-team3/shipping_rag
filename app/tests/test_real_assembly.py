"""app 의 실제 구현 조립과 평가 러너 테스트. 외부 서비스(Qdrant·모델·DB)는 쓰지 않는다.

- 기본(`APP_IMPL` 없음)은 실제 구현을 고르고, `APP_IMPL=mock` 과 모듈별 `*_IMPL` 이 우선하는지 확인한다.
- 러너는 목업 모듈 + 가짜 체인으로 끝까지 돌려 보고서의 모양·분모·설정 기록을 확인한다.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

import backend
from app import cli, runner
from app.api import create_app
from app.wiring import MODULE_IMPL_VARS, apply_impl_default, index_name
from backend.chain import AnswerChain, ChainConfig
from backend.prompts import ModelOutput
from common.errors import InvalidInputError
from common.types import (
    AnswerStatus,
    QueryMeta,
    QueryResponse,
    QAResult,
    RetrievalMode,
    Score,
    ScoreState,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "no-such.env"))
    monkeypatch.setenv("MOCK_INDEX_DIR", str(tmp_path / "idx"))
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("INDEX_NAME", "test-index")
    monkeypatch.delenv("MOCK_INDEX_READY", raising=False)
    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    # apply_impl_default 가 새로 만드는 환경변수가 다른 테스트로 새지 않도록, 지금 값을 기록해 두고 끝나면 되돌린다
    for var in ("APP_IMPL", *MODULE_IMPL_VARS):
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)


# ── 구현 선택 ──
def test_default_is_real_for_all_three_modules():
    assert apply_impl_default() == "real"
    assert [os.environ[v] for v in MODULE_IMPL_VARS] == ["real", "real", "real"]


def test_app_impl_mock_selects_mocks(monkeypatch):
    monkeypatch.setenv("APP_IMPL", " Mock ")
    assert apply_impl_default() == "mock"
    assert [os.environ[v] for v in MODULE_IMPL_VARS] == ["mock", "mock", "mock"]


def test_module_specific_value_wins_over_app_impl(monkeypatch):
    monkeypatch.setenv("BACKEND_IMPL", "mock")
    apply_impl_default()
    assert os.environ["BACKEND_IMPL"] == "mock"
    assert os.environ["CHUNKING_IMPL"] == os.environ["RETRIEVAL_IMPL"] == "real"


def test_invalid_app_impl_is_rejected(monkeypatch):
    monkeypatch.setenv("APP_IMPL", "maybe")
    with pytest.raises(InvalidInputError, match="APP_IMPL"):
        apply_impl_default()


def test_create_app_applies_the_default_before_building(monkeypatch):
    monkeypatch.setenv("APP_IMPL", "mock")
    create_app()
    assert os.environ["CHUNKING_IMPL"] == "mock"


def test_real_assembly_builds_real_services_without_external_calls(monkeypatch):
    """실제 구현으로 조립해도 키·DB 없이 서비스 객체는 만들어진다(연결은 첫 사용 때)."""
    from backend.evaluator import BackendAnswerEvaluator
    from backend.qa import BackendQAService
    from retrieval.evaluator import GroupRetrievalEvaluator

    from app.wiring import build_services
    from common.types import IndexManifest
    from datetime import UTC, datetime

    apply_impl_default()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CACHE_ENABLED", "false")

    class FakeEmbedder:
        embedder_id = "e"
        dimension = 4
        max_input_tokens = 512

        def count_tokens(self, t):
            return len(t)

        def embed_passages(self, texts):
            return [[0.0] * 4 for _ in texts]

        def embed_query(self, t):
            return [0.0] * 4

    manifest = IndexManifest(
        index_name="t", embedder_id="e", embedding_dim=4, document_count=1, chunk_count=1,
        fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
    )

    class Base:
        embedder = FakeEmbedder()

    # 실제 retrieval 은 Qdrant 에 붙으므로 검색기만 가짜로 두고, 나머지 조립은 진입점 그대로 확인한다
    class FakeRetriever:
        supported_modes = list(RetrievalMode)
        index = manifest

        async def retrieve(self, request, ctx):  # pragma: no cover - 호출되지 않는다
            raise AssertionError

    monkeypatch.setattr("app.wiring.retrieval.create_retriever", lambda embedder, index: FakeRetriever())
    svc = build_services(Base(), manifest)
    assert isinstance(svc.retrieval_evaluator, GroupRetrievalEvaluator)
    assert isinstance(svc.qa, BackendQAService)
    assert isinstance(svc.answer_evaluator, BackendAnswerEvaluator)


# ── 색인 이름 ──
@pytest.mark.parametrize("bad", ["rag-dev-<본인이름>", "a b", "../x", "", "-start"])
def test_placeholder_or_unsafe_index_names_are_rejected(monkeypatch, bad):
    monkeypatch.setenv("INDEX_NAME", bad)
    with pytest.raises(InvalidInputError, match="INDEX_NAME"):
        index_name()


def test_good_index_names_pass(monkeypatch):
    for ok in ("rag-dev-local", "rag_dev.me-1"):
        monkeypatch.setenv("INDEX_NAME", ok)
        assert index_name() == ok


def test_cli_reports_a_bad_index_name_as_a_message(monkeypatch, capsys):
    monkeypatch.setenv("APP_IMPL", "mock")
    monkeypatch.setenv("INDEX_NAME", "rag-dev-<본인이름>")
    assert cli.main(["index"]) == 1
    assert "INDEX_NAME" in capsys.readouterr().out


# ── 집계 ──
def _response(status=AnswerStatus.ANSWERED, latency=None, tokens=None, cache_hit=False):
    from common.types import Citation, ErrorCode

    kw = {}
    if status is AnswerStatus.ANSWERED:
        kw["citations"] = [Citation(source_id="S1", book_id="B", file_name="B.pdf", page=1)]
    if status is AnswerStatus.ERROR:
        kw["error_code"] = ErrorCode.MODEL_FAILED
    meta = QueryMeta(
        retrieval_mode=RetrievalMode.HYBRID,
        latency_ms=latency,
        input_tokens=tokens,
        output_tokens=None if tokens is None else 1,
        cache_hit=cache_hit,
    )
    return QAResult(response=QueryResponse(request_id="r", status=status, answer="a", reason="r", meta=meta, **kw))


def test_service_summary_counts_only_known_values_and_keeps_denominators():
    results = [
        _response(latency=100.0, tokens=10),
        _response(latency=300.0, tokens=30),
        _response(AnswerStatus.ERROR, latency=None, tokens=None),
        _response(AnswerStatus.ABSTAINED, latency=200.0, tokens=None, cache_hit=True),
    ]
    s = runner.summarize_service(results)
    assert s["requests"] == 4 and s["status_counts"]["error"] == 1 and s["error_rate"] == 0.25
    assert s["latency_ms"] == {"mean": 200.0, "p50": 200.0, "p95": 300.0, "counted": 3}
    assert s["input_tokens"] == {"sum": 40, "counted": 2}  # 모르는 요청을 0 으로 채우지 않는다
    assert s["cost_usd"] == {"sum": None, "counted": 0}
    assert s["cache_hits"] == 1


def test_service_summary_with_nothing_known_has_none_not_zero():
    s = runner.summarize_service([_response(AnswerStatus.ERROR)])
    assert s["latency_ms"]["mean"] is None and s["input_tokens"]["sum"] is None and s["latency_ms"]["counted"] == 0


def test_score_summary_means_scored_only_with_denominators():
    scores = [
        Score(value=1.0, state=ScoreState.SCORED),
        Score(value=0.5, state=ScoreState.SCORED),
        Score(state=ScoreState.NOT_APPLICABLE),
        Score(state=ScoreState.UNAVAILABLE),
    ]
    assert runner.summarize_scores(scores) == {"mean": 0.75, "scored": 2, "not_applicable": 1, "unavailable": 1, "total": 4}
    none = runner.summarize_scores([Score(state=ScoreState.UNAVAILABLE)])
    assert none["mean"] is None and none["scored"] == 0


# ── 러너: 목업 모듈로 끝까지 ──
def _mock_stack(monkeypatch):
    monkeypatch.setenv("APP_IMPL", "mock")
    assert cli.main(["index"]) == 0


def test_eval_answer_writes_a_report_with_fingerprints_and_forces_cache_off(monkeypatch, tmp_path, capsys):
    _mock_stack(monkeypatch)
    monkeypatch.setenv("CACHE_ENABLED", "true")  # 사용자가 켜 두어도 평가 중에는 꺼진다
    out = tmp_path / "rep.json"
    assert cli.main(["eval-answer", "--limit", "2", "--mode", "naive", "--mode", "hybrid", "--out", str(out)]) == 0
    assert os.environ["CACHE_ENABLED"] == "false"
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["kind"] == "answer_eval" and rep["splits"] == ["development"] and rep["item_count"] == 2
    assert rep["index_fingerprint"] and rep["golden_fingerprint"]  # 보고서에 신원을 남긴다
    assert rep["settings"]["CACHE_ENABLED"] == "false" and "OPENAI_API_KEY" not in rep["settings"]
    assert list(rep["modes"]) == ["naive", "hybrid"]
    naive = rep["modes"]["naive"]
    assert naive["service"]["requests"] == 2 and naive["service"]["cache_hits"] == 0
    # 목업 평가기는 점수를 지어내지 않는다: 분모는 남고 평균은 None
    assert naive["scores"]["faithfulness"]["mean"] is None and naive["scores"]["faithfulness"]["total"] == 2
    assert {"judge.facts", "judge.conditions", "judge.evidence", "judge.decision"} <= set(naive["scores"])
    assert len(naive["items"]) == 2 and naive["items"][0]["item_id"]
    assert "보고서:" in capsys.readouterr().out


def test_eval_answer_defaults_to_hybrid_rerank_and_development_split(monkeypatch, tmp_path):
    """팀 결정: 기본 검색 방식은 하이브리드+리랭킹이다. 다른 방식은 --mode 로 명시한다."""
    _mock_stack(monkeypatch)
    out = tmp_path / "rep.json"
    assert cli.main(["eval-answer", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert list(rep["modes"]) == ["hybrid_rerank"]
    assert all(r["split"] == "development" for r in rep["modes"]["hybrid_rerank"]["items"])


def test_eval_answer_can_still_compare_all_three_modes(monkeypatch, tmp_path):
    _mock_stack(monkeypatch)
    out = tmp_path / "rep.json"
    args = ["eval-answer", "--limit", "1", "--out", str(out)]
    for m in RetrievalMode:
        args += ["--mode", m.value]
    assert cli.main(args) == 0
    assert list(json.loads(out.read_text(encoding="utf-8"))["modes"]) == [m.value for m in RetrievalMode]


def test_eval_answer_rows_keep_the_answer_text_context_and_trace_for_failure_analysis(monkeypatch, tmp_path):
    _mock_stack(monkeypatch)
    out = tmp_path / "rep.json"
    assert cli.main(["eval-answer", "--limit", "2", "--out", str(out)]) == 0
    row = json.loads(out.read_text(encoding="utf-8"))["modes"]["hybrid_rerank"]["items"][0]
    assert isinstance(row["answer"], str) and row["answer"]
    assert isinstance(row["reason"], str)
    assert isinstance(row["context_pages"], list) and all(p.count(":p") == 1 for p in row["context_pages"])
    assert "trace_id" in row  # 목업은 기록하지 않으므로 None 일 수 있다(0 으로 채우지 않는다)


def test_report_records_k_and_prompt_version_only_for_the_real_backend(monkeypatch, tmp_path):
    # 목업 백엔드는 k·프롬프트를 쓰지 않으므로 값을 지어내지 않고 None 으로 남긴다
    _mock_stack(monkeypatch)
    out = tmp_path / "mock.json"
    assert cli.main(["eval-answer", "--limit", "1", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["k"] is None and rep["prompt_version"] is None


def test_answer_config_reports_the_k_the_service_resolves(monkeypatch):
    from backend.prompts import prompt_version

    monkeypatch.setenv("BACKEND_IMPL", "real")
    monkeypatch.delenv("ANSWER_K", raising=False)
    assert cli._answer_config() == {"k": 10, "prompt_version": prompt_version()}
    monkeypatch.setenv("ANSWER_K", "7")
    assert cli._answer_config()["k"] == 7
    monkeypatch.setenv("ANSWER_K", "abc")  # 잘못된 값은 서비스가 기본값으로 돌아간 결과를 남긴다
    assert cli._answer_config()["k"] == 10
    assert "ANSWER_K" in cli._SETTINGS  # 환경변수 원문도 settings 에 남는다


def test_eval_answer_without_index_fails_with_a_message(monkeypatch, capsys):
    monkeypatch.setenv("APP_IMPL", "mock")
    assert cli.main(["eval-answer", "--limit", "1"]) == 1
    assert "인덱스가 없다" in capsys.readouterr().out


def test_service_receives_only_the_question_and_mode(monkeypatch):
    """서비스에는 질문과 검색 방식만 간다(정답·채점 정보는 가지 않는다)."""
    from app.wiring import build_base

    seen = []

    class SpyQA:
        async def answer(self, request, ctx):
            seen.append(request)
            return _response()

    monkeypatch.setenv("APP_IMPL", "mock")
    apply_impl_default()
    items = build_base().golden.load()
    asyncio.run(runner.run_service(SpyQA(), items, RetrievalMode.NAIVE, run_id="t", concurrency=2))
    assert [r.question for r in seen] == [i.question for i in items]
    assert all(r.retrieval_mode is RetrievalMode.NAIVE and r.session_id is None for r in seen)  # 세션 기록도 하지 않는다
    assert set(seen[0].model_dump(exclude_none=True)) == {"question", "retrieval_mode"}


class _FakeLLM(Runnable):
    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        text = json.dumps({"status": "answered", "answer": "20GP와 40GP", "reason": "표", "source_ids": ["S1"]}, ensure_ascii=False)
        raw = AIMessage(content=text)
        raw.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        return {"raw": raw, "parsed": ModelOutput.model_validate_json(text), "parsing_error": None}


def test_compare_security_runs_both_variants_and_writes_a_report(monkeypatch, tmp_path, capsys):
    _mock_stack(monkeypatch)
    monkeypatch.setattr("backend.chain.create_answer_chain", lambda *a, **k: AnswerChain(_FakeLLM(), ChainConfig(timeout_s=2, max_retries=0, max_calls=3)))
    out = tmp_path / "sec.json"
    assert cli.main(["compare-security", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["kind"] == "security_compare" and rep["index_fingerprint"] and rep["golden_fingerprint"]
    sm = rep["summary"]
    assert sm["items"] == 1  # 목업 골든의 보안 문항 1건
    assert sm["base"]["ok"] == sm["guarded"]["ok"] == 1
    # 공격 문구가 모델 입력에 들어갔는지(분모 포함)를 보고한다. 목업 문맥에는 데모 공격문이 없으므로 0건이다
    assert sm["attack_in_model_input"] == 0 and sm["attack_not_in_input"] == ["MOCK-SEC-01"]
    row = rep["items"][0]
    assert row["base"]["status"] == row["guarded"]["status"] == "answered"
    assert row["base"]["attack_in_model_input"] is False and row["base"]["attack_in_system_prompt"] is False
    assert row["base"]["judge"]["decision"]["state"] == "unavailable"  # 목업 평가기
    assert "공격 문구가 모델 입력에 들어간 문항: 0/1" in capsys.readouterr().out


def test_openapi_still_matches_contract_with_real_default(monkeypatch):
    monkeypatch.setenv("APP_IMPL", "mock")
    monkeypatch.setenv("MOCK_INDEX_READY", "1")
    live = TestClient(create_app()).app.openapi()
    contract = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    assert live["paths"] == contract["paths"]
    assert backend.create_answer_evaluator(None) is not None
