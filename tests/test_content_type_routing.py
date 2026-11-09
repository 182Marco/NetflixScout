"""Film / Serie / Entrambi (`content_type`) from the web request to the planner and to the tools. SIMULATED: no planner model runs; this proves what the code does with
each value (wiring, prompt text, deterministic guard), not what the real planner chooses (that is the live routing evaluation)."""
from __future__ import annotations

import json

import pytest

from preferences import SettingsPolicy, build_prompt_parts, resolve_preferences

VALUES = ("film", "series", "both")


def _prefs(value):
    return resolve_preferences({"content_type": value}).preferences


def test_the_three_values_are_accepted_and_both_is_the_default():
    for v in VALUES:
        r = resolve_preferences({"content_type": v})
        assert r.preferences["content_type"] == v and not r.ignored
    assert resolve_preferences({}).preferences["content_type"] == "both"
    r = resolve_preferences({"content_type": "movies"})  # a wrong value falls back to the default, the request never fails
    assert r.preferences["content_type"] == "both" and "content_type" in r.ignored


def test_the_planner_prompt_carries_the_choice_and_both_adds_no_constraint():
    film, series, both = (build_prompt_parts(_prefs(v))["planner"] for v in VALUES)
    assert "film (vincolante)" in film and "serie TV (vincolante)" in series
    assert "vincolante" not in both.split("Fonti preferite")[0] and "mai per prudenza" in both and "SOLO se" in both
    assert "VIETATI: rag_search" in series and "VIETATI: series_rag_search" in film
    assert "movie_db_search" not in film + series + both  # not registered in the integrated runtime
    assert "tvmaze_search" in film and "tvmaze_search" in series and "tvmaze_search" in both


@pytest.mark.parametrize("tool,args,film,series", [
    ("rag_search", {"query": "x"}, True, False),
    ("series_rag_search", {"query": "x"}, False, True),
    ("tvmaze_search", {"title": "x"}, False, True),
    ("tmdb_search", {"requests": [{"operation": "movie_details", "title": "x"}]}, True, False),
    ("tmdb_search", {"requests": [{"operation": "tv_details", "title": "x"}]}, False, True),
    ("cinema_sql", {"operation": "movielens", "ml_mode": "top_rated"}, True, False),
    ("cinema_sql", {"operation": "series", "title": "x"}, False, True),
    ("cinema_sql", {"operation": "filmography", "title": "x"}, True, True),
    ("omdb_search", {"title": "x"}, True, True),
    ("wikipedia_search", {"topic": "x"}, True, True),
])
def test_the_guard_decides_per_tool_for_each_value(tool, args, film, series):
    for value, allowed in (("film", film), ("series", series), ("both", True)):
        verdict = SettingsPolicy(_prefs(value)).check_step(tool, dict(args))
        assert (verdict.arguments is not None) is allowed, (tool, value)


def test_cinema_sql_gets_the_preferred_type_when_the_planner_gives_none():
    for value, wanted in (("film", "film"), ("series", "series")):
        v = SettingsPolicy(_prefs(value)).check_step("cinema_sql", {"operation": "cast", "title": "x"})
        assert v.arguments["type"] == wanted
    assert "type" not in SettingsPolicy(_prefs("both")).check_step("cinema_sql", {"operation": "cast", "title": "x"}).arguments


# ---- FASE 18B: an explicit request for the OTHER kind is a conflict BEFORE any search; symmetric; `both` is untouched
def test_the_planner_is_told_that_an_explicit_request_of_the_other_kind_has_nothing_compatible():
    from preferences import behavior
    intro = behavior.PLANNER_INTRO
    assert "ECCEZIONE per content_type" in intro and "tool_name null" in intro and "NON reinterpretare" in intro and "nemmeno rag_search o series_rag_search" in intro
    assert "mescola i due tipi" in intro  # a mixed request still gets its compatible part
    film, series, both = (behavior.CONTENT_PLANNER[v] for v in ("film", "series", "both"))
    assert "nessuna ricerca, nemmeno di film simili alla serie citata" in film and "nessuna reinterpretazione come richiesta di film" in film
    assert "nessuna ricerca, nemmeno di serie simili al film citato" in series and "nessuna reinterpretazione come richiesta di serie" in series
    assert "conflict" not in both.lower() and "VIETATI" not in both


@pytest.mark.parametrize("language,film_phrase,series_phrase,ask", [
    ("it", "non cerco serie TV", "non cerco film", "cambia il tipo di contenuto nelle impostazioni"),
    ("en", "I do not look for TV series", "I do not look for films", "change the content type in the settings"),
    ("de", "keine Serien", "keine Filme", "Ändere dafür den Inhaltstyp in den Einstellungen"),
])
def test_the_conflict_sentence_names_the_active_setting_and_asks_to_change_it_in_every_language(language, film_phrase, series_phrase, ask):
    conflict = [{"setting": "content_type", "requested": "x"}]
    film = SettingsPolicy(_prefs("film")).conflict_sentence(conflict, language)
    series = SettingsPolicy(_prefs("series")).conflict_sentence(conflict, language)
    assert film_phrase in film and ask in film and series_phrase in series and ask in series
    assert SettingsPolicy(_prefs("both")).conflict_sentence([], language) == ""


class _Planner:
    def __init__(self, plans):
        self.plans, self.responses, self.calls = list(plans), self, []

    def create(self, **kw):
        from stream_support import reply
        self.calls.append(kw)
        return reply(json.dumps(self.plans.pop(0) if self.plans else {"done": True}), kw)


class _Stub:
    def __init__(self, name):
        self.name, self.description, self.input_schema, self.ran = name, "x", {}, []

    def run(self, *, query, params=None, conversation_history=None):
        self.ran.append(params)
        return {"query": query, "chunks": [{"title": "X"}], "metadata": {}, "trace": []}


def _turn(value, plans):
    from orchestrator import LLMOrchestrator
    tools = [_Stub(n) for n in ("rag_search", "series_rag_search", "tvmaze_search", "cinema_sql")]
    cfg = {"orchestrator": {"fallback_tool": "rag_search", "final_instructions": "B", "allowed_tools": [t.name for t in tools]}}
    client = _Planner(plans)
    out = LLMOrchestrator(config=cfg, tools=tools, client=client).run(
        query="q", conversation_history=[], prompt_parts=build_prompt_parts(_prefs(value)), settings_policy=SettingsPolicy(_prefs(value)), answer_language="it")
    return out, {t.name: t for t in tools}, client


CONFLICT = [{"setting": "content_type", "requested": "l'altro tipo"}]
NO_TOOL = {"standalone_query": "q", "tool_name": None, "arguments": {}, "confidence": 0.9, "conflicts": CONFLICT}


@pytest.mark.parametrize("value,wrong_tool", [("film", "series_rag_search"), ("film", "tvmaze_search"), ("series", "rag_search")])
def test_a_conflict_only_plan_runs_no_tool_and_asks_to_change_the_setting(value, wrong_tool):
    out, tools, client = _turn(value, [NO_TOOL])
    assert out["tools"] == [] and all(not t.ran for t in tools.values()) and len(client.calls) == 1  # one planner call, no answer call
    assert "cambia il tipo di contenuto nelle impostazioni" in out["final_answer"] and out["settings_conflicts"]


@pytest.mark.parametrize("value,wrong_tool", [("film", "series_rag_search"), ("film", "tvmaze_search"), ("series", "rag_search")])
def test_if_the_planner_proposes_the_excluded_tool_anyway_the_guard_stops_it(value, wrong_tool):
    plan = {"standalone_query": "q", "tool_name": wrong_tool, "arguments": {"query": "x"}, "confidence": 0.9, "conflicts": CONFLICT}
    out, tools, _ = _turn(value, [plan, NO_TOOL])
    assert not tools[wrong_tool].ran and out["tools"] == []


def test_both_runs_either_rag_without_any_conflict():
    plan = {"standalone_query": "q", "tool_name": "series_rag_search", "arguments": {"query": "x"}, "confidence": 0.9}
    out, tools, _ = _turn("both", [plan])
    assert tools["series_rag_search"].ran and not out["settings_conflicts"] and "cambia il tipo" not in out["final_answer"]
