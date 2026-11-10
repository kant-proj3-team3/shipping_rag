"""PR 제목(Conventional Commits)·브랜치 규칙·본문 필수 항목을 검사한다 (pr-lint workflow).

입력은 환경변수다: PR_TITLE, PR_BODY, PR_HEAD(작성 브랜치), PR_BASE(대상 브랜치).
표준 라이브러리만 쓴다.

검사
  1. 제목: `type(scope): 설명` 또는 `type: 설명` (Conventional Commits). scope 는 선택.
  2. 브랜치: feat/*·fix/* → dev, dev → main 만 허용한다.
  3. 본문: .github/pull_request_template.md 의 필수 항목을 채웠는가
     (변경 요약, 대상 모듈 1개 이상 체크, 계약 영향, 실행한 검사).
"""

from __future__ import annotations

import os
import re
import sys

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")
TITLE_RE = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9][a-z0-9_./-]*\))?!?: \S.*$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# 템플릿 항목 제목 → 본문에 내용이 있어야 하는 항목
REQUIRED_TEXT = ("변경 요약", "계약 영향")


def check_title(title: str) -> list[str]:
    if TITLE_RE.match(title.strip()):
        return []
    return [
        f"PR 제목이 Conventional Commits 형식이 아니다: {title!r}\n"
        f"  예: feat(retrieval): 하이브리드 검색 추가  (type: {', '.join(TYPES)})"
    ]


# dev 로 PR 을 올릴 수 있는 작업 브랜치의 접두어. 제목 type(feat·fix)과 짝을 맞춘다.
WORK_BRANCH_PREFIXES = ("feat/", "fix/")


def check_branches(head: str, base: str) -> list[str]:
    if base == "dev" and any(head.startswith(p) and len(head) > len(p) for p in WORK_BRANCH_PREFIXES):
        return []
    if base == "main" and head == "dev":
        return []
    return [f"허용되지 않는 브랜치 조합이다: {head} → {base} (허용: feat/*·fix/* → dev, dev → main)"]


def sections(body: str) -> dict[str, str]:
    """`## 제목` 단위로 나누고 HTML 주석을 제거한다."""
    out: dict[str, str] = {}
    current: str | None = None
    for line in HTML_COMMENT.sub("", body).splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            out[current] = ""
        elif current is not None:
            out[current] += line + "\n"
    return out


def check_body(body: str) -> list[str]:
    errors: list[str] = []
    sec = sections(body)
    for name in REQUIRED_TEXT:
        if not sec.get(name, "").strip():
            errors.append(f"PR 본문의 '{name}' 항목이 비어 있거나 없다 (없으면 '없음'이라고 쓴다)")
    modules = sec.get("대상 모듈", "")
    if not re.search(r"^\s*-\s*\[[xX]\]", modules, re.M):
        errors.append("PR 본문의 '대상 모듈'에서 하나 이상 체크해야 한다")
    if "실행한 검사" not in sec:
        errors.append("PR 본문에 '실행한 검사' 항목이 없다")
    else:
        checks = sec["실행한 검사"]
        unchecked = re.compile(r"^\s*-\s*\[ \]")
        has_check = re.search(r"^\s*-\s*\[[xX]\]", checks, re.M) is not None
        has_note = any(ln.strip() and not unchecked.match(ln) for ln in checks.splitlines())
        if not (has_check or has_note):
            errors.append("PR 본문의 '실행한 검사'에서 실행한 검사를 체크하거나 '해당 없음'과 이유를 적어야 한다")
    return errors


def main() -> int:
    title = os.environ.get("PR_TITLE", "")
    body = os.environ.get("PR_BODY", "") or ""
    head = os.environ.get("PR_HEAD", "")
    base = os.environ.get("PR_BASE", "")
    errors = check_title(title) + check_branches(head, base) + check_body(body)
    if errors:
        print("FAIL: PR 검사")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: PR 제목·브랜치·본문")
    return 0


if __name__ == "__main__":
    sys.exit(main())
