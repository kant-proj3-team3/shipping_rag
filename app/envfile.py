""".env 읽기. 호스트에서 `uv run`으로 직접 실행할 때 `.env`가 적용되게 한다.

- compose 의 api·cli 는 `env_file`로 이미 환경변수를 받으므로 이 로더가 할 일이 없다(컨테이너에는 `.env`가 없다).
- 이미 설정된 환경변수는 덮어쓰지 않는다 (셸·compose 에서 준 값이 우선이다).
- 값이 빈 항목(`KEY=`)은 설정하지 않는다 (`.env.example`의 빈 키가 '설정됨'으로 보이지 않게).
- 위치: 환경변수 `ENV_FILE`이 있으면 그 경로, 없으면 저장소 루트의 `.env`. 파일이 없으면 아무것도 하지 않는다.
- 모듈(`packages/*`)은 이 로더를 쓰지 않는다. 모듈은 환경변수만 읽고, `.env`를 아는 곳은 `app/`뿐이다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".env"
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env(text: str) -> dict[str, str]:
    """`KEY=VALUE` 줄을 읽는다. `#` 주석, `export ` 접두, 따옴표 값, 값 뒤의 ` # 주석`을 처리한다."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not _KEY.match(key):
            continue
        if value[:1] in {'"', "'"}:
            end = value.find(value[0], 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            comment = re.search(r"\s#", value)
            if comment:
                value = value[: comment.start()]
            value = value.strip()
        out[key] = value
    return out


def load_env_file(path: Path | str | None = None) -> list[str]:
    """`.env`를 읽어 아직 없는 환경변수만 설정하고, 새로 설정한 키 목록을 돌려준다."""
    target = Path(path or os.environ.get("ENV_FILE") or DEFAULT_PATH)
    if not target.is_file():
        return []
    applied: list[str] = []
    for key, value in parse_env(target.read_text(encoding="utf-8-sig")).items():
        if value and key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied
