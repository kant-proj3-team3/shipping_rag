"""모듈 간 공유 데이터 타입.

모든 타입은 불변(frozen)이고 정의되지 않은 필드를 거부한다(extra="forbid").
필드를 추가·삭제·변경하는 것은 계약 변경이다. (CONTRACTS.md의 '변경 절차' 참고)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# 세션 ID: 클라이언트가 UUID 등으로 만들어 보낸다. Redis 키로 쓰이므로 문자 범위를 제한한다.
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{8,128}$"


# ── 열거형 ────────────────────────────────────────────────────────────
class RetrievalMode(StrEnum):
    """세 가지 필수 RAG 검색 방식."""

    NAIVE = "naive"  # Dense 검색
    HYBRID = "hybrid"  # Dense + 키워드(BM25) 결합
    HYBRID_RERANK = "hybrid_rerank"  # 하이브리드 + 리랭킹


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    ABSTAINED = "abstained"
    ERROR = "error"  # LLM이 아니라 서버 코드가 부여한다


class ErrorCode(StrEnum):
    """status=error 일 때만 쓰는 오류 분류. 근거 부족(abstained)과 섞지 않는다."""

    INDEX_NOT_READY = "index_not_ready"
    RETRIEVAL_FAILED = "retrieval_failed"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_FAILED = "model_failed"
    OUTPUT_INVALID = "output_invalid"  # 모델 출력 JSON·자료 ID 검증 실패
    INGEST_FAILED = "ingest_failed"  # 인덱싱 단계 전용 (API 응답에는 쓰지 않음)
    INVALID_INPUT = "invalid_input"  # 형식은 맞지만 처리할 수 없는 입력 (예: 임베딩 한도를 넘는 질문)
    SESSION_NOT_FOUND = "session_not_found"  # GET /session 의 404 전용 (QueryResponse에는 쓰지 않음)
    INTERNAL = "internal"


class Split(StrEnum):
    """제공 평가 파일과 대응: development.json / additional.json / security_tasks.json.
    expansion_validation 은 Basic 난이도에만 있다. 질문만 담은 *_questions.json 은 split 이 아니다.
    """

    DEVELOPMENT = "development"
    ADDITIONAL = "additional"
    EXPANSION_VALIDATION = "expansion_validation"  # Basic 전용
    SECURITY = "security"


class ExpectedAction(StrEnum):
    """평가 파일의 expected_action. API 상태와 이름만 다르다 (answer→answered 등)."""

    ANSWER = "answer"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"


class EvidenceUnit(StrEnum):
    """검색 평가에서 근거 일치를 판단하는 단위."""

    DOCUMENT = "document"  # book_id 가 같으면 일치
    PAGE = "page"  # 청크의 페이지 범위가 근거 페이지를 포함해야 일치


class ScoreState(StrEnum):
    SCORED = "scored"
    NOT_APPLICABLE = "not_applicable"  # 해당 없음 (평균에서 제외)
    UNAVAILABLE = "unavailable"  # 평가 불가 (호출·계산 실패, 평균에서 제외)


# ── 요청 공통 ─────────────────────────────────────────────────────────
class RequestContext(_Contract):
    """요청 하나를 가로지르는 식별자. 서버가 만들고 모든 호출에 전달한다."""

    request_id: str = Field(min_length=1)
    trace_id: str | None = None  # Langfuse trace


# ── 청킹 모듈 산출물 ──────────────────────────────────────────────────
class Chunk(_Contract):
    """검색 단위. Qdrant payload는 이 스키마를 따른다."""

    chunk_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)  # PDF 파일명에서 .pdf를 뺀 값 (FB01.pdf → FB01)
    file_name: str  # 원본 파일명 그대로
    title: str | None = None  # PDF 문서 제목 (없으면 None). 프롬프트 문맥 표시에 쓴다
    page_start: int = Field(ge=1)  # 첫 페이지 = 1
    page_end: int = Field(ge=1)
    text: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)  # 모듈 내부 확장용

    @model_validator(mode="after")
    def _pages(self) -> Self:
        if self.page_end < self.page_start:
            raise ValueError("page_end는 page_start 이상이어야 한다")
        return self


class IngestFailure(_Contract):
    book_id: str
    stage: str  # 예: "parse", "chunk", "index"
    reason: str


class IndexProgress(_Contract):
    """장시간 인덱싱의 진행 상황. 콜백으로 전달한다."""

    stage: str  # 예: "parse", "chunk", "embed", "upsert"
    done: int = Field(ge=0)
    total: int = Field(ge=0)


class IndexBuildRequest(_Contract):
    documents_dir: Path  # documents/*.pdf 가 있는 폴더
    index_name: str = Field(min_length=1)
    rebuild: bool = False
    params: dict[str, JsonValue] = Field(default_factory=dict)  # 청킹 모듈 내부 옵션


class IndexManifest(_Contract):
    """인덱스 하나의 신원 증명. 청킹이 쓰고 검색·백엔드가 읽는다."""

    index_name: str
    embedder_id: str  # 질의 임베딩이 반드시 같은 값이어야 한다
    embedding_dim: int = Field(ge=1)
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)  # 순서 있는 (chunk_id, text) 해시. 결과의 비교 가능성 확인용
    max_chunk_tokens: int = Field(ge=1)  # 모든 청크가 이 토큰 수 이하 (임베더 토큰화 기준, 접두사 포함)
    created_at: datetime
    params: dict[str, JsonValue] = Field(default_factory=dict)  # 재현용 기록
    failures: list[IngestFailure] = Field(default_factory=list)  # 누락·실패 기록


# ── 골든 데이터셋 ─────────────────────────────────────────────────────
class EvidenceRef(_Contract):
    """정답 근거 한 곳. quote 는 PDF 해당 페이지에 실제로 있는 원문이다."""

    book_id: str
    page: int = Field(ge=1)  # 첫 페이지 = 1
    quote: str | None = None  # 평가·디버깅용. 서비스 경로로 넘기지 않는다


class GradingSpec(_Contract):
    """답변 채점용 정보. 서비스 생성 입력으로 넘기지 않는다."""

    required_facts: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)  # 답이 성립하는 전제 조건
    grading_notes: str | None = None


class SecurityInfo(_Contract):
    """보안 문항 전용. 공격 문구는 이미 코퍼스 문서(external_source_id)에 들어 있다."""

    attack_type: str  # 예: indirect_prompt_injection, context_poisoning
    external_source_id: str  # 공격 문구가 든 문서의 book_id
    source_page: int = Field(ge=1)
    attack_text: str
    bad_claims: list[str] = Field(default_factory=list)  # 공격에 넘어갔을 때 나오는 주장


class GoldenItem(_Contract):
    """평가 질문 한 건. 서비스에는 question 만 전달하고 나머지는 평가기·러너만 쓴다."""

    id: str
    split: Split
    question: str
    expected_action: ExpectedAction
    reference_answer: str | None = None
    # 그룹끼리는 모두 필요(AND), 한 그룹 안의 후보는 하나만 맞으면 된다(OR).
    # 비어 있으면 검색 지표는 '해당 없음' (예: 되묻기 문항).
    evidence_groups: list[list[EvidenceRef]] = Field(default_factory=list)
    grading: GradingSpec = Field(default_factory=GradingSpec)
    security: SecurityInfo | None = None

    @model_validator(mode="after")
    def _security(self) -> Self:
        if (self.split is Split.SECURITY) != (self.security is not None):
            raise ValueError("security 정보는 split=security 문항만, 그리고 반드시 가진다")
        if any(len(g) == 0 for g in self.evidence_groups):
            raise ValueError("빈 근거 그룹은 허용하지 않는다")
        return self


# ── 검색 모듈 ─────────────────────────────────────────────────────────
class RetrievalRequest(_Contract):
    query: str = Field(min_length=1)
    mode: RetrievalMode
    k: int = Field(ge=1, le=50)  # 최종 청크 수. 세 방식에서 같은 값을 쓴다


class RetrievedChunk(_Contract):
    rank: int = Field(ge=1)  # 1이 가장 관련 높음
    score: float  # 방식 내부 점수. 방식 간 비교 금지
    chunk: Chunk


class RetrievalResult(_Contract):
    mode: RetrievalMode
    k: int
    chunks: list[RetrievedChunk]  # 길이 ≤ k, rank 오름차순, chunk_id 중복 없음. 빈 목록은 정상
    latency_ms: float | None = None


class Score(_Contract):
    value: float | None = None
    state: ScoreState
    reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.state is ScoreState.SCORED) != (self.value is not None):
            raise ValueError("value는 state가 scored일 때만 가진다 (미확인 값을 0으로 채우지 않는다)")
        return self


class RetrievalItemMetrics(_Contract):
    item_id: str
    hit: Score  # 만족한 그룹이 하나라도 있으면 1
    recall: Score  # 만족한 그룹 수 / 전체 그룹 수
    groups_total: int = Field(ge=0)
    satisfied_groups: list[int] = Field(default_factory=list)  # 만족한 그룹의 인덱스


class RetrievalReport(_Contract):
    mode: RetrievalMode
    k: int
    unit: EvidenceUnit
    index_name: str
    index_fingerprint: str  # IndexManifest.fingerprint. 다른 인덱스끼리의 비교를 막는다
    golden_fingerprint: str | None = None  # GoldenDatasetProvider.fingerprint
    items: list[RetrievalItemMetrics]
    hit_at_k_mean: float | None  # scored 문항만의 평균
    recall_at_k_mean: float | None
    scored: int
    not_applicable: int
    unavailable: int


# ── 백엔드 모듈 / API ─────────────────────────────────────────────────
class QueryRequest(_Contract):
    question: str = Field(max_length=500)
    retrieval_mode: RetrievalMode | None = None  # 없으면 서버 기본값
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)  # 없으면 세션 기록 없이 단발 처리

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("빈 질문은 허용하지 않는다")
        return v


class Citation(_Contract):
    source_id: str  # 이번 요청 안에서만 유효한 자료 ID (S1, S2 ...)
    book_id: str
    file_name: str
    page: int = Field(ge=1)


class QueryMeta(_Contract):
    retrieval_mode: RetrievalMode
    latency_ms: float | None = None  # 요청 수신 ~ 응답 반환
    input_tokens: int | None = None  # 확인 못 한 값은 None (0 금지)
    output_tokens: int | None = None
    cost_usd: float | None = None  # 확인 못 하면 None (0은 확인된 무료)
    cache_hit: bool = False
    trace_id: str | None = None


class QueryResponse(_Contract):
    request_id: str
    status: AnswerStatus
    answer: str  # 답변, 되묻는 질문, 보류 설명 또는 사용자용 오류 문구
    reason: str  # 판단 이유 (짧게)
    citations: list[Citation] = Field(default_factory=list)
    error_code: ErrorCode | None = None
    meta: QueryMeta

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.status is AnswerStatus.ERROR) != (self.error_code is not None):
            raise ValueError("error_code는 status=error 일 때만, 그리고 반드시 가진다")
        if self.status is AnswerStatus.ANSWERED and not self.citations:
            raise ValueError("answered 응답은 출처를 1개 이상 가져야 한다")
        return self


class ContextItem(_Contract):
    """모델에 실제로 전달한 최종 문맥의 한 조각."""

    source_id: str
    chunk: Chunk


class QAResult(_Contract):
    """QAService 반환값. API는 response만 내보내고, final_context는 평가용이다."""

    response: QueryResponse
    final_context: list[ContextItem] = Field(default_factory=list)


class SessionTurn(_Contract):
    """세션에 기록된 질의응답 한 번. status=error 응답은 기록하지 않는다."""

    request_id: str
    asked_at: datetime
    question: str
    retrieval_mode: RetrievalMode
    status: AnswerStatus  # answered | needs_clarification | abstained
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class SessionInfo(_Contract):
    """GET /session/{session_id} 응답."""

    session_id: str
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime | None = None  # 만료 시각을 모르거나 만료 없음이면 None
    turn_count: int = Field(ge=0)  # 전체 질의응답 수
    turns: list[SessionTurn] = Field(default_factory=list)  # 오래된 것 → 최신 순, 최근 limit 개만

    @model_validator(mode="after")
    def _counts(self) -> Self:
        if len(self.turns) > self.turn_count:
            raise ValueError("turns 개수는 turn_count를 넘을 수 없다")
        return self


class ApiError(_Contract):
    """QueryResponse가 아닌 오류 응답(현재는 /session 404)."""

    error_code: ErrorCode
    message: str


class HealthResponse(_Contract):
    status: Literal["ok"] = "ok"
    index_ready: bool
    index_name: str | None = None
    embedder_id: str | None = None
    supported_modes: list[RetrievalMode] = Field(default_factory=list)


# ── 답변 평가 ─────────────────────────────────────────────────────────
class AnswerEvalRecord(_Contract):
    item: GoldenItem
    result: QAResult


class JudgeScores(_Contract):
    """LLM-as-a-Judge 네 항목. 각 항목 0/1."""

    facts: Score
    conditions: Score
    evidence: Score
    decision: Score


class AnswerEvaluation(_Contract):
    item_id: str
    request_id: str
    faithfulness: Score  # RAGAS Faithfulness
    ragas_extra: dict[str, Score] = Field(default_factory=dict)  # answer_relevancy · context_recall · context_precision 등 선택 지표
    judge: JudgeScores
