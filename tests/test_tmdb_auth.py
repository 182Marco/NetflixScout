from __future__ import annotations

import urllib.error

import pytest
from tmdb_support import BASE, MOVIE_ID, SECRET, TOKEN, calls_shown, make_tool, movie_payload, run, tmdb_meta

from presenters import OutputChannel, present
from tool.tmdb.auth import AuthMode, authorize, detect_mode, load_credentials, validate_base_url
from tool.tmdb.calls import display_url
from tool.tmdb.errors import TmdbConfigError
from presenters.web.api import serialize_tmdb_calls_step
from turn import TraceStep, TurnResult


def test_credentials_come_from_the_given_environment() -> None:
    creds = load_credentials({"VUE_APP_TMDB_API_KEY": f" {SECRET} ", "VUE_APP_TMDB_BASE_URL": "https://api.themoviedb.org/3/"})

    assert (creds.secret, creds.base_url, creds.mode) == (SECRET, BASE, AuthMode.query)
    assert load_credentials({"VUE_APP_TMDB_API_KEY": TOKEN}).mode is AuthMode.bearer
    assert SECRET not in repr(creds) and SECRET not in str(creds)


def test_missing_key_is_a_config_error() -> None:
    with pytest.raises(TmdbConfigError, match="VUE_APP_TMDB_API_KEY"):
        load_credentials({})


@pytest.mark.parametrize(
    "url",
    [
        "http://api.themoviedb.org/3",
        "https://evil.example.com/3",
        "https://api.themoviedb.org.evil.com/3",
        "https://user:pw@api.themoviedb.org/3",
        "https://api.themoviedb.org:8443/3",
        "https://api.themoviedb.org/4",
        "https://api.themoviedb.org/3?x=1",
    ],
)
def test_base_url_outside_the_allowlist_is_rejected(url) -> None:
    with pytest.raises(TmdbConfigError):
        validate_base_url(url)


def test_authorize_puts_the_credential_where_the_mode_requires() -> None:
    query, headers = authorize(load_credentials({"VUE_APP_TMDB_API_KEY": SECRET}), {"language": "it-IT"})
    assert query == {"language": "it-IT", "api_key": SECRET} and "Authorization" not in headers

    query, headers = authorize(load_credentials({"VUE_APP_TMDB_API_KEY": TOKEN}), {"language": "it-IT"})
    assert query == {"language": "it-IT"} and headers["Authorization"] == f"Bearer {TOKEN}"
    assert detect_mode("not-a-jwt") is AuthMode.query


def test_display_url_masks_the_key_and_hides_parameters() -> None:
    query_creds = load_credentials({"VUE_APP_TMDB_API_KEY": SECRET})
    bearer_creds = load_credentials({"VUE_APP_TMDB_API_KEY": TOKEN})

    assert display_url(query_creds, f"/movie/{MOVIE_ID}/credits") == f"{BASE}/movie/{MOVIE_ID}/credits?api_key=***"
    assert display_url(bearer_creds, f"/movie/{MOVIE_ID}") == f"{BASE}/movie/{MOVIE_ID}"


@pytest.mark.parametrize("mode", [AuthMode.query, AuthMode.bearer])
def test_secret_never_leaves_the_http_layer(mode, capsys) -> None:
    def explode(params):
        raise urllib.error.URLError(f"failed {BASE}/movie/1?api_key={SECRET} {TOKEN}")

    tool, transport = make_tool(
        {f"/movie/{MOVIE_ID}": movie_payload(), "/movie/2": explode, "/movie/3": (500, {}, {"x": SECRET})},
        mode=mode,
    )
    result = run(
        tool,
        {"operation": "movie_details", "tmdb_id": MOVIE_ID, "facets": ["credits"]},
        {"operation": "movie_details", "tmdb_id": 2},
        {"operation": "movie_details", "tmdb_id": 3},
    )
    step = TraceStep(**result["trace"][0])
    present(TurnResult(query="q", language="it", blocked=False, answer="ok", steps=[step]), OutputChannel.terminal)
    rendered = repr(result) + capsys.readouterr().out + repr(serialize_tmdb_calls_step(step, "it")) + repr(tool.cache._items)

    secret = TOKEN if mode is AuthMode.bearer else SECRET
    assert secret not in rendered
    assert [o["error"] for o in tmdb_meta(result)["requests"][1:]] == ["network_error", "http_error"]
    # The real request did carry the credential.
    sent_url, sent_headers = transport.calls[0][3], transport.calls[0][2]
    assert secret in sent_url or secret in sent_headers.get("Authorization", "")
    expected = f"{BASE}/movie/{MOVIE_ID}" + ("?api_key=***" if mode is AuthMode.query else "")
    assert calls_shown(result)[0] == expected
