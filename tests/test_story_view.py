from __future__ import annotations

import ast
from pathlib import Path

import pytest

from presenters.story_view import MAX_OK_LINES, StoryBuilder, build_story
from turn import TraceStep

ROOT = Path(__file__).resolve().parents[1]


def _selection(tool="tmdb_search", purpose="cast di Parasite") -> TraceStep:
    return TraceStep(kind="tool_selection", title="x", data={"tool": tool, "purpose": purpose, "arguments": {}})


def _outcome(tool="tmdb_search", status="ok", reason=None, elapsed_ms=2400) -> TraceStep:
    return TraceStep(
        kind="tool_outcome", title="x", data={"tool": tool, "status": status, "reason": reason, "elapsed_ms": elapsed_ms}
    )


def _texts(steps, language="it") -> list[str]:
    return [line.text for line in build_story(steps, language)]


def test_a_search_tells_what_where_and_how_it_went() -> None:
    assert _texts([_selection(), _outcome()]) == ["Cerco su TMDb: cast di Parasite", "TMDb: trovato, 2 s"]


def test_english() -> None:
    assert _texts([_selection(), _outcome()], "en") == ["Searching on TMDb: cast di Parasite", "TMDb: found, 2 s"]


def test_the_language_comes_from_the_classification_step() -> None:
    classification = TraceStep(kind="classification", title="x", data={"language": "en"})

    assert _texts([classification, _selection("youtube_search", "interviews")]) == ["Searching on YouTube: interviews"]


def test_empty_and_failed_runs_are_warnings_in_plain_words() -> None:
    lines = build_story([_outcome(status="empty", elapsed_ms=300), _outcome("movie_db_search", "error", "unsupported_request")])

    assert [(line.level, line.text) for line in lines] == [
        ("warn", "TMDb: nessun risultato, meno di 1 s"),
        ("warn", "Voti: questa richiesta non si può cercare qui, 2 s"),
    ]


def test_an_unknown_error_code_and_an_unknown_tool_stay_readable() -> None:
    lines = build_story([_selection("future_tool", "x"), _outcome("future_tool", "error", "weird_code")])

    assert lines[0].text == "Cerco future_tool: x"
    assert lines[1].text == "future_tool: non è andata a buon fine, 2 s"


def test_in_a_long_turn_only_the_first_found_lines_are_kept_but_problems_always_show() -> None:
    steps = [_outcome() for _ in range(MAX_OK_LINES + 3)] + [_outcome(status="empty")]

    lines = build_story(steps)

    assert [line.level for line in lines].count("ok") == MAX_OK_LINES and lines[-1].level == "warn"


def test_a_rewritten_query_is_told_and_an_unchanged_one_is_not() -> None:
    rewritten = TraceStep(kind="query_rewrite", title="x", data={"original": "e il regista?", "used": "regista di Dune", "rewritten": True})
    same = TraceStep(kind="query_rewrite", title="x", data={"original": "a", "used": "a", "rewritten": False})

    assert _texts([rewritten]) == ["Ho inteso la domanda così: regista di Dune"] and _texts([same]) == []


def test_fallbacks_and_unsearched_parts_are_warnings() -> None:
    planning = TraceStep(
        kind="planning",
        title="x",
        data={"fallbacks": ["planner_failed", "planner_failed", "answer_failed"], "pending": [{"part": "un'intervista", "tool": "youtube_search"}]},
    )

    lines = build_story([planning])

    assert [line.level for line in lines] == ["warn"] * 3
    assert lines[0].text.startswith("Non ho capito bene come cercare")
    assert lines[2].text == "Non ho cercato: un'intervista"


def test_clarification_and_stages() -> None:
    clarification = TraceStep(kind="tool_selection", title="x", data={"tool": None, "clarification": True})

    assert _texts([clarification]) == ["Mi serve un chiarimento prima di cercare."]
    assert [line.text for line in StoryBuilder("en").status("answering")] == ["Writing the answer…"]
    assert StoryBuilder().status("unknown_stage") == []


def test_steps_without_a_story_are_ignored() -> None:
    assert _texts([TraceStep(kind="retrieval", title="x", data={})]) == []


def test_story_view_imports_only_turn() -> None:
    tree = ast.parse((ROOT / "presenters" / "story_view.py").read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert modules == {"__future__", "turn"}
