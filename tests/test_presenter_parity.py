"""Terminal and web must tell the same story and show the same data; only the format differs."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from presenters import OutputChannel, present
from presenters.story_view import STORY_STEP_KINDS, build_story
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.payload import STEP_SERIALIZERS, to_payload
from turn import TraceStep, TurnResult

ROOT = Path(__file__).resolve().parents[1]
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⏳═-╿]")

CHUNK = {"id": "c1", "testo": "trama", "score": 0.9, "title": "Matrix", "release_year": "1999", "genres": "Sci-Fi"}
YOUTUBE_STEP = TraceStep(
    kind="youtube_calls",
    title="YouTube",
    data={
        "calls": ["https://www.googleapis.com/youtube/v3/search?key=***"],
        "searches": [{"kind": "director_interview", "q": "Dune director", "returned": 3, "kept": 1, "filtered_out": {"no_anchor": 2}}],
        "not_searched": [],
        "videos": [{"kind": "director_interview", "title": "Intervista", "channel": "Canale", "url": "https://www.youtube.com/watch?v=abcdefghijk", "published_at": "2024-01-01T00:00:00Z", "notes": [], "verification": "confirmed"}],
        "hints": ["specify_year"],
    },
)
STEPS = [
    TraceStep(kind="classification", title="x", data={"is_cinema": True, "language": "it"}),
    TraceStep(kind="query_rewrite", title="x", data={"original": "e il regista?", "used": "regista di Dune", "rewritten": True}),
    TraceStep(kind="tool_selection", title="x", data={"tool": "rag_search", "purpose": "film con robot"}),
    TraceStep(kind="tool_outcome", title="x", data={"tool": "rag_search", "status": "ok", "reason": None, "elapsed_ms": 1500}),
    TraceStep(kind="retrieval", title="x", data={"embedded_text": "robots", "signals": {"genres": ["Sci-Fi"]}, "chunks": [CHUNK]}),
    TraceStep(kind="rerank", title="x", data={"chunks": [CHUNK]}),
    TraceStep(kind="tool_selection", title="x", data={"tool": "movie_db_search", "purpose": "voti"}),
    TraceStep(kind="tool_outcome", title="x", data={"tool": "movie_db_search", "status": "error", "reason": "unsupported_request", "elapsed_ms": 100}),
    TraceStep(kind="db_query", title="Database", data={"queries": [{"sql": "SELECT ? ", "params": [1]}]}),
    TraceStep(kind="tmdb_calls", title="TMDb", data={"calls": ["https://api.themoviedb.org/3/movie/1?api_key=***"], "attributions": ["justwatch"]}),
    YOUTUBE_STEP,
    TraceStep(kind="planning", title="x", data={"fallbacks": ["answer_failed"], "pending": []}),
]


def _turn(language: str = "it") -> TurnResult:
    return TurnResult(query="q", language=language, blocked=False, answer="Risposta.", tool="rag_search", steps=STEPS)


def test_both_channels_know_the_same_tool_steps() -> None:
    assert set(STEP_RENDERERS) == set(STEP_SERIALIZERS)
    assert not set(STEP_RENDERERS) & STORY_STEP_KINDS


def test_the_terminal_prints_the_story_lines_the_web_sends(capsys) -> None:
    present(_turn(), OutputChannel.terminal)
    out = capsys.readouterr().out
    story = to_payload(_turn())["story"]

    assert story and all(line["text"] in out for line in story)


def test_live_and_replay_print_the_same_steps(capsys) -> None:
    from presenters.terminal import TerminalObserver

    observer = TerminalObserver()
    for step in STEPS:
        observer.step(step)
    live = capsys.readouterr().out
    present(_turn(), OutputChannel.terminal)
    replay = capsys.readouterr().out
    present(_turn(), OutputChannel.terminal, streamed=True)
    streamed_end = capsys.readouterr().out

    assert live and replay.startswith(live) and "Risposta." in replay
    assert streamed_end.count("Risposta.") == 1 and "Matrix" not in streamed_end  # steps not printed twice


@pytest.mark.parametrize("language", ["it", "en"])
def test_the_web_payload_has_no_terminal_decoration(language) -> None:
    payload = to_payload(_turn(language))

    assert not EMOJI.search(repr(payload["story"])) and "═" not in repr(payload)
    assert [line["level"] for line in payload["story"]] == [line.level for line in build_story(STEPS, language)]


def test_every_step_has_its_web_form_with_the_data_the_terminal_shows() -> None:
    steps = {step["kind"]: step for step in to_payload(_turn())["steps"]}

    assert set(steps) == {"retrieval", "rerank", "db_query", "tmdb_calls", "youtube_calls"}
    assert steps["retrieval"]["embedded_text"] == "robots" and steps["retrieval"]["chunks"][0]["title"] == "Matrix"
    assert steps["rerank"]["chunks"][0]["year"] == "1999"
    assert steps["db_query"]["queries"][0]["display_sql"] == "SELECT 1 "
    assert steps["tmdb_calls"]["attributions"][0]["source"] == "JustWatch" and steps["tmdb_calls"]["notice"]
    video = steps["youtube_calls"]["groups"][0]["confirmed"][0]
    assert video["url"] == "https://www.youtube.com/watch?v=abcdefghijk" and video["channel"] == "Canale"
    assert steps["youtube_calls"]["notice"] and steps["youtube_calls"]["source"]


def test_an_unknown_step_is_passed_on_in_both_channels(capsys) -> None:
    turn = TurnResult(
        query="q", language="it", blocked=False, answer="r",
        steps=[TraceStep(kind="future", title="Nuovo", data={"a": 1})],
    )

    present(turn, OutputChannel.terminal)

    assert "NUOVO" in capsys.readouterr().out
    assert to_payload(turn)["steps"] == [{"kind": "future", "title": "Nuovo", "data": {"a": 1}}]


def test_the_story_of_a_real_turn_equals_the_story_rebuilt_from_its_steps(monkeypatch) -> None:
    import app as app_module
    from turn_support import stream_decision

    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": False})

    class _Orchestrator:
        def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None):
            decision = {
                "tool": "tmdb_search",
                "tools": ["tmdb_search"],
                "calls": [{"tool": "tmdb_search", "arguments": {}, "result": {"outcome": {"status": "empty", "reason": None}, "trace": []}}],
                "standalone_query": query,
                "result": {"trace": []},
                "final_answer": "Nothing found.",
            }
            stream_decision(observer, query, decision)
            return decision

    seen = []

    class _Observer:
        def step(self, step) -> None:
            seen.append(step.kind)

        def status(self, stage) -> None:
            seen.append(f"status:{stage}")

    app = {"config": app_module.build_runtime_config(), "orchestrator": _Orchestrator()}
    turn = app_module.handle_query(app, "Who directed Dune?", history=[], observer=_Observer())

    assert turn.story == build_story(turn.steps)
    assert [line.text for line in turn.story] == ["Searching on TMDb: Who directed Dune?", "TMDb: no results, under 1 s"]
    assert seen[0] == "status:understanding" and seen[1] == "classification"
    assert [s for s in seen if not s.startswith("status")] == [s.kind for s in turn.steps]
