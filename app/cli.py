"""배치 CLI. `python -m app.cli index` / `python -m app.cli eval --k 5 --unit page`.

뼈대 단계의 최소 러너다. 평가 러너를 app/ 에 둘지는 팀 결정 대기 중이다 (CONTRACTS.md 5장 3번).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from common.errors import ContractError
from common.types import EvidenceUnit, IndexBuildRequest, IndexProgress, RetrievalMode

from .envfile import load_env_file
from .wiring import build_base, build_services, index_name


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


def main(argv: list[str] | None = None) -> int:
    load_env_file()  # 호스트 실행 시 .env 적용 (이미 설정된 환경변수는 덮어쓰지 않는다)
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_index = sub.add_parser("index", help="문서 색인")
    p_index.add_argument("--rebuild", action="store_true")
    p_index.set_defaults(func=cmd_index)
    p_eval = sub.add_parser("eval", help="검색 평가 (세 방식 비교)")
    p_eval.add_argument("--k", type=int, required=True)
    p_eval.add_argument("--unit", choices=[u.value for u in EvidenceUnit], required=True)  # 기본값 없음
    p_eval.set_defaults(func=cmd_eval)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ContractError as exc:  # 계약 오류는 트레이스백 대신 메시지로 알린다
        print(f"오류({exc.code.value}): {exc.message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
