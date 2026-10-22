"""Offline tests of `youtube/tool.py`: fake transport, no network, no `.env`."""
from __future__ import annotations

import json

import pytest
from youtube_support import (
    BASE,
    SECRET,
    by_kind,
    error_body,
    make_tool,
    run_tool,
    search_item,
    video_item,
)

from orchestrator import Tool
from turn import STEP_YOUTUBE_CALLS
from youtube import tool as tool_module
from youtube.errors import YoutubeConfigError
from youtube.models import YoutubeToolInput
from youtube.quota import QuotaBucket, QuotaLatch
from youtube.tool import YOUTUBE_TOOL_NAME, overall_status

ID1, ID2, ID3, ID4 = "vid00000001", "vid00000002", "vid00000003", "vid00000004"
SEARCH_URL = f"{BASE}/search?key=***"
VIDEOS_URL = f"{BASE}/videos?key=***"


def meta(result: dict) -> dict:
    return result["metadata"]["youtube"]


def kinds(result: dict) -> dict[str, dict]:
    return {row["kind"]: row for row in meta(result)["kinds"]}


def step(result: dict) -> dict:
    [only] = result["trace"]
    assert only["kind"] == STEP_YOUTUBE_CALLS and only["title"] == "YouTube"
    return only["data"]


def making_of_routes(**extra):
    return {
        "/search": by_kind(
            {
                "making": {"items": [search_item(ID1, "Dune: Part Two - Making of"), search_item(ID2, "Dune: Part Two | Official Featurette")]},
                "behind": {"items": [search_item(ID3, "Dune: Part Two - Behind the Scenes")]},
                "interview": {"items": [search_item(ID4, "Denis Villeneuve interview on Dune: Part Two")]},
            }
        ),
        "/videos": {
            "items": [
                video_item(ID1, "Dune: Part Two – “Making of” & more", channel="Warner Bros. Italia"),
                video_item(ID2, "Dune: Part Two | Official Featurette", channel="Legendary"),
                video_item(ID3, "Dune: Part Two - Behind the Scenes", channel="IGN"),
                video_item(ID4, "Denis Villeneuve interview on Dune: Part Two", channel="Variety"),
            ]
        },
        **extra,
    }


# --- contract ---------------------------------------------------------------------------


def test_the_tool_follows_the_orchestrator_contract() -> None:
    tool, _ = make_tool(making_of_routes())

    assert isinstance(tool, Tool)
    assert tool.name == YOUTUBE_TOOL_NAME == "youtube_search"
    assert tool.input_schema == YoutubeToolInput.model_json_schema()
    assert "tmdb_search" in tool.description and "never invented" in tool.description

    result = run_tool(tool)

    assert set(result) == {"query", "chunks", "metadata", "trace"}
    assert result["query"] == "domanda" and result["chunks"] == []
    json.dumps(result)  # JSON-ready: metadata goes into the prompt, trace to the presenters


def test_happy_path_one_search_and_one_videos_lookup() -> None:
    tool, transport = make_tool(making_of_routes())

    result = run_tool(tool, kinds=["making_of", "behind_the_scenes"])

    assert transport.paths == ["/search", "/search", "/videos"]
    assert transport.calls[2][1]["id"] == f"{ID1},{ID2},{ID3}"
    assert meta(result)["status"] == "ok" and meta(result)["not_searched"] == []
    making = kinds(result)["making_of"]
    assert (making["status"], making["result"], making["returned"]) == ("searched", "ok", 2)
    assert [hit["video_id"] for hit in making["hits"]] == [ID1, ID2]  # API order kept
    assert step(result)["calls"] == [SEARCH_URL, SEARCH_URL, VIDEOS_URL]


def test_titles_channels_and_urls_are_the_api_values() -> None:
    tool, _ = make_tool(making_of_routes())

    hit = kinds(run_tool(tool))["making_of"]["hits"][0]

    assert hit["title"] == "Dune: Part Two – “Making of” & more"
    assert hit["channel"] == "Warner Bros. Italia"
    assert hit["url"] == f"https://www.youtube.com/watch?v={ID1}"
    assert hit["published_at"] == "2024-02-20T10:00:00Z" and hit["duration_seconds"] == 300
    assert "title_from_search" not in hit["notes"]


def test_control_characters_reach_metadata_unchanged() -> None:
    """Sanitizing for the terminal is the presenter's job (step 8), never the tool's."""
    raw = "Dune: Part Two \x1b[31mMaking of\x07"
    routes = making_of_routes()
    routes["/videos"] = {"items": [video_item(ID1, raw), video_item(ID2, "Dune: Part Two featurette")]}
    tool, _ = make_tool(routes)

    result = run_tool(tool)

    assert kinds(result)["making_of"]["hits"][0]["title"] == raw
    assert step(result)["videos"][0]["title"] == raw


def test_max_results_caps_the_hits_of_each_kind() -> None:
    tool, _ = make_tool(making_of_routes(), max_results=1)

    assert [hit["video_id"] for hit in kinds(run_tool(tool))["making_of"]["hits"]] == [ID1]


def test_turn_language_is_accepted_and_ignored() -> None:
    tool, transport = make_tool(making_of_routes())

    tool.run(query="q", params={"title": "Dune: Part Two", "kinds": ["making_of"], "turn_language": "it"}, conversation_history=[])

    assert "relevanceLanguage" not in transport.calls[0][1] and "regionCode" not in transport.calls[0][1]


# --- invalid input and configuration -------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [{}, {"title": "Dune"}, {"title": "Dune", "kinds": ["bloopers"]}, {"title": "Dune", "kinds": ["trailer"], "url": "x"}],
)
def test_invalid_input_sends_nothing(params) -> None:
    tool, transport = make_tool(making_of_routes())

    result = tool.run(query="Titolo segreto", params=params, conversation_history=[])

    assert transport.calls == [] and result["trace"] == []
    assert meta(result)["status"] == "error" and meta(result)["error"] == "invalid_request"
    assert "Titolo segreto" not in json.dumps(meta(result)["errors"])


def test_missing_key_sends_nothing(monkeypatch) -> None:
    def _missing():
        raise YoutubeConfigError("YouTube API key missing: set YOUTUBE_API_KEY in .env.")

    monkeypatch.setattr(tool_module, "load_credentials", _missing)
    tool, transport = make_tool(making_of_routes())
    tool.credentials = None

    result = run_tool(tool)

    assert transport.calls == [] and meta(result)["error"] == "not_configured"
    assert "YOUTUBE_API_KEY" in meta(result)["detail"]


def test_credentials_are_read_on_first_use_only(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(tool_module, "load_credentials", lambda: calls.append(1) or tool_module.YoutubeCredentials(secret=SECRET))
    tool, _ = make_tool(making_of_routes())
    tool.credentials = None

    run_tool(tool)
    run_tool(tool)

    assert calls == [1]


# --- per-turn limit ------------------------------------------------------------------------


def test_kinds_beyond_the_turn_limit_are_declared_not_searched() -> None:
    tool, transport = make_tool(making_of_routes(), max_searches=2)

    result = run_tool(tool, kinds=["making_of", "behind_the_scenes", "director_interview"])

    assert transport.paths.count("/search") == 2
    assert kinds(result)["director_interview"] == {
        "kind": "director_interview",
        "status": "not_searched",
        "result": None,
        "reason": "turn_limit",
        "error": None,
        "returned": 0,
        "filtered_out": {},
        "hits": [],
    }
    assert meta(result)["not_searched"] == ["director_interview"]
    assert meta(result)["status"] == "partial"
    assert step(result)["not_searched"] == [{"kind": "director_interview", "reason": "turn_limit"}]


def test_the_order_of_kinds_decides_what_is_searched() -> None:
    tool, transport = make_tool(making_of_routes(), max_searches=1)

    result = run_tool(tool, kinds=["director_interview", "making_of"])

    assert "interview" in transport.calls[0][1]["q"]
    assert kinds(result)["making_of"]["reason"] == "turn_limit"


# --- errors and quota ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (error_body(403, "quotaExceeded"), "quota_exceeded"),
        (error_body(403, "rateLimitExceeded"), "rate_limited"),
        (error_body(400, "keyInvalid"), "unauthorized"),
        (error_body(403, "accessNotConfigured"), "api_not_enabled"),
    ],
)
def test_run_stopping_errors_leave_the_other_kinds_not_searched(answer, code) -> None:
    tool, transport = make_tool({"/search": answer, "/videos": {"items": []}}, max_searches=3)

    result = run_tool(tool, kinds=["making_of", "behind_the_scenes", "director_interview"])

    assert transport.paths == ["/search"]  # no useless calls in the same run
    rows = kinds(result)
    assert (rows["making_of"]["status"], rows["making_of"]["result"], rows["making_of"]["error"]) == ("searched", "error", code)
    assert rows["behind_the_scenes"]["reason"] == code and rows["director_interview"]["reason"] == code
    assert meta(result)["status"] == "error"


def test_quota_error_pauses_later_runs_and_is_shown_in_the_trace() -> None:
    latch = QuotaLatch()
    tool, transport = make_tool({"/search": error_body(403, "quotaExceeded")}, latch=latch)

    first = run_tool(tool)
    second = run_tool(tool, kinds=["making_of", "behind_the_scenes"])

    assert len(transport.calls) == 1
    assert "quota_paused_until" in step(first) and "quota_paused_until" in step(second)
    assert [row["reason"] for row in meta(second)["kinds"]] == ["quota_exceeded", "quota_exceeded"]
    assert step(second)["calls"] == [] and step(second)["searches"] == []


def test_key_errors_do_not_pause_later_runs() -> None:
    tool, transport = make_tool({"/search": error_body(400, "keyInvalid")})

    run_tool(tool)
    run_tool(tool)

    assert len(transport.calls) == 2
    assert tool.latch.blocked(QuotaBucket.search) is None


def test_a_new_tool_tries_again_after_a_quota_error_elsewhere() -> None:
    old, _ = make_tool({"/search": error_body(403, "quotaExceeded")})
    run_tool(old)

    fresh, transport = make_tool(making_of_routes())
    result = run_tool(fresh)

    assert transport.paths[0] == "/search" and meta(result)["status"] == "ok"


@pytest.mark.parametrize(("failure", "code"), [(TimeoutError("t"), "timeout"), (ConnectionResetError("x"), "network_error")])
def test_transient_errors_do_not_stop_the_other_kinds(failure, code) -> None:
    calls = []

    def _route(params):
        calls.append(params["q"])
        if len(calls) == 1:
            raise failure
        return {"items": [search_item(ID3, "Dune: Part Two - Behind the Scenes")]}

    tool, _ = make_tool({"/search": _route, "/videos": {"items": [video_item(ID3, "Dune: Part Two - Behind the Scenes")]}})

    result = run_tool(tool, kinds=["making_of", "behind_the_scenes"])

    assert kinds(result)["making_of"]["error"] == code
    assert kinds(result)["behind_the_scenes"]["result"] == "ok"
    assert meta(result)["status"] == "partial"


# --- empty and filtered results ------------------------------------------------------------


def test_no_results_is_empty_not_an_error() -> None:
    tool, transport = make_tool({"/search": {"items": []}})

    result = run_tool(tool)

    assert transport.paths == ["/search"]  # nothing to look up
    assert meta(result)["status"] == "empty" and kinds(result)["making_of"]["result"] == "empty"


def test_filtered_out_results_are_counted_by_reason() -> None:
    items = [
        search_item(ID1, "Dune: Part Two REACTION"),
        search_item(ID2, "Making of a sci-fi epic"),
        {"id": {"kind": "youtube#channel", "channelId": "UC123"}, "snippet": {"title": "Dune channel"}},
        search_item("bad id", "Dune: Part Two making of"),
    ]
    tool, transport = make_tool({"/search": {"items": items}})

    result = run_tool(tool)

    row = kinds(result)["making_of"]
    assert row["returned"] == 4 and row["result"] == "empty"
    assert row["filtered_out"] == {"invalid_id": 2, "negative_pattern": 1, "no_anchor": 1}
    assert step(result)["searches"][0]["filtered_out"] == row["filtered_out"]
    assert transport.paths == ["/search"]


def test_a_video_kept_for_one_kind_is_not_repeated_for_another() -> None:
    same = search_item(ID1, "Dune: Part Two - Making of and behind the scenes")
    tool, _ = make_tool({"/search": {"items": [same]}, "/videos": {"items": [video_item(ID1, same["snippet"]["title"])]}})

    result = run_tool(tool, kinds=["making_of", "behind_the_scenes"])

    assert [hit["video_id"] for hit in kinds(result)["making_of"]["hits"]] == [ID1]
    assert kinds(result)["behind_the_scenes"]["filtered_out"] == {"duplicate_of_other_kind": 1}


def test_self_declared_shorts_are_dropped_after_the_lookup() -> None:
    routes = making_of_routes()
    routes["/videos"] = {
        "items": [video_item(ID1, "Dune: Part Two making of #shorts", duration="PT40S"), video_item(ID2, "Dune: Part Two featurette", duration="PT45S")]
    }
    tool, _ = make_tool(routes)

    row = kinds(run_tool(tool))["making_of"]

    assert [hit["video_id"] for hit in row["hits"]] == [ID2] and "very_short" in row["hits"][0]["notes"]
    assert row["filtered_out"] == {"short_video": 1}


def test_a_video_missing_from_the_lookup_is_unavailable() -> None:
    routes = making_of_routes()
    routes["/videos"] = {"items": [video_item(ID2, "Dune: Part Two | Official Featurette")]}
    tool, _ = make_tool(routes)

    row = kinds(run_tool(tool))["making_of"]

    assert [hit["video_id"] for hit in row["hits"]] == [ID2] and row["filtered_out"] == {"unavailable": 1}


def test_failed_lookup_keeps_search_data_decoded_and_noted() -> None:
    routes = making_of_routes()
    routes["/search"] = {"items": [search_item(ID1, "Schindler&#39;s List: making of", channel="Film &amp; TV")]}
    routes["/videos"] = error_body(500)
    tool, _ = make_tool(routes)

    result = run_tool(tool, title="Schindler's List")

    hit = kinds(result)["making_of"]["hits"][0]
    assert (hit["title"], hit["channel"]) == ("Schindler's List: making of", "Film & TV")
    assert "title_from_search" in hit["notes"] and "duration_unknown" in hit["notes"]
    assert meta(result)["details_error"] == "http_error" and meta(result)["status"] == "ok"


def test_region_restriction_is_a_note_only() -> None:
    routes = making_of_routes()
    routes["/videos"] = {
        "items": [
            video_item(ID1, "Dune: Part Two making of", region={"blocked": ["IT", "DE"]}),
            video_item(ID2, "Dune: Part Two featurette", region={"allowed": ["US"]}),
        ]
    }
    tool, _ = make_tool(routes)

    hits = kinds(run_tool(tool))["making_of"]["hits"]

    assert [hit["video_id"] for hit in hits] == [ID1, ID2]
    assert all("blocked_in:IT" in hit["notes"] for hit in hits)


def test_description_excerpt_is_capped_and_labelled() -> None:
    routes = making_of_routes()
    routes["/videos"] = {"items": [video_item(ID1, "Dune: Part Two making of", description="x" * 1000)]}
    tool, _ = make_tool(routes)

    hit = kinds(run_tool(tool))["making_of"]["hits"][0]

    assert len(hit["description_excerpt"]) == 300


# --- trace and secrets --------------------------------------------------------------------


def test_trace_lists_calls_queries_and_videos() -> None:
    tool, _ = make_tool(making_of_routes())

    data = step(run_tool(tool, kinds=["making_of", "behind_the_scenes"]))

    assert data["calls"] == [SEARCH_URL, SEARCH_URL, VIDEOS_URL]
    assert [row["kind"] for row in data["searches"]] == ["making_of", "behind_the_scenes"]
    assert data["searches"][0]["q"].startswith('"Dune: Part Two" "making of"')
    assert data["searches"][0]["kept"] == 2 and data["searches"][0]["returned"] == 2
    assert data["videos"][0] == {
        "kind": "making_of",
        "title": "Dune: Part Two – “Making of” & more",
        "channel": "Warner Bros. Italia",
        "url": f"https://www.youtube.com/watch?v={ID1}",
        "published_at": "2024-02-20T10:00:00Z",
    }
    assert "quota_paused_until" not in data


@pytest.mark.parametrize(
    "routes",
    [
        making_of_routes(),
        {"/search": error_body(403, "quotaExceeded", message=f"key {SECRET}")},
        {"/search": error_body(400, "keyInvalid", message=f"API key not valid: {SECRET}")},
        {"/search": ConnectionResetError(f"https://www.googleapis.com/youtube/v3/search?key={SECRET}")},
    ],
)
def test_the_key_never_appears_in_the_result(routes) -> None:
    tool, transport = make_tool(routes)

    result = run_tool(tool)

    assert SECRET in transport.calls[0][3]  # it was sent
    assert SECRET not in json.dumps(result) and SECRET not in repr(result) and SECRET not in repr(tool)


# --- overall status -------------------------------------------------------------------------


def test_overall_status() -> None:
    from youtube.models import KindOutcome, VideoHit

    hit = VideoHit(video_id=ID1, url="u", title="t", channel="c")
    ok = KindOutcome(kind="making_of", status="searched", result="ok", hits=[hit])
    empty = KindOutcome(kind="trailer", status="searched", result="empty")
    error = KindOutcome(kind="trailer", status="searched", result="error", error="timeout")
    skipped = KindOutcome(kind="trailer", status="not_searched", reason="turn_limit")

    assert overall_status([ok]) == "ok"
    assert overall_status([ok, empty]) == "ok"
    assert overall_status([empty]) == "empty"
    assert overall_status([ok, error]) == "partial"
    assert overall_status([empty, skipped]) == "partial"
    assert overall_status([error]) == "error"
    assert overall_status([skipped]) == "error"

