import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from backend.chain import AnswerChain, ChainConfig, ModelCallError
from backend.context import build_context
from backend.prompts import ModelOutput
from backend.validate import (
    DEFAULT_MAX_REGENERATIONS,
    ENV_MAX_REGENERATIONS,
    OutputValidationError,
    build_citations,
    find_unknown_source_ids,
    generate_validated,
    max_regenerations,
    validate_output,
)
from common.types import AnswerStatus, Chunk, RetrievedChunk


# ── 준비물 ──
def _chunk(n: int, *, ps: int = 1, pe: int | None = None, file: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        rank=n,
        score=1.0 / n,
        chunk=Chunk(
            chunk_id=f"c{n}",
            book_id=f"IS0{n}",
            file_name=file or f"IS0{n}.pdf",
            page_start=ps,
            page_end=pe if pe is not None else ps,
            text=f"본문 {n}",
        ),
    )


def _context(*retrieved: RetrievedChunk):
    return build_context(list(retrieved), max_tokens=10_000)


def _json(status="answered", source_ids=("S1",), answer="3일", reason="표 2") -> str:
    return json.dumps(
        {"status": status, "answer": answer, "reason": reason, "source_ids": list(source_ids)}, ensure_ascii=False
    )


def _msg(text: str, usage: tuple[int, int] | None = (10, 5)) -> AIMessage:
    m = AIMessage(content=text)
    if usage is not None:
        m.usage_metadata = {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)}
    return m


class FakeLLM(Runnable):
    """응답 목록을 차례로 돌려주는 가짜 LLM. 항목이 예외면 던진다."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _chain(llm, **kw) -> AnswerChain:
    cfg = ChainConfig(**{"timeout_s": 1.0, "max_retries": 0, "max_calls": 5, **kw})
    return AnswerChain(llm, cfg)


def run(coro):
    return asyncio.run(coro)


def _output(**kw) -> ModelOutput:
    return ModelOutput.model_validate(json.loads(_json(**kw)))


# ── 출처 범위 검증 ──
def test_unknown_source_id_is_rejected():
    ctx = _context(_chunk(1), _chunk(2))
    with pytest.raises(OutputValidationError, match="S99"):
        validate_output(_output(source_ids=("S1", "S99")), ctx.items)


def test_source_id_from_other_request_is_rejected():
    # 이번 문맥은 S1 하나뿐이다. 존재하는 번호(S2)여도 이번 요청에 없으면 거부한다.
    ctx = _context(_chunk(1))
    assert find_unknown_source_ids(["S1", "S2"], ctx.items) == ["S2"]
    with pytest.raises(OutputValidationError):
        validate_output(_output(source_ids=("S2",)), ctx.items)


def test_error_message_has_no_model_text():
    ctx = _context(_chunk(1))
    with pytest.raises(OutputValidationError) as ei:
        validate_output(_output(source_ids=("S9",), answer="비밀 답변 본문"), ctx.items)
    assert "비밀 답변 본문" not in str(ei.value)


@pytest.mark.parametrize("status", ["abstained", "needs_clarification"])
def test_non_answered_may_cite_in_range_sources(status):
    # 자료 충돌로 보류할 때 양쪽 자료를 근거로 드는 응답은 허용한다.
    ctx = _context(_chunk(1), _chunk(2))
    v = validate_output(_output(status=status, source_ids=("S1", "S2")), ctx.items)
    assert [c.source_id for c in v.citations] == ["S1", "S2"]


@pytest.mark.parametrize("status", ["abstained", "needs_clarification"])
def test_non_answered_may_have_no_sources(status):
    v = validate_output(_output(status=status, source_ids=()), _context(_chunk(1)).items)
    assert v.citations == [] and v.source_ids == []


@pytest.mark.parametrize("status", ["abstained", "needs_clarification"])
def test_non_answered_out_of_range_is_still_rejected(status):
    with pytest.raises(OutputValidationError):
        validate_output(_output(status=status, source_ids=("S5",)), _context(_chunk(1)).items)


def test_answered_without_sources_is_rejected_by_schema():
    with pytest.raises(ValueError):
        _output(status="answered", source_ids=())


# ── Citation 은 코드가 Chunk 값으로 채운다 ──
def test_citations_come_from_chunks_in_model_order():
    ctx = _context(_chunk(1, ps=3), _chunk(2, ps=7, file="다른문서.pdf"))
    v = validate_output(_output(source_ids=("S2", "S1")), ctx.items)
    assert [(c.source_id, c.book_id, c.file_name, c.page) for c in v.citations] == [
        ("S2", "IS02", "다른문서.pdf", 7),
        ("S1", "IS01", "IS01.pdf", 3),
    ]
    assert v.source_ids == ["S2", "S1"]


def test_multi_page_chunk_gets_one_citation_per_page():
    ctx = _context(_chunk(1, ps=3, pe=5))
    cs = build_citations(["S1"], ctx.items)
    assert [(c.source_id, c.page) for c in cs] == [("S1", 3), ("S1", 4), ("S1", 5)]


def test_validated_fields_are_copied_from_output():
    v = validate_output(_output(answer="답", reason="이유"), _context(_chunk(1)).items)
    assert (v.status, v.answer, v.reason) == (AnswerStatus.ANSWERED, "답", "이유")


# ── 재생성 ──
def test_first_try_success_needs_no_regeneration():
    llm = FakeLLM(_msg(_json(), (10, 5)))
    out = run(generate_validated(_chain(llm), "q", _context(_chunk(1))))
    assert out.ok and out.failure is None and out.calls == 1 and out.regenerations == 0
    assert (out.input_tokens, out.output_tokens) == (10, 5)
    assert out.answer.citations[0].file_name == "IS01.pdf"


def test_regenerates_after_out_of_range_source_then_succeeds():
    llm = FakeLLM(_msg(_json(source_ids=("S9",)), (10, 5)), _msg(_json(source_ids=("S1",)), (12, 6)))
    out = run(generate_validated(_chain(llm), "q", _context(_chunk(1)), max_regen=1))
    assert out.ok and out.regenerations == 1 and out.calls == 2 and llm.calls == 2
    assert (out.input_tokens, out.output_tokens) == (22, 11)  # 두 호출의 합


def test_regeneration_never_exceeds_limit():
    bad = _msg(_json(source_ids=("S9",)))
    llm = FakeLLM(*[bad] * 10)
    out = run(generate_validated(_chain(llm), "q", _context(_chunk(1)), max_regen=2))
    assert not out.ok and "S9" in out.failure
    assert out.regenerations == 2 and out.calls == 3 and llm.calls == 3


def test_zero_regenerations_means_single_generation():
    llm = FakeLLM(*[_msg(_json(source_ids=("S9",)))] * 3)
    out = run(generate_validated(_chain(llm), "q", _context(_chunk(1)), max_regen=0))
    assert not out.ok and out.calls == 1 and out.regenerations == 0


def test_total_calls_are_capped_by_max_calls():
    # 재생성 상한이 커도 요청 전체의 호출 수(LLM_MAX_CALLS)를 넘지 않는다.
    llm = FakeLLM(*[_msg(_json(source_ids=("S9",)))] * 10)
    out = run(generate_validated(_chain(llm, max_calls=2), "q", _context(_chunk(1)), max_regen=10))
    assert not out.ok and out.calls == 2 and llm.calls == 2


def test_chain_retries_count_toward_call_budget():
    # 읽을 수 없는 출력을 체인이 재시도(2회)한 뒤에는 남은 호출이 없다.
    llm = FakeLLM(*[_msg("JSON 아님")] * 10)
    out = run(generate_validated(_chain(llm, max_retries=1, max_calls=2), "q", _context(_chunk(1)), max_regen=5))
    assert not out.ok and out.calls == 2 and llm.calls == 2
    assert out.failure and "JSON" in out.failure and out.raw_text == "JSON 아님"


def test_unreadable_output_is_regenerated_when_budget_remains():
    llm = FakeLLM(_msg("JSON 아님"), _msg(_json()))
    out = run(generate_validated(_chain(llm, max_retries=0), "q", _context(_chunk(1)), max_regen=1))
    assert out.ok and out.regenerations == 1 and out.calls == 2


def test_tokens_are_none_if_any_call_lacks_usage():
    llm = FakeLLM(_msg(_json(source_ids=("S9",)), usage=None), _msg(_json(), (12, 6)))
    out = run(generate_validated(_chain(llm), "q", _context(_chunk(1)), max_regen=1))
    assert out.ok and out.input_tokens is None and out.output_tokens is None


def test_call_failure_propagates():
    llm = FakeLLM(RuntimeError("x"))
    with pytest.raises(ModelCallError):
        run(generate_validated(_chain(llm), "q", _context(_chunk(1))))


def test_empty_context_is_a_programming_error():
    empty = build_context([], max_tokens=100)
    with pytest.raises(ValueError):
        run(generate_validated(_chain(FakeLLM()), "q", empty))


# ── 설정 ──
def test_max_regenerations_env(monkeypatch):
    monkeypatch.setenv(ENV_MAX_REGENERATIONS, "3")
    assert max_regenerations() == 3
    monkeypatch.setenv(ENV_MAX_REGENERATIONS, "0")
    assert max_regenerations() == 0


@pytest.mark.parametrize("bad", ["", "abc", "-1"])
def test_max_regenerations_defaults_on_bad_values(monkeypatch, bad):
    monkeypatch.setenv(ENV_MAX_REGENERATIONS, bad)
    assert max_regenerations() == DEFAULT_MAX_REGENERATIONS
