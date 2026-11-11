"""app 조립 통합 테스트: 목업 모듈 3개를 진입점으로 연결해 끝까지 흘려본다."""

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.api import create_app


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_INDEX_DIR", str(tmp_path / "idx"))
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("INDEX_NAME", "test-index")
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "no-such.env"))  # 개발자의 실제 .env 가 테스트에 끼지 않게 한다
    monkeypatch.setenv("APP_IMPL", "mock")  # 이 파일은 목업 조립을 확인한다(실제 구현 조립은 test_real_assembly.py)
    for var in ("CHUNKING_IMPL", "RETRIEVAL_IMPL", "BACKEND_IMPL"):
        monkeypatch.setenv(var, "mock")  # apply_impl_default 가 환경변수를 새로 만들어도 테스트가 끝나면 지워지도록 한 번 설정해 둔다
        monkeypatch.delenv(var)
    monkeypatch.delenv("MOCK_INDEX_READY", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)


def test_api_reports_not_ready_before_index_is_built():
    c = TestClient(create_app())
    h = c.get("/health").json()
    assert h["index_ready"] is False and h["supported_modes"] == []
    assert c.post("/query", json={"question": "장비 질문입니다"}).status_code == 404  # 라우터 없음


def test_cli_eval_without_index_fails(capsys):
    assert cli.main(["eval", "--k", "5", "--unit", "page"]) == 1
    assert "인덱스가 없다" in capsys.readouterr().out


def test_index_then_api_end_to_end(capsys):
    assert cli.main(["index"]) == 0
    c = TestClient(create_app())  # 다른 앱 인스턴스: 저장된 인덱스를 본다
    h = c.get("/health").json()
    assert h["index_ready"] is True and h["index_name"] == "test-index" and h["embedder_id"]
    r = c.post("/query", json={"question": "장비 A의 화면 꺼짐 시간", "retrieval_mode": "naive", "session_id": "app-session-01"})
    assert r.status_code == 200
    assert r.json()["status"] == "answered" and r.json()["citations"]
    assert c.get("/session/app-session-01").json()["turn_count"] == 1


def test_cli_index_refuses_existing_without_rebuild(capsys):
    assert cli.main(["index"]) == 0
    assert cli.main(["index"]) == 1
    assert "ingest_failed" in capsys.readouterr().out
    assert cli.main(["index", "--rebuild"]) == 0


def test_live_openapi_matches_contract(monkeypatch):
    import json
    from pathlib import Path

    monkeypatch.setenv("MOCK_INDEX_READY", "1")
    live = TestClient(create_app()).app.openapi()
    contract = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    assert live["paths"] == contract["paths"]
    assert live["components"] == contract["components"]


def test_cli_eval_compares_three_modes(capsys):
    assert cli.main(["index"]) == 0
    capsys.readouterr()
    assert cli.main(["eval", "--k", "5", "--unit", "page"]) == 0
    out = capsys.readouterr().out
    for mode in ("naive", "hybrid", "hybrid_rerank"):
        assert mode in out
    assert "golden_fingerprint=" in out


def test_cors_is_off_by_default_and_opt_in_by_env(monkeypatch):
    monkeypatch.setenv("MOCK_INDEX_READY", "1")
    origin = {"Origin": "http://localhost:5173"}
    off = TestClient(create_app()).get("/health", headers=origin)
    assert "access-control-allow-origin" not in off.headers

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    c = TestClient(create_app())
    on = c.get("/health", headers=origin)
    assert on.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers  # 적지 않은 출처는 허용하지 않는다
    pre = c.options("/query", headers={**origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 200 and "POST" in pre.headers["access-control-allow-methods"]


def test_cors_also_applies_when_index_is_not_ready(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:5173")
    r = TestClient(create_app()).get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.json()["index_ready"] is False
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_dotenv_is_applied_for_host_runs(tmp_path, monkeypatch):
    env = tmp_path / "host.env"
    env.write_text("INDEX_NAME=from-dotenv\nMOCK_INDEX_READY=1\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env))
    # 셸에 값이 없으면 .env 의 값이 쓰인다. 로더가 os.environ 에 직접 넣은 값이 테스트 밖으로 새지 않게
    # setenv 뒤 delenv 로 monkeypatch 가 원래 상태(없음)를 복원하도록 기록해 둔다.
    for key in ("INDEX_NAME", "MOCK_INDEX_READY"):
        monkeypatch.setenv(key, "placeholder")
        monkeypatch.delenv(key)
    health = TestClient(create_app()).get("/health").json()
    assert health["index_ready"] is True and health["index_name"] == "from-dotenv"
