"""계약 manifest 를 만들고 검사한다. contracts/manifest.json 이 결과물이다.

실행
  python scripts/build_contract_manifest.py            # 예시 검사 → openapi.json·viewer.html 재생성 → manifest 작성
  python scripts/build_contract_manifest.py --check    # 아무것도 쓰지 않고 검사만 (CI)
  python scripts/build_contract_manifest.py --check --against origin/dev [--strict]

manifest 가 보증하는 것
  1. 계약 해시: types·interfaces·api·errors·entrypoints 의 내용 해시. 주석·빈 줄·포맷·따옴표 모양·끝 쉼표 같은
     형식 변화는 무시하고, 코드·독스트링(계약 규칙)이 바뀌면 달라진다.
  2. 계약이 바뀌면 CONTRACT_VERSION 을 올리고 CHANGELOG.md 에 같은 버전 항목을 써야 한다.
  3. 삭제·이름 변경(필드·멤버·엔드포인트 등)은 breaking 이라 더 큰 버전 올림이 필요하다.
  4. openapi.json·viewer.html·예시 JSON 이 계약과 일치한다 (손으로 고치거나 재생성을 빠뜨리면 실패).
  5. 각 모듈·프론트가 선언한 계약 버전이 현재 계약과 맞는다.
     모듈: packages/<모듈>/pyproject.toml 의 [tool.rag-contract] version = "x.y.z"
     프론트: frontend/package.json 의 "ragContract": "x.y.z"
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packages" / "common" / "src"
COMMON = SRC / "common"
sys.path.insert(0, str(SRC))

SOURCES = ["types.py", "interfaces.py", "api.py", "errors.py", "entrypoints.py"]
MANIFEST = ROOT / "contracts" / "manifest.json"
CHANGELOG = ROOT / "contracts" / "CHANGELOG.md"
GENERATED = {"contracts/openapi.json": "export_openapi.py", "contracts/viewer.html": "build_contract_viewer.py"}
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MANIFEST_SCHEMA = 1


# ── 해시 ──────────────────────────────────────────────────────────────
def norm_text(data: bytes) -> str:
    return data.decode("utf-8").replace("\r\n", "\n")


def sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_tokens(src: str) -> list[str]:
    """형식에 무관한 토큰 열. 주석·빈 줄·들여쓰기 폭·따옴표 모양·끝 쉼표를 무시한다.

    한계: (x,) 같은 단일 원소 튜플의 쉼표도 끝 쉼표로 보고 무시한다. 계약 파일에는 쓰지 않는다.
    """
    raw: list[str] = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER):
            continue
        if t.type == tokenize.INDENT:
            raw.append("<INDENT>")
        elif t.type == tokenize.DEDENT:
            raw.append("<DEDENT>")
        elif t.type == tokenize.NEWLINE:
            raw.append("<NEWLINE>")
        elif t.type == tokenize.STRING:
            try:
                v = ast.literal_eval(t.string)
                raw.append("S:" + (v if isinstance(v, str) else repr(v)))
            except Exception:  # noqa: BLE001
                raw.append(t.string)
        else:
            raw.append(t.string)
    return [tok for i, tok in enumerate(raw) if not (tok == "," and i + 1 < len(raw) and raw[i + 1] in (")", "]", "}"))]


def source_hashes() -> dict[str, str]:
    return {name: sha("\x1f".join(normalized_tokens(norm_text((COMMON / name).read_bytes())))) for name in SOURCES}


def contract_hash(sources: dict[str, str]) -> str:
    return sha("\n".join(f"{k}={sources[k]}" for k in sorted(sources)))


def file_hash(path: Path) -> str:
    return sha(norm_text(path.read_bytes()))


# ── 구성 요소 (사람이 manifest diff 를 읽고, 삭제·이름 변경을 감지하는 용도) ──
def components(openapi: dict) -> dict:
    import enum
    import inspect

    from pydantic import BaseModel

    from common import entrypoints, interfaces, types

    typ: dict[str, list[str]] = {}
    for name, obj in vars(types).items():
        if not inspect.isclass(obj) or obj.__module__ != types.__name__ or name == "_Contract":
            continue
        if issubclass(obj, enum.Enum):
            typ[name] = [m.name for m in obj]
        elif issubclass(obj, BaseModel):
            typ[name] = list(obj.model_fields)
    ifc: dict[str, list[str]] = {}
    for name, cls in vars(interfaces).items():
        if inspect.isclass(cls) and cls.__module__ == interfaces.__name__ and getattr(cls, "_is_protocol", False) and name != "Protocol":
            ifc[name] = [m for m in cls.__dict__ if not m.startswith("_")]
    endpoints = sorted(f"{method.upper()} {path}" for path, ops in openapi["paths"].items() for method in ops)
    return {
        "types": typ,
        "interfaces": ifc,
        "endpoints": endpoints,
        "error_codes": [e.value for e in types.ErrorCode],
        "entrypoints": [n for n in vars(entrypoints) if n.startswith("Create")],
    }


def removed_items(base: dict, cur: dict) -> list[str]:
    out: list[str] = []
    for kind in ("types", "interfaces"):
        for name, members in base[kind].items():
            if name not in cur[kind]:
                out.append(f"{kind}:{name}")
                continue
            out += [f"{kind}:{name}.{m}" for m in members if m not in cur[kind][name]]
    for kind in ("endpoints", "error_codes", "entrypoints"):
        out += [f"{kind}:{x}" for x in base[kind] if x not in cur[kind]]
    return out


# ── 버전 ──────────────────────────────────────────────────────────────
def parse_version(v: str) -> tuple[int, int, int]:
    m = SEMVER.match(v)
    if not m:
        raise ValueError(f"버전 형식이 x.y.z 가 아니다: {v!r}")
    return int(m[1]), int(m[2]), int(m[3])


def current_version() -> str:
    from common.version import CONTRACT_VERSION

    return CONTRACT_VERSION


def bump_problems(base_v: str, cur_v: str, changed: bool, removed: list[str]) -> list[str]:
    b, c = parse_version(base_v), parse_version(cur_v)
    problems: list[str] = []
    if changed and c <= b:
        problems.append(f"계약이 바뀌었는데 버전이 올라가지 않았다 (기준 {base_v} → 현재 {cur_v})")
    if removed and c > b:
        breaking_ok = c[0] > b[0] if b[0] >= 1 else (c[0] > b[0] or c[1] > b[1])
        if not breaking_ok:
            need = "major" if b[0] >= 1 else "minor(0.x 에서는 breaking 에 minor 를 쓴다)"
            problems.append(f"삭제·이름 변경이 있으므로 {need} 를 올려야 한다: {', '.join(removed[:6])}{' …' if len(removed) > 6 else ''}")
    return problems


def changelog_has(version: str) -> bool:
    return CHANGELOG.exists() and re.search(rf"^## \[{re.escape(version)}\]", CHANGELOG.read_text(encoding="utf-8"), re.M) is not None


# ── 실행 보조 ─────────────────────────────────────────────────────────
def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, str(ROOT / "scripts" / name), *args], env=env, capture_output=True, text=True)


def examples_files() -> list[Path]:
    return sorted((ROOT / "contracts" / "examples").glob("*.json"))


def artifact_hashes() -> dict[str, str]:
    out = {rel: file_hash(ROOT / rel) for rel in GENERATED}
    out.update({f"contracts/examples/{p.name}": file_hash(p) for p in examples_files()})
    return out


def declarations() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for p in sorted((ROOT / "packages").glob("*/pyproject.toml")):
        if p.parent.name == "common":
            continue
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        out[p.parent.name] = data.get("tool", {}).get("rag-contract", {}).get("version")
    pj = ROOT / "frontend" / "package.json"
    if pj.exists():
        out["frontend"] = json.loads(pj.read_text(encoding="utf-8")).get("ragContract")
    return out


def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def load_manifest() -> dict | None:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else None


# ── build ─────────────────────────────────────────────────────────────
def build() -> int:
    version = current_version()
    try:
        parse_version(version)
    except ValueError as e:
        print("✗", e)
        return 1
    if not changelog_has(version):
        print(f"✗ contracts/CHANGELOG.md 에 '## [{version}]' 항목이 없다. 변경 내용을 먼저 적는다.")
        return 1

    r = run_script("check_examples.py")
    print(r.stdout.strip())
    if r.returncode:
        print("✗ 예시 JSON 이 계약을 통과하지 못해 manifest 를 만들지 않는다")
        return 1
    for rel, script in GENERATED.items():
        r = run_script(script)
        if r.returncode:
            print(f"✗ {script} 실패\n{r.stderr}")
            return 1

    sources = source_hashes()
    h = contract_hash(sources)
    comps = components(json.loads((ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8")))

    old = load_manifest()
    if old:
        changed = old["contract_hash"] != h
        problems = bump_problems(old["contract_version"], version, changed, removed_items(old["components"], comps) if changed else [])
        if problems:
            for p in problems:
                print("✗", p)
            print("  → common/version.py 의 CONTRACT_VERSION 을 올리고 CHANGELOG.md 에 항목을 추가한 뒤 다시 실행한다 (생성 파일은 이미 갱신됐다)")
            return 1
        if not changed and old["contract_version"] != version:
            print(f"! 계약 내용은 같은데 버전만 {old['contract_version']} → {version} 으로 올라갔다")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "contract_version": version,
        "contract_hash": h,
        "sources": sources,
        "components": comps,
        "artifacts": artifact_hashes(),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ manifest 작성: v{version}, {h[:19]}…, 산출물 {len(manifest['artifacts'])}개")
    return 0


# ── check ─────────────────────────────────────────────────────────────
def check(against: str | None, strict: bool) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    ok: list[str] = []

    version = current_version()
    try:
        parse_version(version)
    except ValueError as e:
        errors.append(str(e))
    if not changelog_has(version):
        errors.append(f"contracts/CHANGELOG.md 에 '## [{version}]' 항목이 없다")
    else:
        ok.append(f"CHANGELOG 에 v{version} 항목이 있다")

    m = load_manifest()
    sources = source_hashes()
    h = contract_hash(sources)
    openapi_path = ROOT / "contracts" / "openapi.json"
    if m is None:
        errors.append("contracts/manifest.json 이 없다. python scripts/build_contract_manifest.py 를 실행한다")
    else:
        if m["contract_hash"] != h:
            diff = [k for k in SOURCES if m["sources"].get(k) != sources[k]]
            errors.append(f"계약이 manifest 와 다르다 (바뀐 파일: {', '.join(diff)}). 버전을 올리고 build 를 다시 실행한다")
        else:
            ok.append("계약 해시가 manifest 와 같다")
        if m["contract_version"] != version:
            errors.append(f"manifest 버전({m['contract_version']})과 CONTRACT_VERSION({version})이 다르다")

        # 산출물: 커밋된 파일 == manifest 해시 == 계약에서 다시 생성한 결과
        with tempfile.TemporaryDirectory() as td:
            for rel, script in GENERATED.items():
                tmp = Path(td) / Path(rel).name
                r = run_script(script, "--out", str(tmp))
                path = ROOT / rel
                if r.returncode:
                    errors.append(f"{script} 실행 실패: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}")
                elif not path.exists() or norm_text(tmp.read_bytes()) != norm_text(path.read_bytes()):
                    errors.append(f"{rel} 가 계약과 다르다 (재생성을 빠뜨렸거나 손으로 고쳤다)")
                elif m["artifacts"].get(rel) != file_hash(path):
                    errors.append(f"{rel} 가 manifest 해시와 다르다")
                else:
                    ok.append(f"{rel} 가 계약과 일치한다")
        have = {f"contracts/examples/{p.name}": file_hash(p) for p in examples_files()}
        want = {k: v for k, v in m["artifacts"].items() if k.startswith("contracts/examples/")}
        if have != want:
            names = sorted(set(have) ^ set(want)) or sorted(k for k in have if have[k] != want.get(k))
            errors.append(f"예시 JSON 이 manifest 와 다르다: {', '.join(Path(n).name for n in names)}")
        else:
            ok.append(f"예시 JSON {len(have)}개가 manifest 와 같다")

    r = run_script("check_examples.py")
    if r.returncode:
        errors.append("예시 JSON 이 계약을 통과하지 못한다:\n" + "\n".join("    " + ln for ln in r.stdout.splitlines() if ln.startswith("FAIL")))
    else:
        ok.append("예시 JSON 이 계약을 통과한다")

    # 모듈·프론트의 계약 버전 선언
    cur = parse_version(version) if SEMVER.match(version) else None
    for name, v in declarations().items():
        if v is None:
            warnings.append(f"{name}: 계약 버전 선언이 없다")
        elif not SEMVER.match(v):
            errors.append(f"{name}: 선언한 버전 형식이 잘못됐다 ({v!r})")
        elif cur:
            d = parse_version(v)
            if d[0] != cur[0] or d > cur:
                errors.append(f"{name}: 선언한 계약 v{v} 가 현재 v{version} 과 호환되지 않는다")
            elif d < cur:
                warnings.append(f"{name}: 계약 v{v} 기준이다 (현재 v{version}). 최신 계약 반영이 필요한지 확인한다")
            else:
                ok.append(f"{name}: 계약 v{v} 를 선언했다")

    # 기준 브랜치와 비교: 계약이 바뀌었는데 버전이 안 올랐는지, 삭제·이름 변경이 breaking 으로 올랐는지
    if against:
        base_text = git_show(against, "contracts/manifest.json")
        if base_text is None:
            warnings.append(f"{against} 에 manifest 가 없다 (최초 도입으로 보고 버전 비교를 건너뛴다)")
        elif m is not None and openapi_path.exists() and SEMVER.match(version):
            base = json.loads(base_text)
            comps = components(json.loads(openapi_path.read_text(encoding="utf-8")))
            changed = base["contract_hash"] != h
            problems = bump_problems(base["contract_version"], version, changed, removed_items(base["components"], comps) if changed else [])
            errors += [f"{against} 대비: {p}" for p in problems]
            if not problems:
                ok.append(f"{against} 대비 버전 변화가 올바르다 (v{base['contract_version']} → v{version}{'' if changed else ', 계약 변경 없음'})")
            if not changed and base["contract_version"] != version:
                warnings.append(f"{against} 대비 계약 내용은 같은데 버전만 올라갔다")

    for line in ok:
        print("✓", line)
    for line in warnings:
        print("!", line)
    for line in errors:
        print("✗", line)
    failed = bool(errors) or (strict and bool(warnings))
    print(("\n실패" if failed else "\n통과") + f" (오류 {len(errors)}, 경고 {len(warnings)}{', strict' if strict else ''})")
    return 1 if failed else 0


def main() -> int:
    # 한글 Windows 콘솔(cp949)에서 ✓ 같은 문자를 출력해도 죽지 않게 한다 (표현 못 하는 문자는 ? 로 바꾼다)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="아무것도 쓰지 않고 검사만 한다")
    ap.add_argument("--against", metavar="GIT_REF", help="기준 브랜치와 버전 변화를 비교한다 (예: origin/dev)")
    ap.add_argument("--strict", action="store_true", help="경고(선언 누락·구버전 선언)도 실패로 본다 (릴리스 PR용)")
    args = ap.parse_args()
    return check(args.against, args.strict) if args.check else build()


if __name__ == "__main__":
    sys.exit(main())
