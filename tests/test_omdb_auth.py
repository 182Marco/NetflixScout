from __future__ import annotations

import pytest

from omdb_support import SECRET, credentials
from tool.omdb import auth
from tool.omdb.errors import OmdbConfigError


def test_the_key_is_read_from_the_given_environment() -> None:
    assert auth.load_credentials({"OMDB_API_KEY": f"  {SECRET} "}).secret == SECRET


@pytest.mark.parametrize("environ", [{}, {"OMDB_API_KEY": ""}, {"OMDB_API_KEY": "   "}])
def test_a_missing_key_is_a_config_error_that_does_not_name_a_value(environ) -> None:
    with pytest.raises(OmdbConfigError) as caught:
        auth.load_credentials(environ)

    assert caught.value.code == "not_configured" and "OMDB_API_KEY" in str(caught.value)


def test_the_key_is_never_in_repr_or_str() -> None:
    creds = credentials()

    assert SECRET not in repr(creds) and SECRET not in str(creds) and SECRET not in f"{creds!r}{creds}"


def test_authorize_adds_the_key_without_changing_the_input() -> None:
    params = {"i": "tt1000001"}
    query, headers = auth.authorize(credentials(), params)

    assert query == {"i": "tt1000001", "apikey": SECRET} and params == {"i": "tt1000001"}
    assert SECRET not in str(headers)


def test_only_auth_reads_the_environment_variable() -> None:
    from pathlib import Path

    root = Path(auth.__file__).parent
    readers = [p.name for p in root.glob("*.py") if "OMDB_API_KEY" in p.read_text(encoding="utf-8") or "os.environ" in p.read_text(encoding="utf-8")]

    assert readers == ["auth.py"]
