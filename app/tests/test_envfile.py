import os

from app.envfile import load_env_file, parse_env


def test_parse_handles_comments_quotes_and_inline_comments():
    text = """
# 주석
INDEX_NAME=rag-dev-me      # 개인 구분
QUOTED="a b # not comment"
SINGLE='x=y'
export EXPORTED=1
EMPTY=
no_equals_line
1BAD=skip
WITH_SPACE = spaced
"""
    got = parse_env(text)
    assert got == {
        "INDEX_NAME": "rag-dev-me",
        "QUOTED": "a b # not comment",
        "SINGLE": "x=y",
        "EXPORTED": "1",
        "EMPTY": "",
        "WITH_SPACE": "spaced",
    }


def test_existing_environment_wins_and_empty_values_are_not_set(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("A_KEY=from-file\nB_KEY=from-file\nEMPTY_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("A_KEY", "from-shell")
    monkeypatch.delenv("B_KEY", raising=False)
    monkeypatch.delenv("EMPTY_KEY", raising=False)
    applied = load_env_file(f)
    assert applied == ["B_KEY"]
    assert os.environ["A_KEY"] == "from-shell" and os.environ["B_KEY"] == "from-file"
    assert "EMPTY_KEY" not in os.environ
    monkeypatch.delenv("B_KEY")  # load_env_file 이 직접 넣은 값을 테스트 뒤에 남기지 않는다


def test_missing_file_is_a_noop(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == []


def test_env_file_variable_selects_path(tmp_path, monkeypatch):
    f = tmp_path / "custom.env"
    f.write_text("CUSTOM_PATH_KEY=1\n", encoding="utf-8-sig")  # BOM 도 읽는다
    monkeypatch.setenv("ENV_FILE", str(f))
    monkeypatch.delenv("CUSTOM_PATH_KEY", raising=False)
    assert load_env_file() == ["CUSTOM_PATH_KEY"]
    monkeypatch.delenv("CUSTOM_PATH_KEY")
