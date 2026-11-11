"""packages/common 에서 계약을 추출해 contracts/viewer.html 을 만든다.

실행:  uv run python scripts/build_contract_viewer.py
계약(코드)이 바뀌면 다시 실행한다. 손으로 고치지 않는다.
"""

from __future__ import annotations

import enum
import inspect
import json
import types as pytypes
import typing
from pathlib import Path

import annotated_types as at
from pydantic import BaseModel

from common import api, interfaces, types

ROOT = Path(__file__).resolve().parents[1]


def fmt(a) -> str:
    if a is type(None):
        return "None"
    origin = typing.get_origin(a)
    if origin is None:
        return getattr(a, "__name__", str(a)).replace("typing.", "")
    args = typing.get_args(a)
    if origin in (typing.Union, pytypes.UnionType):
        return " | ".join(fmt(x) for x in args)
    if origin is typing.Literal:
        return "Literal[" + ", ".join(repr(x) for x in args) + "]"
    name = getattr(origin, "__name__", str(origin))
    return f"{name}[{', '.join(fmt(x) for x in args)}]"


def constraints(field) -> list[str]:
    out = []
    for m in field.metadata:
        if isinstance(m, at.Ge):
            out.append(f"≥ {m.ge}")
        elif isinstance(m, at.Le):
            out.append(f"≤ {m.le}")
        elif isinstance(m, at.MinLen):
            out.append(f"최소 길이 {m.min_length}")
        elif isinstance(m, at.MaxLen):
            out.append(f"최대 길이 {m.max_length}")
        elif getattr(m, "pattern", None):
            out.append(f"패턴 {m.pattern}")
    return out


def default_text(field) -> str | None:
    if field.is_required():
        return None
    if field.default_factory is not None:
        return repr(field.default_factory())
    d = field.default
    return repr(d.value) if isinstance(d, enum.Enum) else repr(d)


# 코드로 표현된 불변식(validator)을 사람이 읽는 문장으로. 코드의 validator와 같이 바꾼다.
INVARIANTS = {
    "Chunk": ["page_end ≥ page_start"],
    "GoldenItem": [
        "evidence_groups: 그룹끼리는 모두 필요(AND), 한 그룹 안의 후보는 하나만 맞으면 됨(OR). 빈 그룹 금지",
        "security 정보는 split=security 문항만, 그리고 반드시 가진다",
    ],
    "IndexManifest": ["fingerprint는 순서 있는 (chunk_id, text) 해시", "모든 청크는 max_chunk_tokens 이하 (임베더 토큰화 기준, 접두사 포함)"],
    "Score": ["state=scored 일 때만 value를 가진다 (미확인 값을 0으로 채우지 않는다)"],
    "QueryRequest": ["공백만 있는 질문은 거부", "session_id는 영문·숫자·_·- 8~128자 (Redis 키로 쓰이므로)"],
    "SessionInfo": ["turns 개수는 turn_count를 넘을 수 없다"],
    "QueryResponse": [
        "error_code는 status=error 일 때만, 그리고 반드시 가진다",
        "status=answered 이면 citations가 1개 이상",
    ],
}

GROUPS = [
    ("열거형", ["RetrievalMode", "AnswerStatus", "ErrorCode", "Split", "ExpectedAction", "EvidenceUnit", "ScoreState"]),
    ("공통", ["RequestContext", "Score"]),
    ("청킹", ["Chunk", "IngestFailure", "IndexBuildRequest", "IndexProgress", "IndexManifest",
            "EvidenceRef", "GradingSpec", "SecurityInfo", "GoldenItem"]),
    ("검색", ["RetrievalRequest", "RetrievedChunk", "RetrievalResult", "RetrievalItemMetrics", "RetrievalReport"]),
    (
        "백엔드 · API",
        ["QueryRequest", "Citation", "QueryMeta", "QueryResponse", "ContextItem", "QAResult",
         "HealthResponse", "SessionTurn", "SessionInfo", "ApiError", "AnswerEvalRecord", "JudgeScores", "AnswerEvaluation"],
    ),
]


def extract_types() -> dict:
    out = {}
    for name, obj in vars(types).items():
        if not inspect.isclass(obj) or obj.__module__ != types.__name__ or name == "_Contract":
            continue
        if issubclass(obj, enum.Enum):
            out[name] = {
                "kind": "enum",
                "doc": inspect.cleandoc(obj.__doc__ or ""),
                "values": [{"name": m.name, "value": m.value} for m in obj],
            }
        elif issubclass(obj, BaseModel):
            fields = []
            for fname, f in obj.model_fields.items():
                fields.append({
                    "name": fname,
                    "type": fmt(f.annotation),
                    "required": f.is_required(),
                    "default": default_text(f),
                    "constraints": constraints(f),
                })
            out[name] = {
                "kind": "model",
                "doc": inspect.cleandoc(obj.__doc__ or ""),
                "fields": fields,
                "invariants": INVARIANTS.get(name, []),
            }
    return out


def parse_doc(doc: str) -> tuple[str, list[str]]:
    lines = inspect.cleandoc(doc).splitlines()
    if "계약" in lines:
        i = lines.index("계약")
        head, body = lines[:i], lines[i + 1:]
    else:
        head, body = lines, []
    rules: list[str] = []
    for ln in body:
        if ln.startswith("- "):
            rules.append(ln[2:].strip())
        elif ln.strip() and rules:
            rules[-1] += " " + ln.strip()
    return " ".join(x.strip() for x in head if x.strip()), rules


def extract_interfaces() -> dict:
    out = {}
    for name, cls in vars(interfaces).items():
        if not inspect.isclass(cls) or cls.__module__ != interfaces.__name__:
            continue
        if not getattr(cls, "_is_protocol", False) or name == "Protocol":
            continue
        summary, rules = parse_doc(cls.__doc__ or "")
        members = []
        for mname, v in cls.__dict__.items():
            if mname.startswith("_"):
                continue
            if isinstance(v, property):
                sig = inspect.signature(v.fget)
                members.append({"name": mname, "kind": "property", "async": False,
                                "sig": f"{mname}: {sig.return_annotation}"})
            elif callable(v):
                sig = inspect.signature(v)
                ps = []
                for p in list(sig.parameters.values())[1:]:
                    s = f"{p.name}: {p.annotation}"
                    if p.default is not inspect.Parameter.empty:
                        s += f" = {p.default!r}"
                    ps.append(s)
                a = inspect.iscoroutinefunction(v)
                members.append({"name": mname, "kind": "method", "async": a,
                                "sig": f"{'async ' if a else ''}{mname}({', '.join(ps)}) -> {sig.return_annotation}"})
        out[name] = {"summary": summary, "rules": rules, "members": members}
    return out


MODULES = [
    {"id": "chunking", "name": "청킹", "scope": "문서 청킹·인덱싱 · 검색 청크 골든 데이터셋",
     "provides": ["Embedder", "Indexer", "GoldenDatasetProvider"], "injected": [],
     "entry": ["create_embedder()", "create_indexer(embedder)", "create_golden_provider()"],
     "types": ["Chunk", "IndexManifest", "IndexBuildRequest", "IndexProgress", "IngestFailure", "GoldenItem", "EvidenceRef",
               "GradingSpec", "SecurityInfo", "Split", "ExpectedAction"]},
    {"id": "retrieval", "name": "검색", "scope": "RAG 구현 · 검색 청크 품질 테스트",
     "provides": ["Retriever", "RetrievalEvaluator"], "injected": ["Embedder", "IndexManifest"],
     "entry": ["create_retriever(embedder, index)", "create_retrieval_evaluator(retriever)"],
     "types": ["RetrievalMode", "RetrievalRequest", "RetrievalResult", "RetrievedChunk", "RetrievalReport", "RetrievalItemMetrics",
               "EvidenceUnit", "GoldenItem", "EvidenceRef", "Score"]},
    {"id": "backend", "name": "백엔드", "scope": "FastAPI · LangChain · Langfuse · Redis",
     "provides": ["QAService", "SessionService", "AnswerEvaluator"], "injected": ["Retriever", "IndexManifest"],
     "entry": ["create_qa_service(retriever)", "create_session_service()", "create_answer_evaluator(embedder)",
               "create_router(qa_service, session_service, index)"],
     "types": ["QueryRequest", "QueryResponse", "QAResult", "ContextItem", "Citation", "QueryMeta", "HealthResponse",
               "SessionInfo", "SessionTurn", "ApiError", "AnswerEvalRecord", "AnswerEvaluation", "JudgeScores", "RequestContext", "AnswerStatus", "ErrorCode"]},
    {"id": "frontend", "name": "프론트엔드", "scope": "React 클라이언트",
     "provides": [], "injected": [], "entry": [],
     "types": ["QueryRequest", "QueryResponse", "HealthResponse", "SessionInfo", "SessionTurn", "ApiError", "AnswerStatus", "Citation", "QueryMeta", "RetrievalMode", "ErrorCode"]},
]

FLOWS = [
    {"id": "flow-index", "from": "청킹", "to": "검색", "via": "Qdrant 인덱스",
     "types": ["Chunk", "IndexManifest"],
     "rules": ["색인 payload는 Chunk 스키마를 따른다",
               "질의 임베딩의 embedder_id(모델·접두사·정규화·최대 길이)는 IndexManifest.embedder_id와 같아야 한다 (다르면 IndexNotReadyError)",
               "모든 청크는 manifest.max_chunk_tokens 이하여야 하고, 검색은 시작 시 자기 리랭커 한도와 대조한다",
               "manifest.fingerprint가 다른 인덱스끼리는 평가 결과를 비교하지 않는다",
               "빠진 문서·실패는 manifest.failures에 남긴다 (조용히 건너뛰지 않는다)",
               "질문·정답·채점 기준 JSON은 색인하지 않는다"]},
    {"id": "flow-retrieve", "from": "검색", "to": "백엔드", "via": "Retriever.retrieve()",
     "types": ["RetrievalRequest", "RetrievalResult", "RetrievedChunk"],
     "rules": ["결과 길이 ≤ k, rank는 1부터 연속, chunk_id 중복 없음",
               "빈 결과는 정상 (예외 아님)",
               "세 검색 방식은 mode로만 바꾼다. 같은 임베딩·저장소·k를 쓴다",
               "질문이 임베더 한도를 넘으면 InvalidInputError가 그대로 전파된다 (HTTP 400)",
               "백엔드는 검색 구현을 import하지 않고 주입받은 Retriever로만 호출한다"]},
    {"id": "flow-http", "from": "백엔드", "to": "프론트엔드", "via": "HTTP /query · /health · /session",
     "types": ["QueryRequest", "QueryResponse", "HealthResponse", "SessionInfo"],
     "rules": ["정상 처리된 answered · needs_clarification · abstained 는 모두 200, 입력 검증 실패는 422",
               "status=error 는 서버 코드만 부여하고 error_code가 HTTP 상태를 결정한다",
               "answered 응답은 출처(문서명·페이지)를 1개 이상 가진다",
               "source_id(S1…)는 요청 안에서만 유효하며 화면에 노출하지 않는다",
               "GET /session/{id}: 없거나 만료된 세션은 404 + ApiError(session_not_found). 세션 ID는 클라이언트가 UUID로 만들어 보낸다"]},
]

STATUS_UI = {
    "answered": "답변 + 출처(문서명·페이지)",
    "needs_clarification": "되묻는 문장 + 보완 질문 입력",
    "abstained": "보류 이유 + 필요한 자료 설명 (오류처럼 보이지 않게 구분)",
    "error": "사용자용 오류 문구. error_code는 로그용",
}


def main() -> None:
    examples = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((ROOT / "contracts" / "examples").glob("*.json"))}
    data = {
        "types": extract_types(),
        "groups": GROUPS,
        "interfaces": extract_interfaces(),
        "modules": MODULES,
        "flows": FLOWS,
        "http": {
            "paths": {"health": api.PATH_HEALTH, "query": api.PATH_QUERY, "session": api.PATH_SESSION},
            "sessionNotFound": api.HTTP_SESSION_NOT_FOUND,
            "sessionLimit": {"default": api.SESSION_DEFAULT_LIMIT, "max": api.SESSION_MAX_LIMIT},
            "errors": {k.value: v for k, v in api.ERROR_HTTP_STATUS.items()},
            "statusUi": STATUS_UI,
        },
        "examples": examples,
    }
    # 모든 모듈이 가리키는 이름이 실제로 존재하는지 검증 (문서와 코드 어긋남 방지)
    for m in MODULES:
        for n in m["provides"] + m["injected"]:
            assert n in data["interfaces"] or n in data["types"], f"unknown: {n}"
        for n in m["types"]:
            assert n in data["types"], f"unknown type: {n}"
    for f in FLOWS:
        for n in f["types"]:
            assert n in data["types"], f"unknown type: {n}"
    grouped = {n for _, names in GROUPS for n in names}
    assert grouped == set(data["types"]), f"그룹 누락: {set(data['types']) ^ grouped}"

    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    tpl = (ROOT / "scripts" / "viewer_template.html").read_text(encoding="utf-8")
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="기본값은 contracts/viewer.html (build_contract_manifest --check 가 임시 경로로 재생성해 비교한다)")
    out = ap.parse_args().out or ROOT / "contracts" / "viewer.html"
    out.write_text(tpl.replace("/*__DATA__*/", blob), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB), types={len(data['types'])}, interfaces={len(data['interfaces'])}")


if __name__ == "__main__":
    main()
