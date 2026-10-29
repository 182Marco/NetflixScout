"""The HTTP calls the user sees (terminal and web) are the requests the tools really sent.

For every tool that calls an API: each request that reaches the transport has exactly one record
`{"method", "url"}` in the step, in the same order, with the same URL (path and every query parameter)
where only the value of the credential is `***`; the web payload and the terminal show all of them; and
no output holds the key, whatever shape the URL or the failure has.
"""
from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

import omdb_support
import tmdb_support
import wikipedia_support
import youtube_support
from presenters import OutputChannel, present
from presenters.calls_view import call_views
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.payload import STEP_SERIALIZERS
from turn import (
    MASK,
    STEP_OMDB_CALLS,
    STEP_TMDB_CALLS,
    STEP_TVMAZE_CALLS,
    STEP_WIKIDATA_CALLS,
    STEP_WIKIPEDIA_CALLS,
    STEP_YOUTUBE_CALLS,
    TraceStep,
    TurnResult,
    http_call,
    mask_url,
)


# --- mask_url: only credentials, whatever their name or place ---------------------------------------------


@pytest.mark.parametrize(
    ("url", "secrets", "expected"),
    [
        ("https://www.omdbapi.com/?apikey=ABC123&i=tt123", ["ABC123"], "https://www.omdbapi.com/?apikey=***&i=tt123"),
        ("https://www.omdbapi.com/?apikey=ABC123&i=tt123", [], "https://www.omdbapi.com/?apikey=***&i=tt123"),
        ("https://x.test/3/movie/1?language=it-IT&api_key=k1&append_to_response=a%2Cb", [], "https://x.test/3/movie/1?language=it-IT&api_key=***&append_to_response=a%2Cb"),
        ("https://x.test/v3/search?q=%22Dune%22&key=AIzaXYZ", [], "https://x.test/v3/search?q=%22Dune%22&key=***"),
        ("https://x.test/?API_KEY=UP&Token=T", [], "https://x.test/?API_KEY=***&Token=***"),
        ("https://x.test/?access_token=a&client_secret=b&password=c", [], "https://x.test/?access_token=***&client_secret=***&password=***"),
        # a secret under a name nobody knows, in the query, the path, percent-encoded, the fragment
        ("https://x.test/?foo=S3cr%C3%A8t&bar=1", ["S3crèt"], "https://x.test/?foo=***&bar=1"),
        ("https://x.test/S3cret/path?x=1", ["S3cret"], "https://x.test/***/path?x=1"),
        ("https://x.test/p?x=1#S3cret", ["S3cret"], "https://x.test/p?x=1#***"),
        ("https://x.test/?a=p+q%2Br", ["p q+r"], "https://x.test/?a=***"),
        # user:password in the authority
        ("https://user:hunter2@x.test/p?x=1", [], "https://***@x.test/p?x=1"),
        # not credentials: untouched, even when the name or value looks alike
        ("https://x.test/?monkey=1&keyword=key&q=api_key&i=tt1", [], "https://x.test/?monkey=1&keyword=key&q=api_key&i=tt1"),
        ("https://x.test/?apikey=A&apikey=B&n=1", [], "https://x.test/?apikey=***&apikey=***&n=1"),
    ],
)
def test_mask_url_hides_only_credentials(url, secrets, expected) -> None:
    masked = mask_url(url, secrets)

    assert masked == expected and mask_url(masked, secrets) == masked  # idempotent


def test_http_call_records_method_and_the_masked_full_url() -> None:
    assert http_call("get", "https://h.test/p?apikey=Z&i=tt1", ["Z"]) == {"method": "GET", "url": "https://h.test/p?apikey=***&i=tt1"}
    assert http_call("not a method!", "https://h.test/")["method"] == "?"


# --- the presenters mask once more, so a tool that forgot cannot leak -----------------------------------------


@pytest.mark.parametrize("kind", [STEP_TMDB_CALLS, STEP_YOUTUBE_CALLS, STEP_WIKIPEDIA_CALLS, STEP_OMDB_CALLS, STEP_TVMAZE_CALLS, STEP_WIKIDATA_CALLS])
def test_a_step_with_an_unmasked_url_still_shows_no_key(kind, capsys) -> None:
    leaky = [
        {"method": "GET", "url": "https://h.test/p?x=1&apikey=LEAK1&key=LEAK2&api_key=LEAK3"},
        "https://u:LEAK4@h.test/p?token=LEAK5",
    ]
    step = TraceStep(kind=kind, title="t", data={"calls": leaky})

    present(TurnResult(query="q", language="it", blocked=False, answer="ok", steps=[step]), OutputChannel.terminal)
    rendered = capsys.readouterr().out + json.dumps(STEP_SERIALIZERS[kind](step, "it"))

    assert "LEAK" not in rendered and "x=1&apikey=***&key=***&api_key=***" in rendered


def test_only_https_urls_are_shown_and_garbage_is_ignored() -> None:
    views = call_views([{"method": "GET", "url": "http://h.test/"}, 5, None, {"url": 3}, {"method": "GET", "url": "https://h.test/\x1b[31m"}])

    assert [view.url for view in views] == ["https://h.test/[31m"] and call_views("x") == []


# --- every tool: what the transport got is what the user sees ---------------------------------------------


def _tmdb() -> tuple[dict[str, Any], list[str], str]:
    routes = {f"/movie/{tmdb_support.MOVIE_ID}": tmdb_support.movie_payload(), "/movie/501": tmdb_support.movie_payload()}
    tool, transport = tmdb_support.make_tool(routes)
    result = tmdb_support.run(
        tool,
        {"operation": "movie_details", "tmdb_id": tmdb_support.MOVIE_ID},
        {"operation": "movie_details", "tmdb_id": 501},
        language="it",
    )
    return result, [call[3] for call in transport.calls], tmdb_support.SECRET


def _youtube() -> tuple[dict[str, Any], list[str], str]:
    tool, transport = youtube_support.make_tool({"/search": {"items": []}})
    result = tool.run(query="q", params={"title": "Dune", "kinds": ["making_of", "behind_the_scenes"]})
    return result, [call[3] for call in transport.calls], youtube_support.SECRET


def _wikipedia() -> tuple[dict[str, Any], list[str], str]:
    lead = wikipedia_support.lookup_answer(wikipedia_support.page("Park Chan-wook", "Park Chan-wook è un regista."))
    tool, transport = wikipedia_support.make_tool(wikipedia_support.by_mode(lookup=lead, article=wikipedia_support.article_answer()))
    result = tool.run(query="q", params={"topic": "Park Chan-wook", "depth": "full", "keywords": ["Oldboy"]})
    return result, [call[3] for call in transport.calls], ""


def _omdb() -> tuple[dict[str, Any], list[str], str]:
    hit = omdb_support.search_hit("tt1000001", "Sample Movie", "2016")
    tool, transport = omdb_support.make_tool(
        omdb_support.by_endpoint(search=omdb_support.search_answer(hit), by_id={"tt1000001": omdb_support.record()})
    )
    result = tool.run(query="q", params={"title": "Sample Movie"})
    return result, [call[2] for call in transport.calls], omdb_support.SECRET


def _tvmaze() -> tuple[dict[str, Any], list[str], str]:
    import tvmaze_support

    tool, transport = tvmaze_support.make_tool(tvmaze_support.routes_for())
    result = tool.run(query="q", params={"title": "Sample Show", "facets": ["cast", "next", "seasons"]})
    # No key: nothing to mask, the URL shown is the URL sent.
    return result, [call[3] for call in transport.calls], ""


def _wikidata() -> tuple[dict[str, Any], list[str], str]:
    import wikidata_support

    tool, transport = wikidata_support.make_tool(wikidata_support.routes_for())
    result = tool.run(query="q", params={"operation": "relations", "title": "Sample Film", "year": 1982})
    # No key: nothing to mask, the URL shown is the URL sent (the SPARQL text included).
    return result, [call[3] for call in transport.calls], ""


@pytest.mark.parametrize(
    ("build", "kind", "expected_calls"),
    [
        (_tmdb, STEP_TMDB_CALLS, 2),
        (_youtube, STEP_YOUTUBE_CALLS, 2),
        (_wikipedia, STEP_WIKIPEDIA_CALLS, 2),
        (_omdb, STEP_OMDB_CALLS, 2),
        (_tvmaze, STEP_TVMAZE_CALLS, 3),
        (_wikidata, STEP_WIKIDATA_CALLS, 3),
    ],
)
def test_every_request_sent_is_shown_with_its_full_url_and_only_the_key_masked(build, kind, expected_calls, capsys) -> None:
    result, sent, secret = build()
    (step_dict,) = result["trace"]
    step = TraceStep(**step_dict)

    recorded = step.data["calls"]
    assert step.kind == kind and len(sent) >= expected_calls and len(recorded) == len(sent)
    for call, url in zip(recorded, sent, strict=True):
        assert call == {"method": "GET", "url": mask_url(url, [secret])}
        assert not secret or secret not in call["url"]
    if secret:
        assert all(secret in url for url in sent) and all(MASK in call["url"] for call in recorded)

    web = STEP_SERIALIZERS[kind](step, "it")
    assert [(c["method"], c["url"]) for c in web["calls"]] == [(c["method"], c["url"]) for c in recorded]

    STEP_RENDERERS[kind](step, "it")
    out = capsys.readouterr().out
    assert all(f"GET {call['url']}" in out for call in recorded)
    assert not secret or secret not in out + json.dumps(web) + json.dumps(result, default=str)


def test_tmdb_bearer_tokens_are_never_in_the_url_nor_the_step() -> None:
    from tool.tmdb.auth import AuthMode

    tool, transport = tmdb_support.make_tool({f"/movie/{tmdb_support.MOVIE_ID}": tmdb_support.movie_payload()}, mode=AuthMode.bearer)
    result = tmdb_support.run(tool, {"operation": "movie_details", "tmdb_id": tmdb_support.MOVIE_ID})

    (call,) = result["trace"][0]["data"]["calls"]
    assert call["url"] == transport.calls[0][3] and tmdb_support.TOKEN not in json.dumps(result)


# --- failures never carry the key ----------------------------------------------------------------------------


def _leaky(secret: str):
    def explode(*args: Any, **kwargs: Any):
        raise urllib.error.URLError(f"failed https://h.test/?apikey={secret}&key={secret} {secret}")

    return explode


def test_a_transport_that_fails_with_the_key_in_its_message_leaks_nothing_in_any_tool(capsys) -> None:
    outputs = []

    tool, _ = tmdb_support.make_tool({f"/movie/{tmdb_support.MOVIE_ID}": _leaky(tmdb_support.SECRET)})
    outputs.append((tmdb_support.SECRET, tmdb_support.run(tool, {"operation": "movie_details", "tmdb_id": tmdb_support.MOVIE_ID})))

    tool, _ = youtube_support.make_tool({"/search": _leaky(youtube_support.SECRET)})
    outputs.append((youtube_support.SECRET, tool.run(query="q", params={"title": "Dune", "kinds": ["making_of"]})))

    tool, _ = omdb_support.make_tool(_leaky(omdb_support.SECRET))
    outputs.append((omdb_support.SECRET, tool.run(query="q", params={"imdb_id": "tt1000001"})))

    for secret, result in outputs:
        assert result["outcome"]["status"] == "error"
        for step in result["trace"]:
            view = STEP_SERIALIZERS[step["kind"]](TraceStep(**step), "it")
            STEP_RENDERERS[step["kind"]](TraceStep(**step), "it")
            assert secret not in json.dumps(view)
        assert secret not in json.dumps(result, default=str) + capsys.readouterr().out


# --- tools without HTTP calls are unchanged ----------------------------------------------------------------


def test_a_step_without_calls_shows_none_and_the_non_http_steps_are_untouched(capsys) -> None:
    empty = TraceStep(kind=STEP_OMDB_CALLS, title="t", data={})
    assert STEP_SERIALIZERS[STEP_OMDB_CALLS](empty, "it")["calls"] == []

    db = TraceStep(kind="db_query", title="DB", data={"queries": [{"sql": "SELECT 1", "params": []}]})
    assert "calls" not in STEP_SERIALIZERS["db_query"](db, "it")
