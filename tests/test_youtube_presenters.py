"""Offline tests of the YouTube presenters: terminal renderer, web serializer."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from youtube_support import SECRET, make_tool, run_tool, search_item, video_item

from presenters import OutputChannel, present
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.terminal.youtube import render_youtube_calls
from presenters.terminal.youtube.blocks import printable
from turn import STEP_YOUTUBE_CALLS, TraceStep, TurnResult

ROOT = Path(__file__).resolve().parents[1]
ID1, ID2 = "vid00000001", "vid00000002"
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search?key=***"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos?key=***"
URL1 = f"https://www.youtube.com/watch?v={ID1}"


def _step(**data) -> TraceStep:
    base = {
        "calls": [SEARCH_URL, VIDEOS_URL],
        "searches": [
            {
                "kind": "making_of",
                "q": '"Dune: Part Two" "making of" -reaction -parody',
                "result": "ok",
                "error": None,
                "returned": 9,
                "kept": 1,
                "filtered_out": {"no_anchor": 3, "homonym_risk": 1},
            }
        ],
        "not_searched": [{"kind": "director_interview", "reason": "turn_limit"}],
        "videos": [
            {
                "kind": "making_of",
                "title": "Dune: Part Two – “Making of” & more",
                "channel": "Warner Bros. Italia",
                "url": URL1,
                "published_at": "2024-02-20T10:00:00Z",
                "notes": ["kind_unconfirmed", "blocked_in:IT"],
            }
        ],
    }
    return TraceStep(kind=STEP_YOUTUBE_CALLS, title="YouTube", data={**base, **data})


def _turn(step: TraceStep, language: str = "it") -> TurnResult:
    return TurnResult(query="q", language=language, blocked=False, answer="Risposta.", tool="youtube_search", steps=[step])


def _render(step: TraceStep, language: str, capsys) -> str:
    present(_turn(step, language), OutputChannel.terminal)
    return capsys.readouterr().out


# --- registration and layout ----------------------------------------------------------------


def test_the_renderer_is_registered_for_the_step() -> None:
    assert STEP_RENDERERS[STEP_YOUTUBE_CALLS] is render_youtube_calls


def test_step_is_rendered_before_the_final_answer_not_with_the_generic_fallback(capsys) -> None:
    out = _render(_step(), "it", capsys)

    assert out.index("YOUTUBE — 1 VIDEO") < out.index("Risposta.")
    assert "calls: [" not in out  # generic fallback prints the raw dict items


# --- content ----------------------------------------------------------------------------------


def test_italian_labels_results_reasons_and_notes(capsys) -> None:
    out = _render(_step(), "it", capsys)

    assert "Fonte: YouTube" in out
    assert f"Chiamato: {SEARCH_URL}" in out and f"Chiamato: {VIDEOS_URL}" in out
    assert 'Ricerca making-of: "Dune: Part Two" "making of" -reaction -parody' in out
    assert "9 ricevuti, 1 tenuti; scartati: film non nominato 3, possibile omonimo 1" in out
    assert "Non cercato: interviste al regista" in out and "limite di ricerche" not in out
    assert "▶ [making-of] Dune: Part Two – “Making of” & more — Warner Bros. Italia (2024-02-20)" in out
    assert URL1 in out
    assert "note: categoria non confermata dal titolo, non visibile in IT" in out


def test_english_labels(capsys) -> None:
    out = _render(_step(), "en", capsys)

    assert "Source: YouTube" in out and f"Called: {SEARCH_URL}" in out
    assert "Not searched: director interviews" in out and "search limit" not in out
    assert "notes: category not confirmed by the title, not viewable in IT" in out


def test_errors_and_quota_pause_are_shown(capsys) -> None:
    step = _step(
        calls=[SEARCH_URL],
        searches=[{"kind": "making_of", "q": "q", "result": "error", "error": "quota_exceeded", "returned": 0, "kept": 0, "filtered_out": {}}],
        not_searched=[{"kind": "behind_the_scenes", "reason": "quota_exceeded"}],
        videos=[],
        quota_paused_until="2026-10-24T07:00:00+00:00",
    )

    out = _render(step, "it", capsys)

    assert "errore: quota giornaliera esaurita" in out
    assert "Non cercato: dietro le quinte" in out
    assert "Quota di ricerca YouTube esaurita (condivisa dal progetto Google) fino a 2026-10-24T07:00:00+00:00" in out
    assert "Nessun video da mostrare." in out


def test_no_calls_in_the_turn(capsys) -> None:
    out = _render(_step(calls=[], searches=[], videos=[]), "en", capsys)

    assert "No YouTube call in this turn." in out


def test_only_https_urls_and_well_formed_rows_are_shown(capsys) -> None:
    step = _step(
        calls=[SEARCH_URL, "javascript:alert(1)", {"url": "x"}],
        videos=[
            {"kind": "making_of", "title": "Bad", "channel": "c", "url": "http://evil.example/x"},
            "not a row",
            {"kind": "making_of", "title": "Good", "channel": "c", "url": URL1},
        ],
        searches="not a list",
    )

    out = _render(step, "it", capsys)

    assert "javascript" not in out and "evil.example" not in out and "Bad" not in out
    assert "Good" in out and "YOUTUBE — 1 VIDEO" in out


# --- sanitization -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("Dune \x1b[31mMaking of\x1b[0m", "Dune [31mMaking of[0m"),
        ("Dune\x07\x00\x7f", "Dune"),
        ("Dune\x9b2J\x85Part Two", "Dune2J Part Two"),  # C1: CSI removed, NEL as a space
        ("Dune\nPart\tTwo\r", "Dune Part Two "),
    ],
)
def test_control_characters_are_removed_for_display(raw, shown) -> None:
    assert printable(raw) == shown


@pytest.mark.parametrize(
    "text",
    ["Dune: Part Two – “Making of” & more", "C'è ancora domani", "千と千尋の神隠し", "Amélie 🎬", "Schindler's List"],
)
def test_printable_text_is_unchanged(text) -> None:
    assert printable(text) == text


def test_terminal_output_has_no_control_characters_but_the_step_is_unchanged(capsys) -> None:
    raw_title = "Dune: Part Two \x1b]8;;https://evil.example\x07click\x1b]8;;\x07 Making of"
    step = _step(videos=[{"kind": "making_of", "title": raw_title, "channel": "Chan\x9bnel", "url": URL1, "notes": []}])
    before = copy.deepcopy(step.data)

    out = _render(step, "it", capsys)

    assert not any(ord(c) < 0x20 and c != "\n" or 0x7F <= ord(c) <= 0x9F for c in out)
    assert "click" in out and "Channel" in out
    assert step.data == before and step.data["videos"][0]["title"] == raw_title


def test_tool_metadata_and_trace_keep_control_characters_after_rendering(capsys) -> None:
    """End to end from the tool: display sanitizing never reaches metadata (the LLM prompt)."""
    raw = "Dune: Part Two \x1b[31mMaking of\x07"
    tool, _ = make_tool(
        {
            "/search": {"items": [search_item(ID1, "Dune: Part Two making of")]},
            "/videos": {"items": [video_item(ID1, raw, channel="Chan\x85nel")]},
        }
    )
    result = run_tool(tool)
    metadata_before = json.dumps(result["metadata"])

    out = _render(TraceStep(**result["trace"][0]), "it", capsys)

    assert "Dune: Part Two [31mMaking of" in out and "\x1b" not in out
    assert json.dumps(result["metadata"]) == metadata_before
    hit = result["metadata"]["youtube"]["kinds"][0]["hits"][0]
    assert hit["title"] == raw and hit["channel"] == "Chan\x85nel"
    assert result["trace"][0]["data"]["videos"][0]["title"] == raw


def test_the_key_never_reaches_the_terminal(capsys) -> None:
    tool, _ = make_tool({"/search": {"items": [search_item(ID1, "Dune: Part Two making of")]}, "/videos": {"items": [video_item(ID1, "Dune: Part Two making of")]}})
    result = run_tool(tool)

    out = _render(TraceStep(**result["trace"][0]), "en", capsys)

    assert SECRET not in out and "key=***" in out


# --- notice and isolation ------------------------------------------------------------------------


def test_youtube_presenters_import_only_turn_and_their_own_modules() -> None:
    paths = sorted((ROOT / "presenters" / "terminal" / "youtube").rglob("*.py"))
    paths += sorted((ROOT / "presenters" / "web" / "youtube").rglob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module in {"__future__", "typing", "turn"}, (path, node.module)
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                assert node.module in {"box", "youtube_view"}, (path, node.module)
            if isinstance(node, ast.Import):
                raise AssertionError((path, [alias.name for alias in node.names]))


def test_presenters_never_import_the_youtube_package() -> None:
    for path in sorted((ROOT / "presenters").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert not node.module.startswith("tool"), (path, node.module)


def test_web_serializer_shows_the_same_view_as_the_terminal() -> None:
    from presenters.web.youtube import serialize_youtube_calls_step
    from presenters.youtube_view import youtube_calls_view

    step = _step()

    view = youtube_calls_view(step, "it").model_dump(mode="json", exclude={"not_searched"})
    view["labels"].pop("not_searched")

    # Same view, except the terminal-only "not searched" line.
    assert serialize_youtube_calls_step(step, "it") == {"kind": step.kind, **view}


def test_web_channel_returns_a_payload_with_the_step() -> None:
    payload = present(_turn(_step()), OutputChannel.web)

    assert payload["steps"] and payload["steps"][0]["kind"] == "youtube_calls"


@pytest.mark.parametrize(("language", "label"), [("it", "altro formato"), ("en", "another format")])
def test_other_format_drops_have_a_label(language, label, capsys) -> None:
    step = _step()
    step.data["searches"][0]["filtered_out"] = {"other_format": 2}

    assert f"{label} (" in _render(step, language, capsys)


@pytest.mark.parametrize(
    ("language", "director", "cast"),
    [("it", "interviste al regista", "interviste al cast"), ("en", "director interviews", "cast interviews")],
)
def test_director_and_cast_interviews_have_distinct_labels(language, director, cast, capsys) -> None:
    step = _step(
        not_searched=[{"kind": "cast_interview", "reason": "turn_limit"}],
        videos=[{"kind": "director_interview", "title": "Nolan on Oppenheimer", "channel": "c", "url": URL1, "notes": []}],
    )

    out = _render(step, language, capsys)

    assert f"[{director}] Nolan on Oppenheimer" in out
    assert f"{'Non cercato' if language == 'it' else 'Not searched'}: {cast}" in out



# --- fix 6: confirmed first, then "to verify", hints ------------------------------------------


def _video(kind: str, title: str, verification: str, notes=()) -> dict:
    return {"kind": kind, "title": title, "channel": "c", "url": URL1, "published_at": "2024-01-01", "notes": list(notes), "verification": verification}


def test_confirmed_videos_come_first_then_to_verify_in_the_order_received(capsys) -> None:
    step = _step(
        videos=[
            _video("director_interview", "A unsure", "to_verify", ["kind_unconfirmed"]),
            _video("director_interview", "B sure", "confirmed"),
            _video("director_interview", "C unsure", "to_verify", ["homonym_unchecked"]),
            _video("cast_interview", "D sure", "confirmed"),
            _video("director_interview", "E sure", "confirmed"),
        ]
    )

    out = _render(step, "it", capsys)

    order = [out.index(name) for name in ("B sure", "E sure", "Da verificare", "A unsure", "C unsure", "D sure")]
    assert order == sorted(order)
    assert "❔ [interviste al regista] Da verificare (categoria o film non confermati):" in out
    assert "[interviste al cast] D sure" in out
    assert out.count("Da verificare") == 1  # the cast kind has nothing to verify


def test_only_confirmed_videos_have_no_to_verify_header(capsys) -> None:
    out = _render(_step(videos=[_video("making_of", "Sure", "confirmed")]), "en", capsys)

    assert "To verify" not in out and "Sure" in out


def test_videos_without_a_label_are_shown_as_before(capsys) -> None:
    # Older traces had no `verification`: they are not hidden.
    out = _render(_step(), "it", capsys)

    assert "Dune: Part Two – “Making of” & more" in out and "Da verificare" not in out


@pytest.mark.parametrize(
    ("language", "year", "original"),
    [
        ("it", "Indica l'anno del film per escludere eventuali omonimi.", "Se il film ha un titolo originale diverso, indicarlo può aiutare."),
        ("en", "Give the film's year to rule out homonyms.", "If the film has a different original title, giving it can help."),
    ],
)
def test_hints_are_shown_in_the_turn_language(language, year, original, capsys) -> None:
    out = _render(_step(hints=["specify_year", "original_title", "unknown_hint"]), language, capsys)

    assert year in out and original in out and "unknown_hint" not in out


def test_categories_not_searched_are_a_short_line_without_the_reason(capsys) -> None:
    out = _render(_step(not_searched=[{"kind": "cast_interview", "reason": "turn_limit"}, {"kind": "making_of", "reason": "x"}]), "it", capsys)

    assert "Non cercato: interviste al cast, making-of" in out and "turn_limit" not in out


def test_the_web_payload_has_no_not_searched_note() -> None:
    from presenters.web.youtube import serialize_youtube_calls_step

    payload = serialize_youtube_calls_step(_step(not_searched=[{"kind": "cast_interview", "reason": "turn_limit"}]), "it")

    assert "not_searched" not in payload and "not_searched" not in payload["labels"]
    assert "cast" not in repr({k: v for k, v in payload.items() if k not in ("groups", "searches", "labels")}).lower()


def test_dropped_titles_are_not_printed(capsys) -> None:
    routes = {
        "/search": {"items": [search_item("vid00000001", "Dune: Part Two | Making of"), search_item("vid00000002", "Dune: Part Two reaction")]},
        "/videos": {"items": [video_item("vid00000001", "Dune: Part Two | Making of")]},
    }
    tool, _ = make_tool(routes)
    result = run_tool(tool)
    [step] = result["trace"]
    assert step["data"]["dropped"]

    render_youtube_calls(TraceStep(**step), "it")

    out = capsys.readouterr().out
    assert "Dune: Part Two | Making of" in out and "Dune: Part Two reaction" not in out
