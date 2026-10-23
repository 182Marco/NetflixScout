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
    tool, transport = make_tool(
        {"/search": {"items": items}, "/videos": {"items": [video_item(ID2, "Making of a sci-fi epic", description="Desert.")]}}
    )

    result = run_tool(tool)

    row = kinds(result)["making_of"]
    assert row["returned"] == 4 and row["result"] == "empty"
    assert row["filtered_out"] == {"invalid_id": 2, "negative_pattern": 1, "no_anchor": 1}
    assert step(result)["searches"][0]["filtered_out"] == row["filtered_out"]
    # The reaction is dropped on its snippet title; the other one is judged on `/videos` data.
    assert transport.paths == ["/search", "/videos"]
    assert transport.calls[1][1]["id"] == ID2


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
        "notes": [],
        "verification": "confirmed",
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



# --- relevance on the full `/videos` data (fix 1 after the live run) -------------------------

# The search snippet description is truncated by the API (about 160 characters).
TRUNCATED = "A look at how the film about a man who falls in love with an operating system was made, from the first..."
FULL_WITH_DIRECTOR = TRUNCATED + " Interviews with writer-director Spike Jonze, Joaquin Phoenix and the crew."


def her_routes(full_description: str, videos=None):
    return {
        "/search": {"items": [search_item(ID1, "Her - Making of", description=TRUNCATED, published_at="2014-01-10T00:00:00Z")]},
        "/videos": videos if videos is not None else {"items": [video_item(ID1, "Her - Making of", description=full_description)]},
    }


def her(tool):
    return run_tool(tool, title="Her", director="Spike Jonze")


def test_the_director_in_the_full_description_confirms_a_one_word_title() -> None:
    tool, transport = make_tool(her_routes(FULL_WITH_DIRECTOR))

    row = kinds(her(tool))["making_of"]

    assert [hit["video_id"] for hit in row["hits"]] == [ID1]
    assert row["hits"][0]["matched_on"] == ["title", "director"]
    assert "title_from_search" not in row["hits"][0]["notes"]
    assert transport.paths == ["/search", "/videos"]


def test_without_the_director_anywhere_a_one_word_title_is_a_homonym_risk() -> None:
    tool, _ = make_tool(her_routes(TRUNCATED + " A short film by a student about a summer romance."))

    row = kinds(her(tool))["making_of"]

    assert row["hits"] == [] and row["filtered_out"] == {"homonym_risk": 1}


def test_the_lookup_covers_every_video_not_dropped_by_its_title_in_one_call() -> None:
    search = by_kind(
        {
            "making": {"items": [search_item(ID1, "Her - Making of", description=TRUNCATED), search_item(ID2, "Her making of REACTION")]},
            "behind": {"items": [search_item(ID3, "Her | behind the scenes", description=TRUNCATED)]},
        }
    )
    videos = {
        "items": [
            video_item(ID1, "Her - Making of", description=FULL_WITH_DIRECTOR),
            video_item(ID3, "Her | behind the scenes", description="Spike Jonze on set."),
        ]
    }
    tool, transport = make_tool({"/search": search, "/videos": videos})

    result = run_tool(tool, title="Her", director="Spike Jonze", kinds=["making_of", "behind_the_scenes"])

    assert transport.paths == ["/search", "/search", "/videos"]
    assert transport.calls[2][1]["id"] == f"{ID1},{ID3}"  # the reaction never reaches the lookup
    assert kinds(result)["making_of"]["filtered_out"] == {"negative_pattern": 1}
    assert [hit["video_id"] for row in meta(result)["kinds"] for hit in row["hits"]] == [ID1, ID3]


def test_full_description_also_confirms_a_one_word_title_for_behind_the_scenes() -> None:
    """Barbie behind the scenes: no year, director named only in the full description."""
    routes = {
        "/search": {"items": [search_item(ID1, "Barbie - Behind the Scenes", description="Go behind the scenes of the pink...")]},
        "/videos": {"items": [video_item(ID1, "Barbie - Behind the Scenes", description="Go behind the scenes of the pink world built by Greta Gerwig.")]},
    }
    tool, _ = make_tool(routes)

    row = kinds(run_tool(tool, title="Barbie", director="Greta Gerwig", kinds=["behind_the_scenes"]))["behind_the_scenes"]

    assert [hit["video_id"] for hit in row["hits"]] == [ID1] and "director" in row["hits"][0]["matched_on"]


@pytest.mark.parametrize("failure", [error_body(500), error_body(403, "quotaExceeded"), TimeoutError("t")])
def test_failed_lookup_falls_back_to_the_snippet_as_before(failure) -> None:
    tool, _ = make_tool(her_routes(FULL_WITH_DIRECTOR, videos=failure))

    result = her(tool)

    # The truncated snippet does not name the director: same verdict as before the fix.
    assert kinds(result)["making_of"]["filtered_out"] == {"homonym_risk": 1}
    assert meta(result)["details_error"] in {"http_error", "quota_exceeded", "timeout"}


def test_failed_lookup_keeps_videos_the_snippet_confirms() -> None:
    routes = {
        "/search": {"items": [search_item(ID1, "Her - Making of", description="Spike Jonze on making Her.")]},
        "/videos": error_body(500),
    }
    tool, _ = make_tool(routes)

    hit = kinds(her(tool))["making_of"]["hits"][0]

    assert "title_from_search" in hit["notes"] and hit["matched_on"] == ["title", "director"]


def test_videos_beyond_the_lookup_limit_are_judged_on_the_snippet(monkeypatch) -> None:
    monkeypatch.setattr(tool_module, "VIDEO_IDS_MAX", 1)
    routes = {
        "/search": {
            "items": [
                search_item(ID1, "Her - Making of", description=TRUNCATED),
                search_item(ID2, "Her making of", description="Spike Jonze explains."),
            ]
        },
        "/videos": {"items": [video_item(ID1, "Her - Making of", description=FULL_WITH_DIRECTOR)]},
    }
    tool, transport = make_tool(routes)

    hits = kinds(her(tool))["making_of"]["hits"]

    assert transport.calls[1][1]["id"] == ID1
    assert [(hit["video_id"], "title_from_search" in hit["notes"]) for hit in hits] == [(ID1, False), (ID2, True)]


def test_a_video_dropped_for_one_kind_can_be_kept_for_another() -> None:
    """Duplicates are checked on what was shown, not on what was searched."""
    same = search_item(ID1, "Barbie | featurette", description="Greta Gerwig...")
    tool, _ = make_tool(
        {
            "/search": {"items": [same]},
            "/videos": {"items": [video_item(ID1, "Barbie | featurette", description="Greta Gerwig and the cast.")]},
        }
    )

    result = run_tool(tool, title="Barbie", director="Greta Gerwig", kinds=["making_of", "behind_the_scenes"])

    assert [hit["video_id"] for hit in kinds(result)["making_of"]["hits"]] == [ID1]
    assert kinds(result)["behind_the_scenes"]["filtered_out"] == {"duplicate_of_other_kind": 1}


def test_other_format_is_counted_and_judged_on_the_videos_title() -> None:
    """End to end: the review and the full movie are dropped, the interview stays."""
    routes = {
        "/search": {
            "items": [
                search_item(ID1, "Parasite review", description="Bong Joon-ho..."),
                search_item(ID2, "PARASITE Full Movie"),
                search_item(ID3, "Bong Joon-ho interview on Parasite"),
            ]
        },
        "/videos": {
            "items": [
                video_item(ID1, "Parasite review", description="Bong Joon-ho's film reviewed."),
                video_item(ID2, "PARASITE Full Movie"),
                video_item(ID3, "Bong Joon-ho interview on Parasite"),
            ]
        },
    }
    tool, transport = make_tool(routes)

    row = kinds(run_tool(tool, title="Parasite", director="Bong Joon-ho", kinds=["director_interview"]))["director_interview"]

    assert [hit["video_id"] for hit in row["hits"]] == [ID3]
    assert row["filtered_out"] == {"other_format": 2}
    assert transport.calls[1][1]["id"] == f"{ID1},{ID2},{ID3}"  # decided after /videos, not on the snippet



def test_cast_interview_end_to_end_with_names_from_the_request() -> None:
    routes = {
        "/search": {
            "items": [
                search_item(ID1, 'J. Robert Oppenheimer: "I am become Death"', published_at="2011-08-06T00:00:00Z"),
                search_item(ID2, "Cillian Murphy on Oppenheimer", published_at="2023-07-20T00:00:00Z"),
            ]
        },
        "/videos": {
            "items": [
                video_item(ID1, 'J. Robert Oppenheimer: "I am become Death"', description="1965 interview."),
                video_item(ID2, "Cillian Murphy on Oppenheimer", description="The cast talks about the film."),
            ]
        },
    }
    tool, transport = make_tool(routes)

    result = run_tool(tool, title="Oppenheimer", cast=["Cillian Murphy"], kinds=["cast_interview"])

    assert transport.calls[0][1]["q"].startswith('"Oppenheimer" "Cillian Murphy"|"Murphy" interview|')
    row = kinds(result)["cast_interview"]
    assert [hit["video_id"] for hit in row["hits"]] == [ID2] and row["filtered_out"] == {"homonym_risk": 1}
    assert row["hits"][0]["matched_on"] == ["title", "cast"]


# --- fix 5: original title from the conversation reaches the search ----------------------------


class _PlannerClient:
    """Planning call -> `plan`; final answer otherwise. Records the planner input."""

    def __init__(self, plan: dict) -> None:
        self.outputs = [json.dumps(plan), "Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": self.outputs.pop(0)})()


_SEA_INSIDE_HISTORY = [
    {"role": "user", "content": "Parlami di Mare dentro"},
    {"role": "assistant", "content": "Mare dentro (titolo originale Mar adentro, 2004) è diretto da Alejandro Amenábar."},
]


def _orchestrated(plan: dict, history: list[dict]):
    from orchestrator import LLMOrchestrator

    import app as app_module

    tool, transport = make_tool({"/search": {"items": []}})
    client = _PlannerClient(plan)
    config = app_module.build_runtime_config({"orchestrator": {"allowed_tools": ["youtube_search"]}})
    orchestrator = LLMOrchestrator(config=config, tools=[tool], client=client)
    decision = orchestrator.run(query="E un'intervista al regista?", conversation_history=history)
    return decision, transport, client


def test_original_title_from_the_history_reaches_the_query() -> None:
    plan = {
        "standalone_query": "Cerca un'intervista al regista di Mare dentro",
        "tool_name": "youtube_search",
        "arguments": {
            "title": "Mare dentro",
            "alternative_titles": ["Mar adentro"],
            "director": "Alejandro Amenábar",
            "kinds": ["director_interview"],
        },
        "confidence": 0.9,
    }

    decision, transport, client = _orchestrated(plan, _SEA_INSIDE_HISTORY)

    # The planner saw the history that contains the original title...
    assert any("Mar adentro" in message["content"] for message in client.calls[0]["input"])
    # ...and its arguments reach the search unchanged.
    assert decision["tool"] == "youtube_search"
    assert transport.calls[0][1]["q"].startswith('"Mare dentro"|"Mar adentro" interview|')


def test_without_alternatives_in_the_plan_the_search_uses_the_title_as_given() -> None:
    plan = {
        "standalone_query": "Making of di Il favoloso mondo di Amélie",
        "tool_name": "youtube_search",
        "arguments": {"title": "Il favoloso mondo di Amélie", "kinds": ["making_of"]},
        "confidence": 0.9,
    }

    _, transport, _ = _orchestrated(plan, [])

    assert transport.calls[0][1]["q"].startswith('"Il favoloso mondo di Amélie" "making of"')


def test_the_planner_catalog_carries_the_alternative_titles_rule() -> None:
    from orchestrator import LLMOrchestrator

    import app as app_module

    tool, _ = make_tool()
    orchestrator = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[tool], client=_PlannerClient({}))

    catalog = orchestrator._catalog_text(["youtube_search"])

    assert "never deduce one from your own knowledge" in catalog
    assert "for a localized title with no other title written, leave it empty" in catalog



# --- fix 6: confirmed and to-verify results, hints for the answer -----------------------------


def test_each_hit_is_labelled_from_its_notes_and_the_api_order_is_kept() -> None:
    routes = {
        "/search": {
            "items": [
                search_item(ID1, "Dune: Part Two - Making of"),
                search_item(ID2, "Dune: Part Two | Official Featurette"),  # no making-of word
                search_item(ID3, "Dune: Part Two making of the sandworm"),
            ]
        },
        "/videos": {
            "items": [
                video_item(ID1, "Dune: Part Two - Making of"),
                video_item(ID2, "Dune: Part Two | Official Featurette"),
                video_item(ID3, "Dune: Part Two making of the sandworm"),
            ]
        },
    }
    tool, _ = make_tool(routes)

    result = run_tool(tool)

    hits = kinds(result)["making_of"]["hits"]
    assert [(hit["video_id"], hit["verification"]) for hit in hits] == [
        (ID1, "confirmed"),
        (ID2, "to_verify"),
        (ID3, "confirmed"),
    ]  # labels only: nothing reordered, nothing dropped
    assert [video["verification"] for video in step(result)["videos"]] == ["confirmed", "to_verify", "confirmed"]


@pytest.mark.parametrize(
    ("notes", "label"),
    [
        ([], "confirmed"),
        (["very_short", "duration_unknown", "title_from_search", "blocked_in:IT"], "confirmed"),
        (["kind_unconfirmed"], "to_verify"),
        (["homonym_unchecked"], "to_verify"),
        (["film_title_absent"], "to_verify"),
        (["title_in_description_only"], "to_verify"),
    ],
)
def test_verification_comes_only_from_relevance_notes(notes, label) -> None:
    from youtube.relevance import verification

    assert verification(notes) == label


def test_unchecked_one_word_title_asks_for_the_year_and_the_original_title() -> None:
    routes = {"/search": {"items": [search_item(ID1, "Arrival - Behind the scenes")]}, "/videos": {"items": [video_item(ID1, "Arrival - Behind the scenes")]}}
    tool, _ = make_tool(routes)

    result = run_tool(tool, title="Arrival", kinds=["behind_the_scenes"])

    hit = kinds(result)["behind_the_scenes"]["hits"][0]
    assert hit["verification"] == "to_verify" and "homonym_unchecked" in hit["notes"]
    assert meta(result)["hints"] == ["specify_year", "original_title"]
    assert step(result)["hints"] == ["specify_year", "original_title"]


def test_dropped_homonyms_without_a_year_also_ask_for_the_year() -> None:
    routes = {"/search": {"items": [search_item(ID1, "Her - Making of")]}, "/videos": {"items": [video_item(ID1, "Her - Making of")]}}
    tool, _ = make_tool(routes)

    result = run_tool(tool, title="Her", director="Spike Jonze")

    assert kinds(result)["making_of"]["filtered_out"] == {"homonym_risk": 1}
    assert "specify_year" in meta(result)["hints"]


def test_no_hints_when_everything_is_confirmed() -> None:
    tool, _ = make_tool(making_of_routes())

    result = run_tool(tool, kinds=["behind_the_scenes"], year=2024)

    assert all(hit["verification"] == "confirmed" for hit in kinds(result)["behind_the_scenes"]["hits"])
    assert meta(result)["hints"] == [] and "hints" not in step(result)


def test_a_given_year_or_alternative_title_is_never_asked_again() -> None:
    routes = {"/search": {"items": [search_item(ID1, "Some other video")]}, "/videos": {"items": [video_item(ID1, "Some other video")]}}
    tool, _ = make_tool(routes)

    result = run_tool(tool, title="Mare dentro", alternative_titles=["Mar adentro"], year=2004, kinds=["making_of"])

    assert kinds(result)["making_of"]["result"] == "empty"
    assert meta(result)["hints"] == []


def test_empty_kind_without_alternatives_suggests_the_original_title_only() -> None:
    tool, _ = make_tool({"/search": {"items": []}})

    result = run_tool(tool, title="Il favoloso mondo di Amélie", year=2001)

    assert meta(result)["hints"] == ["original_title"]
