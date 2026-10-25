"""Offline tests of `tool/youtube/auth.py`. The real `.env` is never read: `load_dotenv` is
redirected to a temporary file written by the test."""
from __future__ import annotations

import ast
from pathlib import Path

import dotenv
import pytest

from tool.youtube import auth
from tool.youtube.auth import API_KEY_ENV, YoutubeCredentials, authorize, load_credentials
from tool.youtube.errors import YoutubeConfigError

ROOT = Path(__file__).resolve().parents[1]
SECRET = "AIzaSyTEST-secret-0123456789abcdefghij"
FILE_SECRET = "AIzaSyFILE-secret-0123456789abcdefghij"


@pytest.fixture
def fake_dotenv(monkeypatch, tmp_path):
    """Point `load_dotenv` at a temporary `.env`; record how it is called."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"{API_KEY_ENV}={FILE_SECRET}\n", encoding="utf-8")
    calls: list[dict] = []

    def _load(**kwargs):
        calls.append(kwargs)
        return dotenv.load_dotenv(dotenv_path=env_file, **kwargs)

    monkeypatch.setattr(auth, "load_dotenv", _load)
    # Restored at teardown, also when the fake `.env` sets it.
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    return calls


def test_credentials_come_from_the_given_environment() -> None:
    creds = load_credentials({API_KEY_ENV: f"  {SECRET}\n"})

    assert creds == YoutubeCredentials(secret=SECRET)


@pytest.mark.parametrize("environ", [{}, {API_KEY_ENV: ""}, {API_KEY_ENV: "   "}])
def test_missing_key_is_a_config_error_naming_only_the_variable(environ) -> None:
    with pytest.raises(YoutubeConfigError, match=API_KEY_ENV) as exc:
        load_credentials(environ)

    assert exc.value.code == "not_configured"


def test_without_environ_the_key_is_loaded_from_dotenv(fake_dotenv) -> None:
    creds = load_credentials()

    assert creds.secret == FILE_SECRET
    assert fake_dotenv == [{"override": False}]


def test_a_variable_already_in_the_environment_wins_over_dotenv(fake_dotenv, monkeypatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, SECRET)

    assert load_credentials().secret == SECRET


def test_missing_key_in_environment_and_dotenv(monkeypatch, tmp_path) -> None:
    empty = tmp_path / ".env"
    empty.write_text("OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr(auth, "load_dotenv", lambda **kwargs: dotenv.load_dotenv(dotenv_path=empty, **kwargs))
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv("OTHER", raising=False)

    with pytest.raises(YoutubeConfigError):
        load_credentials()


def test_repr_and_str_never_show_the_key() -> None:
    creds = load_credentials({API_KEY_ENV: SECRET})

    for text in (repr(creds), str(creds), f"{creds}", repr([creds]), repr({"c": creds})):
        assert SECRET not in text and "***" in text


def test_errors_never_contain_a_key() -> None:
    with pytest.raises(YoutubeConfigError) as exc:
        load_credentials({API_KEY_ENV: " ", "OTHER_KEY": SECRET})

    assert SECRET not in str(exc.value) and SECRET not in repr(exc.value)


def test_authorize_adds_the_key_without_changing_the_input() -> None:
    creds = load_credentials({API_KEY_ENV: SECRET})
    params = {"part": "snippet", "q": "Dune"}

    query, headers = authorize(creds, params)

    assert query == {"part": "snippet", "q": "Dune", "key": SECRET}
    assert params == {"part": "snippet", "q": "Dune"}
    assert headers == {"Accept": "application/json"}


def test_only_auth_reads_the_environment_in_the_youtube_package() -> None:
    readers = set()
    for path in sorted((ROOT / "tool" / "youtube").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                readers.add(path.relative_to(ROOT).as_posix())
            if isinstance(node, ast.Constant) and node.value == API_KEY_ENV:
                readers.add(path.relative_to(ROOT).as_posix())
    assert readers == {"tool/youtube/auth.py"}


def test_youtube_package_never_imports_tmdb() -> None:
    for path in sorted((ROOT / "tool" / "youtube").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert not node.module.startswith("tool"), (path, node.module)
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("tool") for alias in node.names), path
