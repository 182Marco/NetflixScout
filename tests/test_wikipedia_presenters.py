"""Offline tests of the Wikipedia presenters: terminal renderer, web serializer, shared view."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from wikipedia_support import by_mode, article_answer, lookup_answer, make_tool, page, run_tool

from presenters import OutputChannel, present
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.payload import STEP_SERIALIZERS, serialize_step
from presenters.web.wikipedia import serialize_wikipedia_calls_step
from presenters.wikipedia_view import printable, wikipedia_calls_view
from turn import STEP_WIKIPEDIA_CALLS, TraceStep, TurnResult

ROOT = Path(__file__).resolve().parents[1]
URL = "https://it.wikipedia.org/wiki/Park_Chan-wook"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
SEARCH_CALL = "https://it.wikipedia.org/w/api.php?action=query&gsrsearch=%22Park+Chan-wook%22"


def _step(**data) -> TraceStep:
    base = {
        "calls": [{"method": "GET", "url": SEARCH_CALL}, {"method": "GET", "url": SEARCH_CALL}],
        "reused": 0,
        "searches": [
            {"language": "it", "q": '"Park Chan-wook"', "result": "ok", "error": None, "returned": 3, "kept": 2,
             "filtered_out": {"disambiguation": 1}}
        ],
        "opens": [{"language": "it", "title": "Park Chan-wook", "result": "ok", "error": None}],
        "pages": [
            {"title": "Park Chan-wook", "language": "it", "url": URL, "verification": "confirmed", "notes": [],
             "last_revised": "2026-09-30T10:12:00Z", "total_chars": 18420, "delivered_chars": 5230,
             "sections": ["Introduzione", "Biografia", "Carriera"], "omitted": 6},
        ],
        "license": {"name": "CC BY-SA 4.0", "url": LICENSE_URL},
    }
    return TraceStep(kind=STEP_WIKIPEDIA_CALLS, title="Wikipedia", data={**base, **data})


def _turn(step: TraceStep, language: str = "it") -> TurnResult:
    return TurnResult(query="q", language=language, blocked=False, answer="Risposta.", tool="wikipedia_search", steps=[step])


def _render(step: TraceStep, language: str, capsys) -> str:
    present(_turn(step, language), OutputChannel.terminal)
    return capsys.readouterr().out


# --- registration ---------------------------------------------------------------------------


def test_the_step_has_a_renderer_and_a_serializer_and_no_story_line() -> None:
    from presenters.story_view import STORY_STEP_KINDS

    assert STEP_WIKIPEDIA_CALLS in STEP_RENDERERS and STEP_WIKIPEDIA_CALLS in STEP_SERIALIZERS
    assert STEP_WIKIPEDIA_CALLS not in STORY_STEP_KINDS
    assert set(STEP_RENDERERS) == set(STEP_SERIALIZERS)


def test_the_step_is_rendered_with_its_own_block_not_the_generic_fallback(capsys) -> None:
    out = _render(_step(), "it", capsys)

    # The box title is upper-cased by the shared terminal box.
    assert "WIKIPEDIA — 1 PAGINA" in out and "Park Chan-wook" in out
    assert out.index("WIKIPEDIA") < out.index("Risposta.")


# --- content ------------------------------------------------------------------------------------


def test_italian_block_shows_pages_urls_sections_and_the_credit(capsys) -> None:
    out = _render(_step(), "it", capsys)

    assert "Fonte: Wikipedia, testo riformulato e abbreviato, licenza CC BY-SA 4.0" in out
    assert f"[it] Park Chan-wook (5230/18420)" in out and URL in out
    assert "Sezioni lette: Introduzione, Biografia, Carriera" in out and "6 sezioni non lette" in out
    assert f"Licenza: CC BY-SA 4.0 — {LICENSE_URL}" in out
    assert f"Chiamato: GET {SEARCH_CALL}" in out
    assert "3 ricevuti, 2 tenuti; scartati: pagina di disambiguazione 1" in out


def test_english_block(capsys) -> None:
    out = _render(_step(), "en", capsys)

    assert "Source: Wikipedia, text reworded and shortened, CC BY-SA 4.0 licence" in out
    assert "Sections read:" in out and "sections not read" in out and "Licence: CC BY-SA 4.0" in out


def test_a_step_served_by_the_cache_says_so(capsys) -> None:
    out = _render(_step(calls=[], reused=1), "it", capsys)

    assert "Nessuna chiamata a Wikipedia in questo passo: dati già in cache." in out and "Chiamato:" not in out


def test_errors_and_missing_pages_are_shown(capsys) -> None:
    step = _step(
        pages=[],
        searches=[{"language": "it", "q": '"X"', "result": "error", "error": "rate_limited", "returned": 0, "kept": 0, "filtered_out": {}}],
        opens=[{"language": "it", "title": "Y", "result": "not_found", "error": None}],
    )

    out = _render(step, "it", capsys)

    assert "errore: troppe richieste, pausa breve" in out and "Y — pagina non trovata" in out
    assert "Nessuna pagina da mostrare." in out


def test_pages_to_verify_come_after_the_confirmed_ones_under_a_header(capsys) -> None:
    dubious = {"title": "Bong Joon-ho", "language": "it", "url": "https://it.wikipedia.org/wiki/Bong_Joon-ho",
               "verification": "to_verify", "notes": ["title_differs"], "delivered_chars": 100, "sections": ["Introduzione"], "omitted": 0}
    step = _step()
    step.data["pages"] = [dubious, *step.data["pages"]]

    out = _render(step, "it", capsys)

    assert out.index("Park Chan-wook (5230") < out.index("Da verificare (pagina non confermata):") < out.index("Bong Joon-ho (100)")
    assert "note: titolo diverso da quello cercato" in out


@pytest.mark.parametrize(("language", "hint"), [("it", "Indica l'anno del film"), ("en", "Give the film's year")])
def test_hints_are_shown_in_the_turn_language(language, hint, capsys) -> None:
    assert hint in _render(_step(hints=["specify_year"]), language, capsys)


def test_only_https_urls_and_well_formed_rows_are_shown(capsys) -> None:
    step = _step(
        calls=[{"method": "GET", "url": "http://it.wikipedia.org/w/api.php"}, 5, {"method": "GET", "url": SEARCH_CALL}],
        pages=[
            {"title": "Plain http", "language": "it", "url": "http://it.wikipedia.org/wiki/X", "verification": "confirmed"},
            {"title": "javascript", "language": "it", "url": "javascript:alert(1)", "verification": "confirmed"},
            "garbage",
            {"title": "Good", "language": "it", "url": URL, "verification": "confirmed", "sections": "not a list", "omitted": "x"},
        ],
        license={"name": "CC BY-SA 4.0", "url": "http://insecure/"},
    )

    out = _render(step, "it", capsys)

    assert "Plain http" not in out and "javascript" not in out and "http://" not in out
    assert "Good" in out and "Licenza:" not in out


# --- display copy and the key -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "shown"),
    [("A\x1b[31mB", "A[31mB"), ("A\tB\nC", "A B C"), ("A\x00B\x9bC", "ABC"), ("Amélie – 東京", "Amélie – 東京"), (None, "")],
)
def test_control_characters_are_removed_from_the_display_copy(raw, shown) -> None:
    assert printable(raw) == shown


def test_the_terminal_is_clean_but_the_step_is_unchanged(capsys) -> None:
    hostile = "Park\x1b[2J Chan-wook\x07"
    step = _step()
    step.data["pages"][0]["title"] = hostile
    before = copy.deepcopy(step.data)

    out = _render(step, "it", capsys)

    assert "\x1b" not in out and "\x07" not in out and "Park[2J Chan-wook" in out
    assert step.data == before


def test_no_user_agent_or_contact_is_ever_shown(capsys) -> None:
    out = _render(_step(), "it", capsys)

    assert "marcomilza" not in out and "NetflixScout/" not in out


# --- web ----------------------------------------------------------------------------------------


def test_web_serializer_shows_the_same_view_as_the_terminal() -> None:
    step = _step()

    assert serialize_wikipedia_calls_step(step, "it") == {
        "kind": step.kind, **wikipedia_calls_view(step, "it").model_dump(mode="json")
    }


def test_the_web_step_has_the_documented_format() -> None:
    payload = serialize_step(_step(), "it")

    assert payload["kind"] == "wikipedia_calls" and payload["title"] == "WIKIPEDIA — 1 pagina"
    assert payload["source"] == "Fonte: Wikipedia, testo riformulato e abbreviato, licenza CC BY-SA 4.0"
    assert payload["pages"] == [{
        "title": "Park Chan-wook", "language": "it", "url": URL, "verification": "confirmed", "notes": [],
        "sections": ["Introduzione", "Biografia", "Carriera"], "omitted": 6, "chars": "5230/18420",
    }]
    assert payload["license"] == {"name": "CC BY-SA 4.0", "url": LICENSE_URL}
    assert payload["calls"] == [{"method": "GET", "url": SEARCH_CALL}] * 2 and payload["reused"] == 0
    assert json.loads(json.dumps(payload)) == payload  # JSON-ready


def test_web_channel_returns_a_payload_with_the_step_and_no_terminal_decoration() -> None:
    payload = present(_turn(_step()), OutputChannel.web)

    assert [step["kind"] for step in payload["steps"]] == ["wikipedia_calls"]
    assert "═" not in json.dumps(payload) and "📖" not in json.dumps(payload)


def test_a_real_run_of_the_tool_is_presented_by_both_channels(capsys) -> None:
    tool, _ = make_tool(by_mode(lookup=lookup_answer(page("Park Chan-wook", "Regista sudcoreano.")), article=article_answer()))
    (trace,) = run_tool(tool, depth="sections", query="carriera")["trace"]
    step = TraceStep(**trace)

    out = _render(step, "it", capsys)
    web = serialize_step(step, "it")

    assert URL in out and web["pages"][0]["url"] == URL and web["pages"][0]["sections"] == ["Carriera"]
    assert "Regista sudcoreano" not in out and "Regista sudcoreano" not in json.dumps(web)


# --- isolation ----------------------------------------------------------------------------------


def test_wikipedia_presenters_import_only_turn_and_their_own_modules() -> None:
    paths = [ROOT / "presenters" / "wikipedia_view.py"]
    paths += sorted((ROOT / "presenters" / "terminal" / "wikipedia").rglob("*.py"))
    paths += sorted((ROOT / "presenters" / "web" / "wikipedia").rglob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module in {"__future__", "typing", "pydantic", "turn"}, (path, node.module)
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                assert node.module in {"box", "wikipedia_view"}, (path, node.module)
            if isinstance(node, ast.Import):
                raise AssertionError((path, [alias.name for alias in node.names]))


def test_presenters_never_import_the_wikipedia_package() -> None:
    for path in sorted((ROOT / "presenters").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert not node.module.startswith("tool"), (path, node.module)


def test_the_wikipedia_package_never_imports_the_presenters() -> None:
    for path in sorted((ROOT / "tool" / "wikipedia").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert not node.module.startswith(("presenters", "web_api", "web_lists", "tool")), (path, node.module)


def test_there_is_no_print_in_the_wikipedia_package_or_the_web_presenter() -> None:
    # The live smoke script (tool/wikipedia/harness/) is a manual tool that prints on purpose.
    paths = [p for p in sorted((ROOT / "tool" / "wikipedia").rglob("*.py")) if "harness" not in p.parts]
    paths += sorted((ROOT / "presenters" / "web" / "wikipedia").rglob("*.py"))
    paths.append(ROOT / "presenters" / "wikipedia_view.py")
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                raise AssertionError(path)


def test_presenters_exist_for_both_channels() -> None:
    for channel in ("terminal", "web"):
        assert (ROOT / "presenters" / channel / "wikipedia" / "__init__.py").is_file()
