import asyncio
import json

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from backend.chain import (
    AnswerChain,
    ChainConfig,
    ModelCallError,
    ModelTimeoutError,
    create_answer_chain,
    parse_model_output,
)
from backend.prompts import PromptVariant
from common.types import AnswerStatus, ErrorCode

GOOD = json.dumps({"status": "answered", "answer": "3일", "reason": "표 2", "source_ids": ["S1"]}, ensure_ascii=False)


class FakeLLM(Runnable):
    """응답 목록을 차례로 돌려주는 가짜 LLM(LCEL 파이프에 끼울 수 있는 Runnable).

    항목이 예외면 던지고, (지연, 항목) 이면 기다린 뒤 처리한다. 받은 메시지와 config 를 기록한다.
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0
        self.last_messages = None
        self.last_config = None

    def invoke(self, input, config=None, **kwargs):  # 체인은 async 경로만 쓴다
        raise NotImplementedError

    async def ainvoke(self, messages, config=None, **kwargs):
        self.calls += 1
        self.last_messages = messages
        self.last_config = config
        step = self.steps.pop(0)
        if isinstance(step, tuple):
            await asyncio.sleep(step[0])
            step = step[1]
        if isinstance(step, Exception):
            raise step
        return step


def _msg(text: str, usage: tuple[int, int] | None = (10, 5)) -> AIMessage:
    m = AIMessage(content=text)
    if usage is not None:
        m.usage_metadata = {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)}
    return m


def _chain(llm, **kw) -> AnswerChain:
    cfg = ChainConfig(**{"timeout_s": 1.0, "max_retries": 2, "max_calls": 3, **kw})
    return AnswerChain(llm, cfg)


def run(coro):
    return asyncio.run(coro)


# ── 정상 ──
def test_success_parses_output_and_reports_tokens():
    llm = FakeLLM(_msg(GOOD, (100, 20)))
    r = run(_chain(llm).generate("질문", "[S1] 자료"))
    assert r.output is not None and r.output.status is AnswerStatus.ANSWERED
    assert r.output.source_ids == ["S1"]
    assert (r.input_tokens, r.output_tokens, r.attempts) == (100, 20, 1)
    assert r.parse_error is None and r.raw_text == GOOD


def test_model_receives_rendered_prompt_as_system_and_user():
    llm = FakeLLM(_msg(GOOD))
    r = run(_chain(llm).generate("질문입니다", "[S1] 자료", PromptVariant.GUARDED))
    system, user = llm.last_messages
    assert system.content == r.prompt.system and user.content == r.prompt.user
    assert "질문입니다" in user.content and r.prompt.version.endswith("guarded")


def test_code_fence_is_stripped():
    r = run(_chain(FakeLLM(_msg(f"```json\n{GOOD}\n```"))).generate("q", "c"))
    assert r.output is not None


# ── 토큰 None ──
def test_missing_usage_is_none_not_zero():
    r = run(_chain(FakeLLM(_msg(GOOD, usage=None))).generate("q", "c"))
    assert r.output is not None
    assert r.input_tokens is None and r.output_tokens is None


def test_partial_usage_is_none():
    m = AIMessage(content=GOOD)
    m.usage_metadata = {"input_tokens": 5, "output_tokens": None}  # type: ignore[typeddict-item]
    r = run(_chain(FakeLLM(m)).generate("q", "c"))
    assert r.input_tokens is None and r.output_tokens is None


# ── 재시도·합산 ──
def test_retry_after_call_error_then_success():
    llm = FakeLLM(RuntimeError("boom"), _msg(GOOD, (7, 3)))
    r = run(_chain(llm).generate("q", "c"))
    assert r.output is not None and r.attempts == 2 and llm.calls == 2
    assert (r.input_tokens, r.output_tokens) == (7, 3)  # 예외로 끝난 시도는 사용량을 알 수 없어 더하지 않는다


def test_retry_tokens_are_summed_across_unreadable_then_good():
    llm = FakeLLM(_msg("JSON 아님", (10, 4)), _msg(GOOD, (12, 6)))
    r = run(_chain(llm).generate("q", "c"))
    assert r.output is not None and r.attempts == 2
    assert (r.input_tokens, r.output_tokens) == (22, 10)


def test_sum_is_none_if_any_response_lacks_usage():
    llm = FakeLLM(_msg("JSON 아님", usage=None), _msg(GOOD, (12, 6)))
    r = run(_chain(llm).generate("q", "c"))
    assert r.output is not None
    assert r.input_tokens is None and r.output_tokens is None


# ── 읽을 수 없는 출력 ──
@pytest.mark.parametrize(
    "bad",
    [
        "그냥 문장",
        "[1, 2]",
        json.dumps({"status": "error", "answer": "a", "reason": "r"}),  # 모델은 error 를 고를 수 없다
        json.dumps({"status": "answered", "answer": "a", "reason": "r", "source_ids": []}),
        json.dumps({"status": "abstained", "answer": "a"}),  # reason 누락
        json.dumps({"status": "abstained", "answer": "a", "reason": "r", "extra": 1}),
    ],
)
def test_unreadable_output_returns_result_with_parse_error(bad):
    llm = FakeLLM(*[_msg(bad)] * 3)
    r = run(_chain(llm).generate("q", "c"))
    assert r.output is None and r.parse_error and r.attempts == 3 and llm.calls == 3
    assert r.raw_text == bad
    assert (r.input_tokens, r.output_tokens) == (30, 15)


def test_parse_model_output_raises_value_error():
    with pytest.raises(ValueError):
        parse_model_output("{")


# ── 호출 실패 ──
def test_timeout_every_attempt_raises_model_timeout():
    llm = FakeLLM((0.5, _msg(GOOD)), (0.5, _msg(GOOD)))
    with pytest.raises(ModelTimeoutError) as ei:
        run(_chain(llm, timeout_s=0.05, max_retries=1).generate("q", "c"))
    assert ei.value.code is ErrorCode.MODEL_TIMEOUT and llm.calls == 2


def test_sdk_style_timeout_exception_is_timeout():
    class APITimeoutError(Exception):
        pass

    with pytest.raises(ModelTimeoutError):
        run(_chain(FakeLLM(*[APITimeoutError("t")] * 3)).generate("q", "c"))


def test_timeout_then_success():
    llm = FakeLLM((0.5, _msg(GOOD)), _msg(GOOD, (1, 1)))
    r = run(_chain(llm, timeout_s=0.05).generate("q", "c"))
    assert r.output is not None and r.attempts == 2


def test_exception_every_attempt_raises_model_failed():
    llm = FakeLLM(*[RuntimeError("secret-key-sk-123")] * 3)
    with pytest.raises(ModelCallError) as ei:
        run(_chain(llm).generate("q", "c"))
    assert ei.value.code is ErrorCode.MODEL_FAILED
    assert "sk-123" not in str(ei.value)  # 사용자에게 나갈 수 있는 문구에 내부 값을 넣지 않는다
    assert llm.calls == 3


# ── 호출 상한 ──
def test_max_calls_caps_attempts():
    llm = FakeLLM(*[RuntimeError("x")] * 5)
    with pytest.raises(ModelCallError):
        run(_chain(llm, max_retries=10, max_calls=2).generate("q", "c"))
    assert llm.calls == 2


def test_zero_retries_means_single_call():
    llm = FakeLLM(RuntimeError("x"), _msg(GOOD))
    with pytest.raises(ModelCallError):
        run(_chain(llm, max_retries=0).generate("q", "c"))
    assert llm.calls == 1


# ── 설정 ──
def test_config_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "m-x")
    monkeypatch.setenv("LLM_TIMEOUT_S", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")
    monkeypatch.setenv("LLM_MAX_CALLS", "2")
    cfg = ChainConfig.from_env()
    assert (cfg.model, cfg.timeout_s, cfg.max_retries, cfg.max_calls, cfg.max_attempts) == ("m-x", 12.5, 4, 2, 2)


def test_config_defaults_on_missing_or_bad_values(monkeypatch):
    for name, bad in [("LLM_MODEL", ""), ("LLM_TIMEOUT_S", "abc"), ("LLM_MAX_RETRIES", "-1"), ("LLM_MAX_CALLS", "0")]:
        monkeypatch.setenv(name, bad)
    cfg = ChainConfig.from_env()
    assert (cfg.model, cfg.timeout_s, cfg.max_retries, cfg.max_calls) == ("gpt-6-luna", 60.0, 2, 3)


def test_create_answer_chain_uses_injected_llm_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = FakeLLM(_msg(GOOD))
    chain = create_answer_chain(llm)
    assert run(chain.generate("q", "c")).output is not None


# ── LCEL 구조·콜백 ──
class RecordingHandler(BaseCallbackHandler):
    """LangChain 이 trace 로 보고하는 단계 이름을 모은다(Langfuse CallbackHandler 가 받는 것과 같은 정보)."""

    def __init__(self):
        self.chain_names: list[str] = []
        self.metadata: list[dict] = []

    def on_chain_start(self, serialized, inputs, *, run_id, name=None, metadata=None, **kwargs):
        self.chain_names.append(name or "")
        self.metadata.append(metadata or {})


def test_callbacks_see_named_steps_and_attempt_metadata():
    handler = RecordingHandler()
    llm = FakeLLM(_msg(GOOD))
    run(_chain(llm).generate("q", "c", callbacks=[handler]))
    # 시도 전체(generate-answer)와 앞뒤 단계(render-prompt, parse-output)가 이름으로 보인다.
    assert {"generate-answer", "render-prompt", "parse-output"} <= set(handler.chain_names)
    assert any(m.get("attempt") == 1 and m.get("prompt_version") for m in handler.metadata)


def test_callbacks_are_passed_on_every_attempt():
    handler = RecordingHandler()
    llm = FakeLLM(RuntimeError("x"), _msg(GOOD))
    run(_chain(llm).generate("q", "c", callbacks=[handler]))
    # 재시도(2번째 시도)에도 같은 콜백이 붙어 attempt 메타데이터가 1, 2로 찍힌다.
    assert {m.get("attempt") for m in handler.metadata} >= {1, 2}


def test_result_is_same_with_or_without_callbacks():
    a = run(_chain(FakeLLM(_msg(GOOD, (3, 2)))).generate("q", "c"))
    b = run(_chain(FakeLLM(_msg(GOOD, (3, 2)))).generate("q", "c", callbacks=[RecordingHandler()]))
    assert (a.output, a.input_tokens, a.output_tokens, a.attempts) == (b.output, b.input_tokens, b.output_tokens, b.attempts)


def test_prompt_with_braces_is_not_treated_as_template():
    # 시스템 프롬프트의 JSON 예시({"status": ...})가 템플릿 변수로 읽히지 않고 그대로 전달된다.
    llm = FakeLLM(_msg(GOOD))
    run(_chain(llm).generate("q", "c"))
    assert '{"status"' in llm.last_messages[0].content


# ── 호출 수 상한 인자(검증 단계가 요청 전체 호출 수를 지키려고 넘긴다) ──
def test_attempt_limit_lowers_attempts():
    llm = FakeLLM(*[RuntimeError("x")] * 5)
    with pytest.raises(ModelCallError):
        run(_chain(llm, max_retries=10, max_calls=10).generate("q", "c", attempt_limit=2))
    assert llm.calls == 2


def test_attempt_limit_cannot_exceed_config():
    llm = FakeLLM(*[RuntimeError("x")] * 5)
    with pytest.raises(ModelCallError):
        run(_chain(llm, max_retries=1).generate("q", "c", attempt_limit=9))
    assert llm.calls == 2


def test_attempt_limit_is_at_least_one():
    llm = FakeLLM(_msg(GOOD))
    assert run(_chain(llm).generate("q", "c", attempt_limit=0)).attempts == 1
