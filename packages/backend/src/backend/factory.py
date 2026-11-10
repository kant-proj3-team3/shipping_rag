"""실제 구현 조립(I): `BACKEND_IMPL=real` 일 때 진입점(`create_*`)이 쓰는 서비스와 지연 생성 체인.

전환 방식
=========
`backend.create_qa_service` / `create_session_service` 는 환경변수 `BACKEND_IMPL` 로 구현을 고른다(retrieval·chunking 의
`RETRIEVAL_IMPL`·`CHUNKING_IMPL` 과 같은 방식).

- 없거나 `mock`(기본): 목업. 키·DB 없이 돌아서 CI 와 다른 모듈의 개발이 그대로 동작한다.
- `real`: 이 모듈의 실제 구현. `OPENAI_API_KEY`(모델), `DATABASE_URL`(PostgreSQL), `REDIS_URL` 을 쓰고,
  `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY` 가 있으면 Langfuse 에 기록한다.

세션 저장소는 하나를 공유한다
-----------------------------
`create_qa_service` 와 `create_session_service` 는 서로를 인자로 받지 않는다. 각자 저장소를 만들면 DB 풀과 Redis 연결이
두 벌이 되므로 프로세스 안에서 하나(`shared_session_store`)만 만들어 둘이 같이 쓴다. QA 서비스는 이 저장소에 턴을 기록하고
(`sessions`) 같은 객체에서 이전 대화를 읽는다(`history`, 멀티턴).

모델 클라이언트는 시작 때 만들어 보고, 못 만들면 첫 요청 때 다시 시도한다
----------------------------------------------------------------------
`ChatOpenAI` 는 `OPENAI_API_KEY` 가 없으면 만들 때 실패한다. 키 하나 때문에 api 전체(`/health` 포함)가 뜨지 않게 하려고,
시작 때 만들어 보되(`warm_up`) 실패해도 예외를 내지 않고 앱을 띄운다. 그러면 정상적으로는 첫 요청이 클라이언트 생성 시간(실측
약 0.75초)을 치르지 않는다. 못 만든 경우에는 요청 때 다시 시도하고, 또 못 만들면 `ModelCallError` 를 내서 QAService 가
`status=error`(`model_failed`, 502)로 돌려준다(계약: 예외를 던지지 않는다). 원인은 서버 로그에 남기고 사용자 응답에는 넣지
않는다. 실패는 기억하지 않고 요청마다 다시 시도한다(환경변수는 시작 때 읽히므로 고치려면 재시작이 필요하다).
"""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from backend.chain import AnswerChain, ChainConfig, ChainResult, ModelCallError, create_answer_chain
from backend.prompts import HistoryTurn, PromptVariant
from backend.qa import BackendQAService
from backend.session import PersistentSessionStore, SessionQueryService, create_session_store
from backend.tracing import Tracer, create_tracer
from common.interfaces import Retriever

logger = logging.getLogger(__name__)


class LazyAnswerChain:
    """첫 `generate` 때 실제 체인을 만든다. 만들 수 없으면 `ModelCallError`(model_failed)를 낸다."""

    def __init__(
        self, *, config: ChainConfig | None = None, build: Callable[[ChainConfig], AnswerChain] | None = None
    ) -> None:
        self._config = config or ChainConfig.from_env()
        self._build = build or (lambda cfg: create_answer_chain(config=cfg))
        self._chain: AnswerChain | None = None
        self._lock = threading.Lock()
        self._failure_logged = False

    @property
    def config(self) -> ChainConfig:
        return self._config

    def warm_up(self) -> bool:
        """모델 클라이언트를 미리 만들어 둔다(앱 시작 때). 첫 요청이 만드는 시간(실측 약 0.75초)을 치르지 않게 한다.

        못 만들어도(키 없음 등) 예외를 내지 않는다. 앱은 뜨고, 첫 요청 때 다시 시도해 `model_failed` 로 돌려준다.
        """
        try:
            self._get()
        except ModelCallError:
            logger.warning("모델 클라이언트를 미리 만들지 못했다. 첫 요청 때 다시 시도한다")
            return False
        return True

    def _get(self) -> AnswerChain:
        if self._chain is None:
            with self._lock:
                if self._chain is None:
                    try:
                        self._chain = self._build(self._config)
                    except Exception as exc:  # noqa: BLE001 - 설정 오류든 라이브러리 오류든 model_failed 로 바꾼다
                        if not self._failure_logged:  # 요청마다 스택을 쏟지 않는다
                            logger.error("모델 클라이언트를 만들지 못했다. OPENAI_API_KEY 등 설정을 확인한다", exc_info=True)
                            self._failure_logged = True
                        else:
                            logger.error("모델 클라이언트를 만들지 못했다(원인은 처음 로그와 같다)")
                        raise ModelCallError("모델 클라이언트를 만들지 못했다") from exc
        return self._chain

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
        return await self._get().generate(
            question, context_text, variant, history=history, callbacks=callbacks, attempt_limit=attempt_limit
        )


@functools.lru_cache(maxsize=1)
def shared_session_store() -> PersistentSessionStore:
    """프로세스 안에서 하나만 만든다(DB 풀·Redis 연결을 QA 서비스와 세션 서비스가 같이 쓴다). 연결은 첫 사용 때 만들어진다."""
    return create_session_store()


def create_real_qa_service(
    retriever: Retriever,
    *,
    chain: Any | None = None,
    store: PersistentSessionStore | None = None,
    tracer: Tracer | None = None,
) -> BackendQAService:
    """실제 QA 서비스. 인자는 테스트에서 가짜를 넣는 자리이고, 진입점은 `retriever` 만 준다."""
    sessions = store if store is not None else shared_session_store()
    if chain is None:
        lazy = LazyAnswerChain()
        lazy.warm_up()  # 앱 시작 때 만들어 본다. 실패해도 앱은 뜨고 첫 요청 때 다시 시도한다
        chain = lazy
    return BackendQAService(
        retriever,
        chain,
        sessions,
        history=sessions,  # 멀티턴: 기록하는 저장소에서 이전 대화를 읽는다
        tracer=tracer if tracer is not None else create_tracer(),
    )


def create_real_session_service(*, store: PersistentSessionStore | None = None) -> SessionQueryService:
    return SessionQueryService(store if store is not None else shared_session_store())


__all__ = [
    "LazyAnswerChain",
    "create_real_qa_service",
    "create_real_session_service",
    "shared_session_store",
]
