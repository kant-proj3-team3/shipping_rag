"""contracts/examples/*.json 이 계약 타입을 통과하는지 검사한다. (프론트 목업 데이터의 신뢰 근거)"""

import json
import sys
from pathlib import Path

from common.types import ApiError, GoldenItem, HealthResponse, QueryRequest, QueryResponse, SessionInfo

EX = Path(__file__).resolve().parents[1] / "contracts" / "examples"
MODELS = {
    "health_ok": HealthResponse,
    "query_request": QueryRequest,
    "session_info": SessionInfo,
    "session_not_found": ApiError,
    "golden_item": GoldenItem,
}
failed = False
for p in sorted(EX.glob("*.json")):
    model = MODELS.get(p.stem, QueryResponse)
    try:
        model.model_validate(json.loads(p.read_text(encoding="utf-8")))
        print(f"OK   {p.name}")
    except Exception as e:  # noqa: BLE001
        failed = True
        print(f"FAIL {p.name}: {e}")
sys.exit(1 if failed else 0)
