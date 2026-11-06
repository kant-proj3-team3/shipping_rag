"""모듈 경계 검사 (import-lint workflow). 표준 라이브러리만 쓴다.

규칙
  1. 모듈(packages/<이름>, common 제외)은 common 과 외부 라이브러리만 import 한다.
     다른 모듈, app 은 import 하지 않는다. 모듈 이름은 packages/ 아래 폴더에서 자동으로 찾는다.
  2. common 은 표준 라이브러리와 pydantic 만 쓴다 (다른 모듈·app·그 밖의 외부 라이브러리 금지).

실행: python scripts/import_lint.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
COMMON = "common"
APP = "app"
COMMON_ALLOWED_EXTERNAL = {"pydantic", "pydantic_core", "annotated_types"}  # pydantic 이 끌고 오는 것까지


def module_names() -> set[str]:
    """packages/ 아래의 폴더 이름 중 common 을 뺀 것이 모듈이다."""
    return {p.name for p in PACKAGES.iterdir() if p.is_dir() and p.name != COMMON and not p.name.startswith(".")}


def imported_roots(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def check_module(name: str, modules: set[str]) -> list[str]:
    forbidden = (modules - {name}) | {APP}
    problems: list[str] = []
    for py in sorted((PACKAGES / name).rglob("*.py")):
        if ".venv" in py.parts:
            continue
        for line, root in imported_roots(py):
            if root in forbidden:
                problems.append(f"{py.relative_to(ROOT)}:{line}: '{name}' 모듈이 '{root}' 를 import 한다")
    return problems


def check_common(modules: set[str]) -> list[str]:
    problems: list[str] = []
    stdlib = set(sys.stdlib_module_names)
    for py in sorted((PACKAGES / COMMON).rglob("*.py")):
        if ".venv" in py.parts:
            continue
        for line, root in imported_roots(py):
            if root == COMMON or root in stdlib or root in COMMON_ALLOWED_EXTERNAL:
                continue
            kind = "모듈/app" if root in modules | {APP} else "허용되지 않은 외부 라이브러리"
            problems.append(f"{py.relative_to(ROOT)}:{line}: common 이 {kind} '{root}' 를 import 한다 (표준 라이브러리와 pydantic 만 허용)")
    return problems


def main() -> int:
    modules = module_names()
    problems: list[str] = []
    for name in sorted(modules):
        problems += check_module(name, modules)
    problems += check_common(modules)
    if problems:
        print("FAIL: 모듈 경계 위반")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print(f"OK: 모듈 경계 위반 없음 (모듈: {', '.join(sorted(modules))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
