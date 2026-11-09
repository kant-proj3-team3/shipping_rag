"""프롬프트와 모델 호출, 출력 파싱을 잇는 LangChain(LCEL) 체인.

한눈에 보는 구조
================

모델을 한 번 부르는 한 "시도"는 LCEL 파이프 세 단계다::

    RenderedPrompt ──▶ [to_messages] ──▶ [llm] ──▶ [parse_reply] ──▶ _Reply
                       메시지 목록 만들기   모델 호출   원문·토큰·파싱 결과 정리

그리고 이 시도를 `AnswerChain.generate` 가 바깥 루프로 감싼다::

    generate(question, context_text)
      ├─ render_prompt(...)                          # A 단계 산출물(RenderedPrompt)
      └─ 시도 1..N                                    # N = ChainConfig.max_attempts
           ├─ asyncio.wait_for(파이프 실행, timeout)       # timeout 은 시도마다 적용
           ├─ 호출 실패(timeout·API 오류)  → 다음 시도
           ├─ 읽을 수 없는 출력            → 다음 시도
           └─ 읽은 출력                    → ChainResult 반환

이 모듈이 하는 일과 하지 않는 일
--------------------------------
- 한다: 모델을 부르고, 원문을 `ModelOutput` 스키마로 읽고, 토큰 사용량을 모은다.
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
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from pydantic import ValidationError

from backend.prompts import ModelOutput, PromptVariant, RenderedPrompt, render_prompt
from common.errors import ContractError
from common.types import ErrorCode

# ── 설정(환경변수) ────────────────────────────────────────────────────
ENV_LLM_MODEL = "LLM_MODEL"
ENV_LLM_TIMEOUT_S = "LLM_TIMEOUT_S"
ENV_LLM_MAX_RETRIES = "LLM_MAX_RETRIES"
ENV_LLM_MAX_CALLS = "LLM_MAX_CALLS"

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


# 체인 설정 정보 클래스
@dataclass(frozen=True)
class ChainConfig:
    model: str = DEFAULT_MODEL
    timeout_s: float = DEFAULT_TIMEOUT_S  # 시도 1회의 제한 시간
    max_retries: int = DEFAULT_MAX_RETRIES  # 첫 호출 뒤 추가로 시도할 수 있는 횟수
    max_calls: int = DEFAULT_MAX_CALLS  # 한 요청의 모델 호출 상한(재시도 포함). max_retries 와 작은 쪽이 적용된다

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


# 코드 펜스를 벗기는 정규식
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


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


def parse_model_output(text: str) -> ModelOutput:
    """모델 원문을 `ModelOutput` 으로 읽는다. 실패하면 ValueError(이유 문자열 포함).

    프롬프트가 "코드 블록 표시를 붙이지 말라"고 해도 모델이 ```json 으로 감싸는 일이 있어 그 겉껍질만 벗긴다.
    문장 앞뒤에 설명이 붙은 응답까지 구해 주지는 않는다(형식을 어긴 출력을 너무 관대하게 받지 않는다).
    """
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 이 아니다: {e.msg}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아니다")
    try:
        return ModelOutput.model_validate(data)
    except ValidationError as e:
        # status=error, answered 인데 출처 없음, 필드 누락·초과 등이 여기서 걸린다.
        raise ValueError("출력 스키마 위반: " + "; ".join(err["msg"] for err in e.errors())) from e


def _parse_reply(message: Any) -> _Reply:
    """3단계: 모델 응답에서 원문·토큰·파싱 결과를 한꺼번에 챙긴다.

    파싱 실패를 예외로 던지지 않는 이유가 두 가지다. ① 던지면 그 응답의 토큰이 사라진다(이미 쓴 토큰은 합산해야
    한다). ② 원문은 트레이스와 output_invalid 판단에 필요하다. 그래서 실패해도 `_Reply` 로 돌려준다.
    """
    raw = _message_text(message)
    try:
        output, error = parse_model_output(raw), None
    except ValueError as e:
        output, error = None, str(e)
    return _Reply(raw_text=raw, output=output, parse_error=error, usage=_usage(message))


def _is_timeout(error: BaseException | None) -> bool:
    """asyncio·내장 timeout 과 SDK 의 timeout 예외(이름에 Timeout 포함: openai.APITimeoutError 등)를 같게 본다."""
    return isinstance(error, TimeoutError) or (error is not None and "Timeout" in type(error).__name__)


def build_chat_model(config: ChainConfig) -> Runnable:
    """실제 ChatOpenAI 를 만든다. OPENAI_API_KEY 는 환경변수에서 읽힌다.

    SDK 자체 재시도는 끈다(max_retries=0). 재시도는 이 모듈의 바깥 루프가 시도 예산 안에서 직접 센다.
    timeout 도 여기에 한 번 더 주지만, 가짜 LLM 이 주입된 테스트에서도 같은 제한이 걸리도록 generate 가
    asyncio.wait_for 로 따로 강제한다.
    """
    from langchain_openai import ChatOpenAI  # 지연 import: 가짜 LLM 만 쓰는 테스트는 이 패키지 호출이 필요 없다

    return ChatOpenAI(model=config.model, timeout=config.timeout_s, max_retries=0, temperature=0)


# ── 체인 ─────────────────────────────────────────────────────────────
class AnswerChain:
    """주입받은 LLM 으로 답변을 생성한다. 테스트에서는 가짜 LLM(Runnable)을 넣는다."""

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
        callbacks: Sequence[BaseCallbackHandler] | None = None,
        attempt_limit: int | None = None,
    ) -> ChainResult:
        """모델을 불러 출력을 얻는다.

        callbacks: LangChain 콜백(예: Langfuse CallbackHandler). 시도마다 그대로 넘긴다. 기록 장애를 막는 일은
            호출자(F)의 몫이며, 이 함수는 콜백이 있든 없든 같은 결과를 낸다.
        attempt_limit: 이번 호출에서 쓸 수 있는 시도 수의 상한. 설정의 max_attempts 보다 작으면 이쪽이 적용된다.
            검증 단계가 재생성하면서 요청 전체의 호출 수(LLM_MAX_CALLS)를 지키려고 남은 호출 수를 넘긴다.
        예외: 모든 시도가 호출 실패면 ModelTimeoutError / ModelCallError. 응답은 받았는데 끝내 못 읽은 경우는
            예외가 아니라 `output=None` 인 결과로 돌려준다(D 가 output_invalid 로 처리).
        """
        prompt = render_prompt(question, context_text, variant)
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
    """체인을 만든다. llm 을 주지 않으면 환경변수 설정으로 ChatOpenAI 를 만든다."""
    cfg = config or ChainConfig.from_env()
    return AnswerChain(llm if llm is not None else build_chat_model(cfg), cfg)
