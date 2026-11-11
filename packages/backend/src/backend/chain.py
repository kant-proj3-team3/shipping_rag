"""프롬프트와 모델 호출, 출력 파싱을 잇는 LangChain(LCEL) 체인.

한눈에 보는 구조
================

모델을 한 번 부르는 한 "시도"는 LCEL 파이프 세 단계다::

    RenderedPrompt ──▶ [to_messages] ──▶ [structured llm] ──▶ [parse_reply] ──▶ _Reply
                       메시지 목록 만들기   모델 호출(구조화 출력)   원문·토큰·파싱 결과 정리

그리고 이 시도를 `AnswerChain.generate` 가 바깥 루프로 감싼다::

    generate(question, context_text)
      ├─ render_prompt(...)                          # A 단계 산출물(RenderedPrompt)
      └─ 시도 1..N                                    # N = ChainConfig.max_attempts
           ├─ asyncio.wait_for(파이프 실행, timeout)       # timeout 은 시도마다 적용
           ├─ 호출 실패(timeout·API 오류)  → 다음 시도
           ├─ 읽을 수 없는 출력            → 다음 시도
           └─ 읽은 출력                    → ChainResult 반환

구조화 출력
-----------
모델은 OpenAI Chat Completions 의 `json_schema`(strict) 로 `ModelOutput` 스키마를 강제받는다
(`ChatOpenAI.with_structured_output(ModelOutput, method="json_schema", strict=True, include_raw=True)`).
`include_raw=True` 라서 파이프 출력은 `{"raw": AIMessage, "parsed": ModelOutput | None, "parsing_error": ...}` 이고,
raw 에서 원문과 토큰 사용량을 읽는다. Responses API 는 쓰지 않는다(strict 구조화 출력에서 응답 항목이 하나 더 붙는다는
보고가 있어 Chat Completions 로 고정했다).
스키마가 형식을 강제해도 다음은 막지 못해서 코드가 계속 확인한다: `status=error`(스키마의 enum 에는 있지만 모델이
고를 수 없다), answered 인데 출처 없음(`ModelOutput` 검증기), 출처가 이번 문맥에 있는지(validate, D 단계). 그래서
`parsed` 가 None 일 수 있고, 그때는 재시도한다. 거부(refusal)도 같은 경로다.

이 모듈이 하는 일과 하지 않는 일
--------------------------------
- 한다: 모델을 부르고, 구조화된 결과를 `ModelOutput` 으로 받고, 토큰 사용량을 모은다.
- 하지 않는다: 출력의 source_id 가 이번 문맥에 있는지 확인하거나 출처(Citation)를 채우는 일(validate, D 단계),
  `status=error` 응답을 만드는 일(qa, E 단계), Langfuse 로 기록을 보내는 일(tracing, F 단계).
  다만 F 단계가 chain 을 다시 고치지 않도록, 콜백(`callbacks`)을 받아 LangChain 에 그대로 넘기는 자리는 열어 두었다.

왜 재시도를 `.with_retry()` 가 아니라 직접 짰나
---------------------------------------------
재시도는 "별도 요청이 아니라 같은 요청의 일부"여야 하고, 시도마다 토큰을 합산하며, 호출 실패와
읽을 수 없는 출력을 같은 예산으로 세야 한다. `.with_retry()` 는 예외만 다시 시도하므로 이 요구를 채우지 못한다.
그래서 파이프는 '한 번의 시도'만 맡고, 재시도는 바깥 루프가 맡는다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from pydantic import ValidationError

from backend.prompts import HistoryTurn, ModelOutput, PromptVariant, RenderedPrompt, render_prompt
from common.errors import ContractError
from common.types import ErrorCode

# ── 설정(환경변수) ────────────────────────────────────────────────────
ENV_LLM_MODEL = "LLM_MODEL"
ENV_LLM_TIMEOUT_S = "LLM_TIMEOUT_S"
ENV_LLM_MAX_RETRIES = "LLM_MAX_RETRIES"
ENV_LLM_MAX_CALLS = "LLM_MAX_CALLS"
ENV_LLM_REASONING_EFFORT = "LLM_REASONING_EFFORT"
ENV_LLM_TEMPERATURE = "LLM_TEMPERATURE"

# gpt-6-luna 가 받는 추론 강도(OpenAI 모델 문서 기준). 이 밖의 값은 무시하고 기본값을 쓴다.
REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
DEFAULT_REASONING_EFFORT = "medium"
# temperature 는 추론을 끈 때(none)만 바꿀 수 있다. 실제 호출로 확인: none 은 0·0.2·1 모두 정상,
# low·medium·미설정은 1 이 아닌 값을 400 으로 거부한다.
TEMPERATURE_REASONING_EFFORT = "none"

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-6-luna"
# 아래 기본값은 임시다. 팀이 정하면 환경변수로 바꾼다(코드 수정 없음).
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_CALLS = 3

# LangChain 이 trace 트리에 표시할 이름. Langfuse 에서 이 이름으로 단계를 찾는다.
RUN_NAME = "generate-answer"
STEP_TO_MESSAGES = "render-prompt"
STEP_PARSE = "parse-output"


# ── 오류 ─────────────────────────────────────────────────────────────
# common.errors 에는 모델 오류가 없고 common 은 수정할 수 없으므로, ContractError 를 상속해 이 모듈에 둔다.
# 메시지에는 원본 예외 문구를 넣지 않는다(키·내부 주소가 섞일 수 있다). 원본은 `__cause__` 로만 남는다.
class ModelTimeoutError(ContractError):
    """모든 시도가 timeout 으로 끝났다."""

    code = ErrorCode.MODEL_TIMEOUT


class ModelCallError(ContractError):
    """모델 호출이 timeout 이 아닌 이유로 끝내 실패했다."""

    code = ErrorCode.MODEL_FAILED


# 환경 변수 호출 함수(없으면 기본 값 사용)
def _env_number(name: str, default: float, *, minimum: float, cast: type = float) -> float:
    """환경변수를 숫자로 읽는다. 비었거나 숫자가 아니거나 최솟값 미만이면 기본값."""
    raw = os.environ.get(name, "").strip()
    try:
        value = cast(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_reasoning_effort() -> str:
    """LLM_REASONING_EFFORT 를 읽는다. 비었거나 허용 값이 아니면 기본값(medium)."""
    raw = os.environ.get(ENV_LLM_REASONING_EFFORT, "").strip().lower()
    return raw if raw in REASONING_EFFORTS else DEFAULT_REASONING_EFFORT


def _env_temperature() -> float | None:
    """LLM_TEMPERATURE 를 읽는다. 비었거나 숫자가 아니거나 0~2 밖이면 None(보내지 않는다)."""
    raw = os.environ.get(ENV_LLM_TEMPERATURE, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0.0 <= value <= 2.0 else None


# 체인 설정 정보 클래스
@dataclass(frozen=True)
class ChainConfig:
    model: str = DEFAULT_MODEL
    timeout_s: float = DEFAULT_TIMEOUT_S  # 시도 1회의 제한 시간
    max_retries: int = DEFAULT_MAX_RETRIES  # 첫 호출 뒤 추가로 시도할 수 있는 횟수
    max_calls: int = DEFAULT_MAX_CALLS  # 한 요청의 모델 호출 상한(재시도 포함). max_retries 와 작은 쪽이 적용된다
    # 추론 강도. 항상 모델에 보낸다(기본 medium). 추론이 켜져 있으면 temperature 를 바꿀 수 없다(build_chat_model 참고).
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    # None 이면 보내지 않는다. reasoning_effort 가 none 일 때만 보낸다(그 외에는 무시하고 경고만 남긴다).
    temperature: float | None = None

    @property
    def max_attempts(self) -> int:
        """실제 시도 횟수 = min(1 + max_retries, max_calls). 최소 1회."""
        return max(1, min(1 + self.max_retries, self.max_calls))

    # 환경 변수를 통해서 호출하는 팩토리 클래스 메소드
    @classmethod
    def from_env(cls) -> ChainConfig:
        return cls(
            model=os.environ.get(ENV_LLM_MODEL, "").strip() or DEFAULT_MODEL,
            timeout_s=_env_number(ENV_LLM_TIMEOUT_S, DEFAULT_TIMEOUT_S, minimum=0.001),
            max_retries=int(_env_number(ENV_LLM_MAX_RETRIES, DEFAULT_MAX_RETRIES, minimum=0, cast=int)),
            max_calls=int(_env_number(ENV_LLM_MAX_CALLS, DEFAULT_MAX_CALLS, minimum=1, cast=int)),
            reasoning_effort=_env_reasoning_effort(),
            temperature=_env_temperature(),
        )


# ── 결과 타입 ─────────────────────────────────────────────────────────
# 체인 결과 정보 클래스
@dataclass(frozen=True)
class ChainResult:
    """`generate` 의 결과. 출력이 끝내 읽히지 않으면 output 은 None 이고 parse_error 에 이유가 있다."""

    output: ModelOutput | None
    raw_text: str  # 마지막으로 받은 모델 원문(트레이스용). 응답을 한 번도 못 받았으면 빈 문자열이 아니라 예외가 난다
    parse_error: str | None
    prompt: RenderedPrompt  # 모델에 실제 전달한 입력
    attempts: int  # 모델을 부른 횟수(재시도 포함)
    input_tokens: int | None  # 확인 못 하면 None(0 아님)
    output_tokens: int | None


@dataclass(frozen=True)
class _Reply:
    """파이프 한 번(시도 1회)의 결과. 바깥 재시도 루프가 이것들을 모아 ChainResult 를 만든다."""

    raw_text: str
    output: ModelOutput | None  # 읽었으면 값, 못 읽었으면 None
    parse_error: str | None
    usage: tuple[int, int] | None  # (입력, 출력) 토큰. 확인 못 하면 None


# ── 파이프의 부품들 ───────────────────────────────────────────────────
def _to_messages(prompt: RenderedPrompt) -> list[BaseMessage]:
    """1단계: 렌더링된 프롬프트를 채팅 메시지로 바꾼다.

    ChatPromptTemplate 을 쓰지 않는 이유: 시스템 프롬프트의 JSON 예시에 중괄호가 있어서 템플릿이
    `{status}` 같은 변수로 읽으려 한다. 문구는 이미 render_prompt 가 완성했으므로 치환 없이 그대로 담는다.
    """
    return [SystemMessage(content=prompt.system), HumanMessage(content=prompt.user)]


# 메시지에서 내용을 추출해내는 함수
def _message_text(message: Any) -> str:
    """AIMessage 의 본문을 문자열로 꺼낸다. content 가 블록 목록(list)일 수도 있다."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # 콘텐츠 블록 목록
        return "".join(
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in content
            if isinstance(part, (str, dict))
        )
    return str(content)


def _usage(message: Any) -> tuple[int, int] | None:
    """(입력, 출력) 토큰. 둘 다 확인되는 정수일 때만 값을 돌려주고, 아니면 None(0으로 채우지 않는다)."""
    meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    i, o = meta.get("input_tokens"), meta.get("output_tokens")
    if isinstance(i, int) and isinstance(o, int) and not isinstance(i, bool) and not isinstance(o, bool):
        return i, o
    return None


def _summarize_error(error: BaseException | None, raw_message: Any) -> str:
    """파싱 실패 이유를 안전한 한 줄로 요약한다. 모델이 쓴 내용(입력값)은 넣지 않는다.

    pydantic 오류의 `str()` 에는 입력 값이 들어갈 수 있어서, 스키마 위반이면 규칙 메시지(`msg`)만 모은다.
    """
    refusal = getattr(raw_message, "additional_kwargs", {}).get("refusal") if raw_message is not None else None
    if refusal:
        return "모델이 응답을 거부했다"
    seen: BaseException | None = error
    while seen is not None:  # 원인 사슬에서 pydantic 검증 오류를 찾는다
        if isinstance(seen, ValidationError):
            return "출력 스키마 위반: " + "; ".join(err["msg"] for err in seen.errors())
        seen = seen.__cause__ or seen.__context__
    return f"구조화 출력을 읽을 수 없다({type(error).__name__ if error is not None else 'parsed 없음'})"


def _parse_reply(result: Mapping[str, Any]) -> _Reply:
    """3단계: 구조화 출력 결과(`raw`/`parsed`/`parsing_error`)에서 원문·토큰·파싱 결과를 챙긴다.

    읽지 못해도 예외를 던지지 않고 `_Reply` 로 돌려주는 이유가 두 가지다. ① 던지면 그 응답의 토큰이 사라진다(이미 쓴
    토큰은 합산해야 한다). ② 원문은 트레이스와 output_invalid 판단에 필요하다.
    """
    raw_message = result.get("raw")
    raw = _message_text(raw_message) if raw_message is not None else ""
    usage = _usage(raw_message)
    parsed = result.get("parsed")
    if isinstance(parsed, ModelOutput):
        return _Reply(raw_text=raw, output=parsed, parse_error=None, usage=usage)
    return _Reply(
        raw_text=raw,
        output=None,
        parse_error=_summarize_error(result.get("parsing_error"), raw_message),
        usage=usage,
    )


def _is_timeout(error: BaseException | None) -> bool:
    """asyncio·내장 timeout 과 SDK 의 timeout 예외(이름에 Timeout 포함: openai.APITimeoutError 등)를 같게 본다."""
    return isinstance(error, TimeoutError) or (error is not None and "Timeout" in type(error).__name__)


def build_chat_model(config: ChainConfig) -> Runnable:
    """실제 ChatOpenAI 를 만든다. OPENAI_API_KEY 는 환경변수에서 읽힌다.

    SDK 자체 재시도는 끈다(max_retries=0). 재시도는 이 모듈의 바깥 루프가 시도 예산 안에서 직접 센다.
    timeout 도 여기에 한 번 더 주지만, 가짜 LLM 이 주입된 테스트에서도 같은 제한이 걸리도록 generate 가
    asyncio.wait_for 로 따로 강제한다.

    추론 강도와 temperature:
    - reasoning_effort 는 항상 보낸다(기본 medium).
    - gpt-6-luna 는 추론이 켜져 있으면(none 이 아니면) 기본값(1) 외의 temperature 를 400 으로 거부한다. 그래서
      temperature 는 reasoning_effort 가 "none" 이고 값이 설정된 때만 보낸다. 그 외에 값이 설정돼 있으면 보내지
      않고 경고를 남긴다(무시되는 줄 모르고 재현성이 확보됐다고 믿지 않게).
    - 추론이 켜진 상태에서는 같은 질문의 답이 조금씩 다를 수 있다. 평가처럼 재현성이 필요하면
      LLM_REASONING_EFFORT=none, LLM_TEMPERATURE=0 으로 고정한다.
    """
    from langchain_openai import ChatOpenAI  # 지연 import: 가짜 LLM 만 쓰는 테스트는 이 패키지 호출이 필요 없다

    kwargs: dict[str, Any] = {"reasoning_effort": config.reasoning_effort}
    if config.temperature is not None:
        if config.reasoning_effort == TEMPERATURE_REASONING_EFFORT:
            kwargs["temperature"] = config.temperature
        else:
            logger.warning(
                "LLM_TEMPERATURE=%s 는 reasoning_effort=%s 에서 모델이 거부하므로 보내지 않는다 (none 일 때만 적용)",
                config.temperature,
                config.reasoning_effort,
            )
    # Responses API 로 자동 전환되지 않게 Chat Completions 로 고정한다(모듈 docstring 의 '구조화 출력' 참고).
    return ChatOpenAI(model=config.model, timeout=config.timeout_s, max_retries=0, use_responses_api=False, **kwargs)


def structured_model(chat_model: Runnable) -> Runnable:
    """채팅 모델에 `ModelOutput` 스키마를 강제하는 구조화 출력을 입힌다(json_schema, strict).

    결과는 `{"raw": AIMessage, "parsed": ModelOutput | None, "parsing_error": ...}` 를 돌려주는 Runnable 이다.
    `AnswerChain` 이 받는 llm 은 이 형태여야 한다(테스트에서는 같은 모양을 돌려주는 가짜를 넣는다).
    """
    return chat_model.with_structured_output(ModelOutput, method="json_schema", strict=True, include_raw=True)


# ── 체인 ─────────────────────────────────────────────────────────────
class AnswerGenerator(Protocol):
    """검증 단계(`generate_validated`)와 QAService 가 체인에 요구하는 것. `AnswerChain` 과 지연 생성 체인(`factory.py`)이 만족한다."""

    @property
    def config(self) -> ChainConfig: ...

    async def generate(
        self,
        question: str,
        context_text: str,
        variant: PromptVariant = ...,
        *,
        history: Sequence[HistoryTurn] = ...,
        callbacks: Sequence[BaseCallbackHandler] | None = ...,
        attempt_limit: int | None = ...,
    ) -> ChainResult: ...


class AnswerChain:
    """주입받은 LLM 으로 답변을 생성한다.

    llm 은 구조화 출력 결과(`{"raw", "parsed", "parsing_error"}`)를 돌려주는 Runnable 이다. 실제로는 `structured_model`
    로 만들고, 테스트에서는 같은 모양을 돌려주는 가짜를 넣는다.
    """

    def __init__(self, llm: Runnable, config: ChainConfig | None = None) -> None:
        self._config = config or ChainConfig.from_env()
        # 시도 1회분 LCEL 파이프. 한 번 만들어 두고 매 시도마다 재사용한다.
        # with_config(run_name=...) 는 trace 트리에서 각 단계가 읽기 쉬운 이름으로 보이게 한다.
        self._attempt: Runnable[RenderedPrompt, _Reply] = (
            RunnableLambda(_to_messages).with_config(run_name=STEP_TO_MESSAGES)
            | llm
            | RunnableLambda(_parse_reply).with_config(run_name=STEP_PARSE)
        )

    @property
    def config(self) -> ChainConfig:
        return self._config

    async def generate(
        self,
        question: str,
        context_text: str,
        variant: PromptVariant = PromptVariant.BASE,
        *,
        history: Sequence[HistoryTurn] = (),
        callbacks: Sequence[BaseCallbackHandler] | None = None,
        attempt_limit: int | None = None,
    ) -> ChainResult:
        """모델을 불러 출력을 얻는다.

        history: 같은 세션의 이전 대화(멀티턴, 오래된 것 → 최신 순). 비어 있으면 이전 대화 없는 프롬프트(단발)다.

        callbacks: LangChain 콜백(예: Langfuse CallbackHandler). 시도마다 그대로 넘긴다. 기록 장애를 막는 일은
            호출자(F)의 몫이며, 이 함수는 콜백이 있든 없든 같은 결과를 낸다.
        attempt_limit: 이번 호출에서 쓸 수 있는 시도 수의 상한. 설정의 max_attempts 보다 작으면 이쪽이 적용된다.
            검증 단계가 재생성하면서 요청 전체의 호출 수(LLM_MAX_CALLS)를 지키려고 남은 호출 수를 넘긴다.
        예외: 모든 시도가 호출 실패면 ModelTimeoutError / ModelCallError. 응답은 받았는데 끝내 못 읽은 경우는
            예외가 아니라 `output=None` 인 결과로 돌려준다(D 가 output_invalid 로 처리).
        """
        prompt = render_prompt(question, context_text, variant, history)
        max_attempts = self._config.max_attempts
        if attempt_limit is not None:
            max_attempts = max(1, min(max_attempts, attempt_limit))

        # 토큰 합산 상태. 응답을 받은 시도만 더하고, 하나라도 사용량이 없으면 합계는 믿을 수 없어 None 이 된다.
        # (예외로 끝난 시도는 응답이 없어 사용량을 알 수 없으므로 더하지 않는다.)
        in_total = out_total = 0
        usage_known = True
        last_failure: BaseException | None = None  # 마지막 호출 실패(응답을 못 받은 시도)
        last_reply: _Reply | None = None  # 마지막으로 받은 응답

        for attempt in range(1, max_attempts + 1):
            run_config: RunnableConfig = {
                "run_name": RUN_NAME,
                "metadata": {"attempt": attempt, "prompt_version": prompt.version},
            }
            if callbacks:
                run_config["callbacks"] = list(callbacks)

            # ── 1) 파이프 실행 (호출 실패는 여기서만 난다) ──
            try:
                reply: _Reply = await asyncio.wait_for(
                    self._attempt.ainvoke(prompt, config=run_config), timeout=self._config.timeout_s
                )
            except Exception as e:  # noqa: BLE001 - 어떤 호출 실패든 재시도 대상. 끝내 실패하면 아래서 분류한다
                last_failure = e
                continue

            # ── 2) 응답을 받았다: 토큰 합산 ──
            last_reply = reply
            if reply.usage is None:
                usage_known = False
            else:
                in_total += reply.usage[0]
                out_total += reply.usage[1]

            # ── 3) 읽었으면 끝, 못 읽었으면 다음 시도 ──
            if reply.output is not None:
                return ChainResult(
                    output=reply.output,
                    raw_text=reply.raw_text,
                    parse_error=None,
                    prompt=prompt,
                    attempts=attempt,
                    input_tokens=in_total if usage_known else None,
                    output_tokens=out_total if usage_known else None,
                )

        # ── 시도를 모두 썼는데 읽은 출력이 없다 ──
        if last_reply is None:
            # 응답을 한 번도 못 받았다 = 호출 실패. 호출자가 error_code 로 바꿀 수 있게 계약 예외로 던진다.
            if _is_timeout(last_failure):
                raise ModelTimeoutError("모델 응답 시간이 초과되었다") from last_failure
            raise ModelCallError(f"모델 호출 실패: {type(last_failure).__name__}") from last_failure

        # 응답은 받았지만 끝내 읽을 수 없었다. 호출 실패가 아니므로 결과로 돌려준다.
        return ChainResult(
            output=None,
            raw_text=last_reply.raw_text,
            parse_error=last_reply.parse_error,
            prompt=prompt,
            attempts=max_attempts,
            input_tokens=in_total if usage_known else None,
            output_tokens=out_total if usage_known else None,
        )


def create_answer_chain(llm: Runnable | None = None, config: ChainConfig | None = None) -> AnswerChain:
    """체인을 만든다. llm 을 주지 않으면 환경변수 설정으로 ChatOpenAI 를 만들어 구조화 출력을 입힌다."""
    cfg = config or ChainConfig.from_env()
    return AnswerChain(llm if llm is not None else structured_model(build_chat_model(cfg)), cfg)
