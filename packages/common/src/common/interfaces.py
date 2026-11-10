"""모듈 공개 인터페이스. 구현은 각 모듈 담당자가 자유롭게 하되, 아래 계약을 지킨다.

공통 약속
- 구현은 이 파일의 Protocol만 만족하면 된다. 내부 구조·라이브러리는 자유.
- 실패는 errors.py의 예외로 알린다. 빈 결과는 실패가 아니다.
- 미확인 값은 None 또는 Score(state=unavailable)로 표현하고 0으로 채우지 않는다.
- 실시간 경로(retrieve, answer, get)와, 이를 여러 건 동시에 호출하거나 외부 LLM 을 병렬로 부르는 평가기(evaluate)는 async 이다.
  호출자(배치 CLI)는 asyncio.run 으로 실행한다. 그 밖의 배치 경로(색인·골든 로딩)는 sync 이다.
  동기 구현은 asyncio.to_thread 로 감싸서 제공한다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from .types import (
    AnswerEvalRecord,
    AnswerEvaluation,
    EvidenceUnit,
    GoldenItem,
    IndexBuildRequest,
    IndexManifest,
    IndexProgress,
    QAResult,
    QueryRequest,
    RequestContext,
    RetrievalMode,
    RetrievalReport,
    RetrievalRequest,
    RetrievalResult,
    SessionInfo,
    Split,
)

ProgressCallback = Callable[[IndexProgress], None]


# ═════════════════════════ 청킹 모듈 (제공) ═════════════════════════
@runtime_checkable
class Embedder(Protocol):
    """텍스트 → 벡터. 구현은 청킹 모듈이 소유하고 검색·평가 모듈에 주입된다.

    계약
    - embedder_id 는 모델 이름뿐 아니라 접두사·정규화·최대 입력 길이 설정까지 구분한다.
      이 중 하나라도 바뀌면 점수 기준이 달라지므로 다른 id 여야 한다.
    - 인덱싱과 질의는 반드시 같은 embedder_id 를 쓴다. (IndexManifest.embedder_id 와 대조)
    - 문서용/질의용 전처리 차이(접두사 등)는 구현 내부에서 처리한다.
    - 반환 벡터 길이는 항상 dimension 이다.
    - max_input_tokens 는 접두사를 포함한 입력의 상한이다. count_tokens 도 접두사를 포함해 센다.
    - embed_query 는 한도를 넘는 입력을 조용히 자르지 않고 InvalidInputError 를 던진다.
      embed_passages 는 한도를 넘는 입력을 조용히 자르지 않고 IngestError 를 던진다.
    """

    @property
    def embedder_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_input_tokens(self) -> int: ...

    def count_tokens(self, text: str) -> int: ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class Indexer(Protocol):
    """PDF 폴더 → 청크 → 벡터 색인.

    계약
    - documents_dir 의 *.pdf 전체를 처리한다. 빠진 문서·실패는 manifest.failures 에 남긴다.
    - 빈 본문, 중복 book_id, 읽을 수 없는 PDF는 failures 에 기록하고 색인에서 뺀다 (조용히 건너뛰지 않는다).
    - book_id 는 파일명에서 .pdf 를 뺀 값, 첫 페이지는 1쪽, 파일명은 바꾸지 않는다.
    - chunk_id 는 결정적이다: 같은 문서·같은 내용·같은 청킹 조건이면 항상 같은 값 (다시 색인해도 중복이 생기지 않는다).
    - 모든 청크는 manifest.max_chunk_tokens 이하이고, 한 청크의 page_start~page_end 는 실제로 걸친 페이지다.
    - 같은 index_name 이 있으면 rebuild=True 일 때만 덮어쓴다. 아니면 IngestError.
    - 색인된 payload 는 types.Chunk 스키마를 따른다.
    - 질문·정답·채점 기준 JSON 은 색인하지 않는다.
    - 오래 걸리는 작업이므로 progress 콜백에 단계별 진행 상황을 알린다 (선택).
    """

    def build(
        self, request: IndexBuildRequest, progress: ProgressCallback | None = None
    ) -> IndexManifest: ...

    def get_manifest(self, index_name: str) -> IndexManifest | None: ...


@runtime_checkable
class GoldenDatasetProvider(Protocol):
    """제공 평가 파일 → GoldenItem 목록. 평가 파일 필드 매핑은 구현이 책임진다.

    계약
    - 정답이 든 파일(development.json · additional.json · security_tasks.json)을 읽는다.
      질문만 든 *_questions.json 은 서비스 입력 점검용이며 같은 id·질문이어야 한다.
    - splits=None 이면 security 를 제외한 전체를 돌려준다.
    - id 는 전체에서 유일하다. evidence_groups 의 book_id·page 는 실제 PDF 범위 안에 있어야 한다.
    - 반환값은 평가기·러너만 쓴다. 서비스(검색·생성)에는 item.question 만 전달한다.
    - fingerprint 는 같은 문항·정답이면 같은 값이다 (순서 있는 id 와 평가 필드의 해시).
    """

    def load(self, splits: Sequence[Split] | None = None) -> list[GoldenItem]: ...

    def fingerprint(self, splits: Sequence[Split] | None = None) -> str: ...


# ═════════════════════════ 검색 모듈 (제공) ═════════════════════════
@runtime_checkable
class Retriever(Protocol):
    """질의 → 근거 청크. 세 검색 방식은 mode 로만 바꾼다 (서비스를 따로 만들지 않는다).

    계약
    - supported_modes 에 없는 mode 가 오면 ValueError 가 아니라 RetrievalError.
    - 결과는 len ≤ k, rank 는 1부터 연속 오름차순, chunk_id 중복 없음.
    - 빈 결과는 정상(예외 아님). 인덱스·임베더 불일치는 IndexNotReadyError.
    - 질문이 임베더 한도를 넘으면 InvalidInputError 를 그대로 전파한다 (RetrievalError 로 감싸지 않는다).
    - 점수 임계값은 방식마다 척도가 달라 검색 모듈 내부 설정이다. 요청으로 받지 않는다.
    - 생성 시점에 인덱스 manifest 의 max_chunk_tokens 를 자신의 모델(리랭커 등) 입력 한도와 대조하고,
      안 맞으면 IndexNotReadyError 로 알린다. 조용히 잘라서 쓰지 않는다.
    - 같은 요청에서 모드 간 임베딩·저장소·k 는 같다. 정답·평가 정보를 참조하지 않는다.
    - index 는 생성 시 주입받은 IndexManifest 그대로다. 평가기(보고서의 index_name·index_fingerprint)와
      백엔드(캐시 키의 index_name+embedder_id)가 이 값으로 인덱스의 신원을 안다.
    """

    @property
    def supported_modes(self) -> Sequence[RetrievalMode]: ...

    @property
    def index(self) -> IndexManifest: ...

    async def retrieve(self, request: RetrievalRequest, ctx: RequestContext) -> RetrievalResult: ...


@runtime_checkable
class RetrievalEvaluator(Protocol):
    """Hit@k / Recall@k. 근거 그룹 단위로 계산한다.

    계약
    - 한 문항의 근거는 evidence_groups 다. 그룹끼리는 모두 필요(AND), 그룹 안 후보는 하나만 맞으면 된다(OR).
      그룹이 만족되면 satisfied. Hit@k = 만족한 그룹이 하나라도 있으면 1, Recall@k = 만족한 그룹 수 / 전체 그룹 수.
    - unit=DOCUMENT 는 book_id 가 같으면 일치, unit=PAGE 는 검색된 청크의 [page_start, page_end] 가
      근거 페이지를 포함해야 일치한다. 같은 근거가 여러 청크에서 나와도 한 번만 센다.
    - unit 은 호출자가 명시한다 (기본값 없음). 어느 단위로 보고했는지는 report.unit 에 남는다.
    - 근거 그룹이 없는 문항은 Score(state=not_applicable).
    - 검색 결과가 비어도 근거가 있는 문항은 제외하지 않고 0점으로 센다.
    - 호출 실패는 해당 문항을 unavailable 로 두고 평균에서 제외한다.
    - k 가 그룹 수보다 작으면 Recall 만점이 불가능하다. 보고서의 k 와 함께 해석한다.
    - 보고서에 index_name · index_fingerprint(주입받은 retriever.index 의 값) 와 golden_fingerprint 를 남긴다.
      golden_fingerprint 는 평가기가 골든 제공자를 모르므로 호출자가 GoldenDatasetProvider.fingerprint 값을 넘긴다
      (안 넘기면 None).
    """

    async def evaluate(
        self,
        items: Sequence[GoldenItem],
        mode: RetrievalMode,
        k: int,
        unit: EvidenceUnit,
        golden_fingerprint: str | None = None,
    ) -> RetrievalReport: ...


# ═════════════════════════ 백엔드 모듈 (제공) ═════════════════════════
@runtime_checkable
class QAService(Protocol):
    """질문 → 검색 → 프롬프트·모델 호출 → 검증 → 출처 매핑 → 응답.

    계약
    - 검색은 주입받은 Retriever 로만 한다. 검색 모듈 구현을 직접 import 하지 않는다.
    - 검색 결과(또는 토큰 예산 적용 후 문맥)가 비면 모델을 호출하지 않고 abstained 로 응답한다.
    - 모델 출력은 코드로 검증한다: 필수 필드, status 값, source_id ∈ 이번 요청 문맥.
      문서명·페이지는 모델이 쓰지 않고 코드가 chunk 정보로 채운다.
    - status=error 는 코드만 부여한다 (LLM이 정하지 않는다). 근거 부족은 abstained.
    - 모든 반환은 QueryResponse 계약을 지킨다. 예외를 호출자에게 던지지 않고
      status=error + error_code 로 돌려준다 (프로그래밍 오류 제외).
      InvalidInputError 는 error_code=invalid_input 으로 매핑한다.
    - ctx.request_id 로 질문·검색 문서·실제 모델 입출력·시간·토큰을 Langfuse에 묶어 기록한다.
      기록에 성공하면 meta.trace_id 를 반드시 채운다 (점수·피드백을 trace_id 에 붙인다).
    - 비용(cost_usd)은 모델 사용량으로 계산할 수 있을 때만 채우고, 모르면 None 이다.
    - 캐시 적중이어도 같은 스키마를 돌려주고 meta.cache_hit=True 로 표시한다.
    - final_context 는 모델에 실제 전달한 문맥과 같아야 한다 (평가 입력).
    - request.session_id 가 있으면 끝난 질의응답을 세션 turn 으로 기록한다 (SessionService 참고).
    - request.session_id 가 있으면 같은 세션의 이전 질의응답(turn)을 답변에 반영한다 (멀티턴).
      반영할 turn 수와 방식은 구현이 정한다. 이력을 쓴 요청은 캐시 키에 이력을 반영하거나 캐시를 우회한다.
    """

    async def answer(self, request: QueryRequest, ctx: RequestContext) -> QAResult: ...


@runtime_checkable
class SessionService(Protocol):
    """세션 조회. 기록은 QAService 가 쓰고 이 서비스가 읽는다. 이력은 영구 저장되며 만료되지 않는다.

    계약
    - 한 번도 기록되지 않은 세션은 None 을 돌려준다 (예외 아님). 라우터가 404 + ApiError 로 바꾼다.
      세션은 만료되지 않으므로 SessionInfo.expires_at 은 항상 None 이다.
    - turns 는 오래된 것 → 최신 순으로 최근 limit 개만, turn_count 는 전체 개수.
    - status=error 응답은 turn 으로 기록하지 않는다.
    - 기록하는 question 은 이메일·API 키 모양 문자열을 가린 값이다 (대화 복원 때 입력 원문과 다를 수 있다).
    - 세션 ID 를 아는 사람은 누구나 조회할 수 있다 (인증 없음). 추측 불가능한 값(UUID)을 쓴다.
    """

    async def get(self, session_id: str, limit: int = 20) -> SessionInfo | None: ...


@runtime_checkable
class AnswerEvaluator(Protocol):
    """RAGAS Faithfulness(+선택 지표) + LLM-as-a-Judge(사실·조건·근거·판단).

    계약
    - 입력 순서와 같은 순서로 평가 결과를 돌려준다 (len 동일).
    - 사실 주장이 없는 응답의 Faithfulness 는 not_applicable, 평가 호출 실패는 unavailable.
    - 정답·채점 기준(GradingSpec)은 평가 호출에만 전달한다. 서비스 생성 입력이나 final_context 에 섞지 않는다.
    - 선택 지표(answer_relevancy · context_recall · context_precision)는 ragas_extra 에 키로 담는다.
      answer_relevancy 는 질문 임베딩이 필요하므로 생성 시 Embedder 를 주입받는다.
    - 보안 문항은 security.bad_claims 가 응답에 나타나면 해당 항목을 감점한다 (판정 방식은 구현이 정한다).
    - 채점 호출의 시간·토큰은 서비스 응답의 meta 에 합산하지 않는다.
    """

    async def evaluate(self, records: Sequence[AnswerEvalRecord]) -> list[AnswerEvaluation]: ...
