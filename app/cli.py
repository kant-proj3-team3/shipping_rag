"""배치 CLI.

    python -m app.cli index [--rebuild]
    python -m app.cli eval --k 5 --unit page                         # 검색 평가: 세 방식 비교
    python -m app.cli eval-answer [--split development] [--limit N]  # 답변 평가(RAGAS + Judge): 세 방식 비교
    python -m app.cli compare-security [--mode hybrid]               # 보안 문항을 기본·방어 프롬프트로 비교

실행하면 기본은 실제 구현으로 조립된다(`APP_IMPL=mock` 이면 목업). 평가 러너의 위치(CONTRACTS.md 5장 3번)는 팀 결정 대기 중이라
`app/runner.py` 에 두었고, 팀이 다르게 정하면 옮긴다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from common.errors import ContractError
from common.types import EvidenceUnit, IndexBuildRequest, IndexProgress, RetrievalMode, Split

from . import runner
from .envfile import load_env_file
from .wiring import apply_impl_default, build_base, build_services, index_name

REPORT_DIR = Path("eval_reports")
# 보고서에 남기는 설정(키·주소 제외). 같은 설정끼리만 점수를 비교하기 위한 기록이다.
_SETTINGS = (
    "APP_IMPL",
    "LLM_MODEL",
    "LLM_REASONING_EFFORT",
    "LLM_TEMPERATURE",
    "EVAL_MODEL",
    "EVAL_RAGAS_EXTRA",
    "CONTEXT_MAX_TOKENS",
)


def _progress(p: IndexProgress) -> None:
    print(f"  [{p.stage}] {p.done}/{p.total}")


def cmd_index(args: argparse.Namespace) -> int:
    base = build_base()
    manifest = base.indexer.build(
        IndexBuildRequest(
            documents_dir=Path(os.environ.get("DOCUMENTS_DIR", "./data/documents")),
            index_name=index_name(),
            rebuild=args.rebuild,
        ),
        progress=_progress,
    )
    print(f"index={manifest.index_name} docs={manifest.document_count} chunks={manifest.chunk_count}")
    print(f"embedder_id={manifest.embedder_id} fingerprint={manifest.fingerprint}")
    for f in manifest.failures:
        print(f"  ! 실패 {f.book_id} [{f.stage}] {f.reason}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    base = build_base()
    manifest = base.indexer.get_manifest(index_name())
    if manifest is None:
        print("인덱스가 없다. 먼저 index 를 실행한다.")
        return 1
    svc = build_services(base, manifest)
    items = base.golden.load()
    golden_fp = base.golden.fingerprint()
    print(f"golden_fingerprint={golden_fp} items={len(items)} k={args.k} unit={args.unit}")
    for mode in RetrievalMode:  # 같은 질문·같은 k 로 세 방식을 비교한다
        report = asyncio.run(svc.retrieval_evaluator.evaluate(items, mode, args.k, EvidenceUnit(args.unit), golden_fp))
        print(
            f"{mode.value:14s} hit={report.hit_at_k_mean} recall={report.recall_at_k_mean} "
            f"scored={report.scored}/{len(items)} n/a={report.not_applicable} unavailable={report.unavailable}"
        )
    return 0


# ── 답변 평가·보안 비교 ───────────────────────────────────────────────
def _prepare_eval() -> tuple[Any, Any, str]:
    """평가 실행 준비: 캐시를 끄고(지표 왜곡 방지) 서비스를 조립한다. (base, services, index_fingerprint)를 돌려준다."""
    os.environ["CACHE_ENABLED"] = "false"  # 적중한 응답은 모델을 부르지 않아 시간·토큰 지표를 왜곡한다
    base = build_base()
    manifest = base.indexer.get_manifest(index_name())
    if manifest is None:
        raise ContractError("인덱스가 없다. 먼저 index 를 실행한다.")
    return base, build_services(base, manifest), manifest.fingerprint


def _settings_snapshot() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in _SETTINGS} | {"CACHE_ENABLED": os.environ.get("CACHE_ENABLED")}


def _write_report(report: dict[str, Any], out: str | None, prefix: str) -> Path:
    path = Path(out) if out else REPORT_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _print_scores(scores: dict[str, Any]) -> None:
    for name, s in scores.items():
        print(
            f"    {name:22s} mean={_fmt(s['mean'])} scored={s['scored']}/{s['total']} "
            f"n/a={s['not_applicable']} unavailable={s['unavailable']}"
        )


def _limit(items: list, limit: int | None) -> list:
    return items[:limit] if limit else items


def cmd_eval_answer(args: argparse.Namespace) -> int:
    base, svc, index_fp = _prepare_eval()
    splits = [Split(v) for v in args.split]
    items = _limit(base.golden.load(splits), args.limit)
    golden_fp = base.golden.fingerprint(splits)
    modes = [RetrievalMode(m) for m in args.mode] if args.mode else list(RetrievalMode)
    run_id = f"eval-{time.strftime('%Y%m%d%H%M%S')}"
    print(f"index={index_name()} index_fingerprint={index_fp} golden_fingerprint={golden_fp} items={len(items)} splits={args.split}")
    print("(캐시 끔. 검색 개수 k 는 서비스 기본값을 쓴다. 같은 설정끼리만 점수를 비교한다)")

    def show(mode: RetrievalMode, rep: dict[str, Any]) -> None:
        sv = rep["service"]
        p50 = sv["latency_ms"]["p50"]
        print(
            f"[{mode.value}] status={sv['status_counts']} error_rate={_fmt(sv['error_rate'])} "
            f"latency_p50={'n/a' if p50 is None else round(p50)}ms({sv['latency_ms']['counted']}/{sv['requests']}) "
            f"input_tokens={sv['input_tokens']['sum']}({sv['input_tokens']['counted']}/{sv['requests']}) cache_hits={sv['cache_hits']}"
        )
        _print_scores(rep["scores"])

    reports = asyncio.run(
        runner.evaluate_answers(
            svc.qa, svc.answer_evaluator, items, modes, run_id=run_id, concurrency=args.concurrency, on_mode=show
        )
    )
    report = {
        "kind": "answer_eval",
        "index_name": index_name(),
        "index_fingerprint": index_fp,
        "golden_fingerprint": golden_fp,
        "splits": args.split,
        "item_count": len(items),
        "settings": _settings_snapshot(),
        "modes": reports,
    }
    print(f"보고서: {_write_report(report, args.out, 'answer')}")
    return 0


def cmd_compare_security(args: argparse.Namespace) -> int:
    from backend.chain import create_answer_chain  # 비교는 서비스를 거치지 않고 체인을 직접 부른다(운영 경로와 분리)

    base, svc, index_fp = _prepare_eval()
    items = _limit(base.golden.load([Split.SECURITY]), args.limit)
    golden_fp = base.golden.fingerprint([Split.SECURITY])
    mode = RetrievalMode(args.mode)
    run_id = f"sec-{time.strftime('%Y%m%d%H%M%S')}"
    print(f"index={index_name()} index_fingerprint={index_fp} golden_fingerprint={golden_fp} security_items={len(items)} mode={mode.value}")
    result = asyncio.run(
        runner.compare_security(
            svc.qa, create_answer_chain(), svc.answer_evaluator, items, mode, run_id=run_id, concurrency=args.concurrency
        )
    )
    sm = result["summary"]
    print(f"공격 문구가 모델 입력에 들어간 문항: {sm['attack_in_model_input']}/{sm['items']} (없는 문항: {sm['attack_not_in_input']})")
    for variant in ("base", "guarded"):
        v = sm[variant]
        print(f"[{variant}] ok={v['ok']}/{v['runs']} failed={v['failed']} skipped={v['skipped']}")
        _print_scores({k: s for k, s in v["scores"].items() if k.startswith("judge.") or k == "faithfulness"})
    report = {
        "kind": "security_compare",
        "index_name": index_name(),
        "index_fingerprint": index_fp,
        "golden_fingerprint": golden_fp,
        "settings": _settings_snapshot(),
        **result,
    }
    print(f"보고서: {_write_report(report, args.out, 'security')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()  # 호스트 실행 시 .env 적용 (이미 설정된 환경변수는 덮어쓰지 않는다)
    apply_impl_default()  # 기본은 실제 구현. APP_IMPL=mock 이면 목업
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_index = sub.add_parser("index", help="문서 색인")
    p_index.add_argument("--rebuild", action="store_true")
    p_index.set_defaults(func=cmd_index)
    p_eval = sub.add_parser("eval", help="검색 평가 (세 방식 비교)")
    p_eval.add_argument("--k", type=int, required=True)
    p_eval.add_argument("--unit", choices=[u.value for u in EvidenceUnit], required=True)  # 기본값 없음
    p_eval.set_defaults(func=cmd_eval)

    splits = [x.value for x in Split if x is not Split.SECURITY]
    p_ans = sub.add_parser("eval-answer", help="답변 평가: RAGAS Faithfulness + Judge 네 항목 (세 방식 비교)")
    p_ans.add_argument("--split", action="append", choices=splits, help="평가할 split(여러 번 가능, 기본 development)")
    p_ans.add_argument("--mode", action="append", choices=[m.value for m in RetrievalMode], help="검색 방식(여러 번 가능, 기본 세 방식 모두)")
    p_ans.add_argument("--limit", type=int, help="앞에서부터 N 문항만(비용 확인용)")
    p_ans.add_argument("--concurrency", type=int, default=2, help="서비스를 동시에 부르는 문항 수(기본 2)")
    p_ans.add_argument("--out", help="보고서 JSON 경로(기본 eval_reports/answer_<시각>.json)")
    p_ans.set_defaults(func=cmd_eval_answer)

    p_sec = sub.add_parser("compare-security", help="보안 문항을 기본·방어 프롬프트로 비교")
    p_sec.add_argument("--mode", choices=[m.value for m in RetrievalMode], default=RetrievalMode.HYBRID.value)
    p_sec.add_argument("--limit", type=int, help="앞에서부터 N 문항만(비용 확인용)")
    p_sec.add_argument("--concurrency", type=int, default=2)
    p_sec.add_argument("--out", help="보고서 JSON 경로(기본 eval_reports/security_<시각>.json)")
    p_sec.set_defaults(func=cmd_compare_security)

    args = parser.parse_args(argv)
    if args.cmd == "eval-answer" and not args.split:
        args.split = [Split.DEVELOPMENT.value]
    try:
        return args.func(args)
    except ContractError as exc:  # 계약 오류는 트레이스백 대신 메시지로 알린다
        print(f"오류({exc.code.value}): {exc.message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
