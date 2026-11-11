"""Redis 답변 캐시(H): 같은 조건의 질문에는 저장된 답변을 돌려준다.

무엇이 키가 되나
================
키는 **답을 바꿀 수 있는 모든 것**의 해시다. 하나라도 다르면 적중하지 않는다.

- 질문(앞뒤 공백을 지우고 유니코드 NFC 로 맞춘 값)
- `retrieval_mode`, `k`
- `index_name` + `embedder_id` + **`manifest.fingerprint`**: 같은 이름으로 재색인하면 `fingerprint` 가 바뀐다. Redis 는 api 를
  재시작해도 남으므로 이게 없으면 옛 인덱스 기준 답변이 적중한다. 모드가 다른데 적중하면 세 방식 비교도 무의미해진다
- 프롬프트 버전(`v2`, 변형이면 `v2+guarded`)
- 모델·추론 강도·temperature, 문맥 토큰 예산(바뀌면 같은 질문도 다른 답이 나온다)
- 저장 형식 버전(`ENTRY_VERSION`). 올리면 옛 항목은 모두 적중하지 않는다

이력이 프롬프트에 들어가는 요청은 **캐시를 우회한다**(읽지도 쓰지도 않는다): 같은 질문이라도 이력에 따라 답이 달라지는데
이력을 키에 넣으면 사실상 적중하지 않기 때문이다. 세션이 있어도 이력이 비어 있는 첫 질문은 단발과 프롬프트가 같으므로 쓴다.

무엇을 저장하나
---------------
`QAResult`(응답 + 평가 입력인 `final_context`) 전체를 JSON 으로 저장한다. **`status=error` 는 저장하지 않는다**(일시적 실패가
TTL 동안 고정되지 않게). 적중하면 서비스가 새 `request_id`·`meta`(시간, `cache_hit=True`, 이번 요청에서 모델을 부르지 않았으므로
**토큰은 None**, 새 `trace_id`)를 채우고, 질문·세션 기록은 그대로 한다.

운영
----
- 키는 `rag:answer:` 로 시작하고 모두 TTL(`CACHE_TTL_SECONDS`, 기본 1시간)이 있다. 세션 키(`rag:session:`)와 공간이 분리돼 있다.
  compose 의 Redis 는 `volatile-lru` 라서 TTL 없는 키는 지워지지 않는다.
- `CACHE_ENABLED=false` 면 끈다(기본은 켜짐). **평가를 돌릴 때는 꺼야 한다**: 적중한 응답은 모델을 부르지 않아 시간·토큰 지표를
  왜곡한다. 적중 여부는 `meta.cache_hit` 으로 알 수 있다.
- 읽기·쓰기가 실패하면 캐시 없이 처리한다(서비스가 경고만 남긴다). 읽기에 실패하면 쓰기는 시도하지 않는다(Redis 가 죽었을 때 timeout 을
  두 번 치르지 않게). 읽을 수 없는 항목(깨진 JSON, 옛 형식, 계약이 바뀐 뒤의 항목)은 없는 것으로 보고 다시 만든다.
- 알려진 한계: 모델이 매번 같은 답을 내지는 않는다. 캐시는 그중 하나를 TTL 동안 고정하므로, 잘못된 답이 한 번 저장되면 TTL 동안 반복된다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from common.types import AnswerStatus, QAResult

logger = logging.getLogger(__name__)

ENV_CACHE_ENABLED = "CACHE_ENABLED"
ENV_CACHE_TTL = "CACHE_TTL_SECONDS"
ENV_CACHE_TIMEOUT = "CACHE_TIMEOUT_S"

DEFAULT_CACHE_TTL_S = 3600  # 임시 기본값. 팀이 정하면 환경변수로 바꾼다.
DEFAULT_CACHE_TIMEOUT_S = 0.5  # 캐시는 느려지면 없는 것보다 나쁘다. 세션 저장소(REDIS_TIMEOUT_S, 2초)보다 짧게 둔다.
KEY_PREFIX = "rag:answer:"  # 세션 키(rag:session:)와 키 공간을 분리한다
ENTRY_VERSION = 1  # 저장 형식이나 키 구성이 바뀌면 올린다(옛 항목은 적중하지 않는다)

_FALSE_VALUES = {"0", "false", "no", "off"}


def cache_enabled() -> bool:
    """`CACHE_ENABLED` 가 0·false·no·off 가 아니면 켠다(비어 있어도 켜짐). 평가를 돌릴 때는 꺼야 한다."""
    return os.environ.get(ENV_CACHE_ENABLED, "").strip().lower() not in _FALSE_VALUES


def cache_ttl_seconds() -> int:
    """환경변수에서 TTL(초)을 읽는다. 없거나 잘못된(0 이하·숫자 아님) 값이면 기본값."""
    raw = os.environ.get(ENV_CACHE_TTL, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CACHE_TTL_S
    return value if value > 0 else DEFAULT_CACHE_TTL_S


def cache_timeout_seconds() -> float:
    """캐시 Redis 의 연결·명령 timeout(초). 없거나 잘못된(0 이하·숫자 아님) 값이면 기본값."""
    raw = os.environ.get(ENV_CACHE_TIMEOUT, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CACHE_TIMEOUT_S
    return value if value > 0 else DEFAULT_CACHE_TIMEOUT_S


def normalize_question(question: str) -> str:
    """키에 쓰는 질문: 앞뒤 공백을 지우고 유니코드 NFC 로 맞춘다(같은 글자가 다른 코드 포인트로 와도 같은 질문이다)."""
    return unicodedata.normalize("NFC", question.strip())


@dataclass(frozen=True)
class CacheKey:
    """답을 바꿀 수 있는 모든 입력. 모듈 docstring 의 목록과 같다."""

    question: str
    retrieval_mode: str
    k: int
    index_name: str
    embedder_id: str
    fingerprint: str
    prompt_version: str
    model: str
    reasoning_effort: str
    temperature: float | None
    context_max_tokens: int

    def digest(self) -> str:
        payload = json.dumps(
            {**asdict(self), "entry_version": ENTRY_VERSION}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return KEY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AnswerCache(Protocol):
    """서비스가 캐시에 요구하는 것. 블로킹 호출이어도 된다: 서비스가 스레드로 부른다."""

    def get(self, key: str) -> QAResult | None: ...

    def put(self, key: str, result: QAResult) -> bool: ...


class RedisAnswerCache:
    """Redis 에 `QAResult` 를 JSON 으로 저장한다. 클라이언트는 주입받는다(테스트에서는 메모리 Redis)."""

    def __init__(self, client: Any, *, ttl_s: int | None = None) -> None:
        self._client = client
        self._ttl_s = ttl_s if ttl_s is not None else cache_ttl_seconds()

    def get(self, key: str) -> QAResult | None:
        """적중이면 저장된 `QAResult`, 없거나 읽을 수 없는 항목이면 None. Redis 장애는 예외로 낸다(서비스가 처리한다)."""
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            entry = json.loads(raw)
            if entry.get("v") != ENTRY_VERSION:
                return None  # 옛 형식: 없는 것으로 보고 다시 만든다
            result = QAResult.model_validate(entry["result"])
        except (ValueError, KeyError, TypeError, AttributeError):
            # 깨진 JSON, 계약이 바뀐 뒤의 항목 등. 한 건 때문에 실패하지 않고 다시 만든다(저장할 때 덮어쓴다).
            logger.warning("읽을 수 없는 캐시 항목을 없는 것으로 본다 key=%s", key, exc_info=True)
            return None
        if result.response.status is AnswerStatus.ERROR:
            return None  # 저장하지 않는 것이 원칙이지만, 들어 있어도 내보내지 않는다
        return result

    def put(self, key: str, result: QAResult) -> bool:
        """저장한다. `status=error` 는 저장하지 않고 False 를 돌려준다."""
        if result.response.status is AnswerStatus.ERROR:
            return False
        entry = {"v": ENTRY_VERSION, "result": result.model_dump(mode="json")}
        self._client.set(key, json.dumps(entry, ensure_ascii=False), ex=self._ttl_s)  # 모든 키에 TTL 이 있다
        return True


def create_answer_cache(*, client: Any | None = None) -> RedisAnswerCache:
    """환경변수(`REDIS_URL`, `CACHE_TIMEOUT_S`, `CACHE_TTL_SECONDS`)로 캐시를 만든다. 연결은 첫 사용 때 만들어진다.

    세션 저장소와 같은 Redis 를 보지만 **timeout 은 따로(기본 0.5초)** 준다: 캐시는 느려지면 없는 것보다 나쁘다.
    """
    if client is None:
        from backend.session import create_redis_client

        client = create_redis_client(timeout_s=cache_timeout_seconds())
    return RedisAnswerCache(client)


__all__ = [
    "AnswerCache",
    "CacheKey",
    "RedisAnswerCache",
    "cache_enabled",
    "cache_timeout_seconds",
    "cache_ttl_seconds",
    "create_answer_cache",
    "normalize_question",
]
