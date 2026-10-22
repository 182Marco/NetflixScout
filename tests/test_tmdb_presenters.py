from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from tmdb_support import BASE, MOVIE_ID, make_tool, movie_payload, providers_payload, run

from presenters import OutputChannel, present
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.api_view import TMDB_NOTICE
from presenters.terminal import print_tmdb_notice
from presenters.web.api import serialize_tmdb_calls_step
from turn import STEP_TMDB_CALLS, TraceStep, TurnResult

ROOT = Path(__file__).resolve().parents[1]
URL = f"{BASE}/movie/{MOVIE_ID}?api_key=***"


def _step(calls=(URL,), attributions=()) -> TraceStep:
    return TraceStep(kind=STEP_TMDB_CALLS, title="TMDb", data={"calls": list(calls), "attributions": list(attributions)})


def _turn(step: TraceStep, language: str = "it") -> TurnResult:
    return TurnResult(query="q", language=language, blocked=False, answer="Risposta.", tool="tmdb_search", steps=[step])


@pytest.mark.parametrize(("language", "label"), [("it", "Chiamato"), ("en", "Called")])
def test_terminal_shows_only_called_urls_in_the_turn_language(language, label, capsys) -> None:
    assert STEP_TMDB_CALLS in STEP_RENDERERS

    present(_turn(_step(), language), OutputChannel.terminal)

    out = capsys.readouterr().out
    assert f"{label}: {URL}" in out
    assert out.index(URL) < out.index("Risposta.")
    assert "JustWatch" not in out


def test_other_languages_get_english_labels() -> None:
    # The turn language is "it" or "en"; a German question is classified "en".
    assert serialize_tmdb_calls_step(_step(), "de")["calls"][0]["label"] == "Called"


def test_justwatch_attribution_is_shown_by_both_channels(capsys) -> None:
    step = _step(attributions=["justwatch"])

    present(_turn(step), OutputChannel.terminal)
    payload = serialize_tmdb_calls_step(step, "it")

    assert "Dati sulla disponibilità in streaming: JustWatch" in capsys.readouterr().out
    assert payload["attributions"] == [{"source": "JustWatch", "text": "Dati sulla disponibilità in streaming: JustWatch"}]


def test_cached_turn_still_credits_justwatch(capsys) -> None:
    present(_turn(_step(calls=(), attributions=["justwatch"]), "en"), OutputChannel.terminal)

    out = capsys.readouterr().out
    assert "No TMDb call in this turn" in out and "Streaming availability data: JustWatch" in out


def test_web_serializer_matches_terminal_and_is_json_ready(capsys) -> None:
    step = _step(calls=(URL, f"{BASE}/search/movie?api_key=***"))

    payload = serialize_tmdb_calls_step(step, "it")
    present(_turn(step), OutputChannel.terminal)
    out = capsys.readouterr().out

    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) == {"kind", "title", "calls", "attributions", "notice"}
    assert all(f"Chiamato: {call['url']}" in out for call in payload["calls"])
    assert payload["notice"] == TMDB_NOTICE


def test_presenters_never_show_parameters_or_raw_json(capsys) -> None:
    step = _step(calls=(URL, "javascript:alert(1)", {"sql": "x"}))
    step.data["raw"] = {"api_key": "x", "results": [1, 2]}

    present(_turn(step), OutputChannel.terminal)
    out = capsys.readouterr().out

    assert "javascript" not in out and "results" not in out and "language=" not in out
    assert serialize_tmdb_calls_step(step)["calls"] == [{"label": "Called", "url": URL}]


def test_end_to_end_step_from_the_tool_with_providers(capsys) -> None:
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": movie_payload(**{"watch/providers": providers_payload()})})
    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID, "facets": ["watch_providers"]}, language="it")

    present(_turn(TraceStep(**result["trace"][0])), OutputChannel.terminal)

    out = capsys.readouterr().out
    assert f"Chiamato: {URL}" in out and "JustWatch" in out
    assert "append_to_response" not in out and "it-IT" not in out


def test_startup_notice_uses_the_terms_wording(capsys) -> None:
    print_tmdb_notice()

    assert "uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB" in capsys.readouterr().out


def test_tmdb_presenters_import_only_turn_and_their_own_view() -> None:
    paths = [ROOT / "presenters" / "api_view.py"]
    for channel in ("terminal", "web"):
        paths += sorted((ROOT / "presenters" / channel / "api").rglob("*.py"))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module in {"__future__", "typing", "pydantic", "turn"}, (path, node.module)
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                assert (node.module or "") in {"api_view", "box"}, (path, node.module)


def test_presenters_never_import_the_tmdb_package() -> None:
    for path in sorted((ROOT / "presenters").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert not node.module.startswith("tmdb"), (path, node.module)


def test_presenters_live_only_in_the_root_folder_split_by_channel_and_tool() -> None:
    stray = [
        path.relative_to(ROOT)
        for path in ROOT.rglob("presenters")
        if path.is_dir() and path != ROOT / "presenters" and ".venv" not in path.parts
    ]
    assert not stray
    for channel in ("terminal", "web"):
        for tool in ("rag", "db", "api", "youtube"):
            assert (ROOT / "presenters" / channel / tool / "__init__.py").is_file(), (channel, tool)


def test_web_channel_is_still_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        present(_turn(_step()), OutputChannel.web)
