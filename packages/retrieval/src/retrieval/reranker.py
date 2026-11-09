"""리랭커: 질문과 청크를 쌍으로 cross-encoder에 넣어 점수를 다시 매긴다."""
from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence

from common.errors import IndexNotReadyError

# Cross-encoder: 질문과 문서 조각을 함께 읽고 관련성을 평가하는 모델
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_MAX_TOKENS = 512  # 질문과 청크를 함께 넣을 때 적용할 입력 길이 한도



class CrossEncoderReranker:
    """(질문, 청크 본문) 쌍에 점수를 매긴다, 점수가 높을수록 질문과 관련이 크다."""

    def __init__(
            self,
            model_name: str | None = None,
            max_tokens: int | None = None,
            scorer: Callable[[list[tuple[str, str]]],
Sequence[float]] | None = None,
    ) -> None:

        # 전달값이 참으로 평가되면 우선 사용하고, 아니면 환경 변수와 기본값을 사용 
        # .env파일을 읽어 환경변수에 넣은 작업은 app/에서 담당
        self.model_name = model_name or os.environ.get("RERANKER_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens or int(os.environ.get("RERANKER_MAX_TOKENS", DEFAULT_MAX_TOKENS))

        # 테스트에서는 실제 모델 대신 점수 계산 함수를 전달할 수 있다.
        self._scorer = scorer
        # 같은 인스턴스의 모델 로딩과 점수 계산을 한 번에 한 스레드만 수행 
        self._lock = threading.Lock()

    def check_chunk_limit(self, max_chunk_tokens: int) -> None:
        """인덱스에 기록된 청크 길이 한도를 리랭커 설정과 비교한다."""

        # 실제 질문, 청크 쌍의 길이를 세는 검사가 아니라, 설정값 간의 비교 
        if max_chunk_tokens > self.max_tokens:
            raise IndexNotReadyError(
                f"인덱스 청크 한도 ({max_chunk_tokens})가 리랭커 입력 한도 ({self.max_tokens})보다 크다"
            )

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """질문과 각 청크 본문의 관련도 점수를 입력 순서대로 돌려준다."""
        
        # 후보가 없으면 모델을 불러오지 않고 종료 
        if not texts:
            return []

        with self._lock:
            scorer = self._load()

            # 같은 질문을 각 청크와 짝지어 채점하고, 점수를 float로 통일
            # 정렬은 호출하는 검색기에서 수행 
            return [float(s) for s in scorer([(query, t) for t in texts])]


    def _load(self) -> Callable[[list[tuple[str, str]]],
Sequence[float]]:

        # 전달받은 채점 함수가 없을 때만 실제 모델을 최초 로딩
        if self._scorer is None:
            from sentence_transformers import CrossEncoder

            # 모델의 예측 함수를 저장해 다음 호출에서도 재사용
            self._scorer = CrossEncoder(self.model_name,
            max_length=self.max_tokens).predict


        return self._scorer