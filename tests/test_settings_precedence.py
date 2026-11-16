"""Settings PREVAIL over an explicit request: the guard on the tools, the planner's declared conflicts, the fixed first sentence."""
from __future__ import annotations

import json

from preferences import SettingsPolicy, defaults, resolve_preferences
from preferences.policy import TMDB_FILM_OPERATIONS, TMDB_SERIES_OPERATIONS
from stream_support import reply

from orchestrator import LLMOrchestrator
from tool.tmdb.models.enums import TmdbOperation


def policy(**values) -> SettingsPolicy:
    return SettingsPolicy(resolve_preferences(values).preferences)


# ---- the deterministic guard
def test_series_forbids_the_film_tools_and_film_operations():
    p = policy(content_type="series")
    assert p.check_step("rag_search", {"query": "x"}).arguments is None
    assert p.check_step("tvmaze_search", {"title": "x"}).arguments == {"title": "x"}
    only_film = {"requests": [{"operation": "discover_movies"}, {"operation": "search", "kind": "movie", "search_query": "x"}]}
    assert p.check_step("tmdb_search", only_film).arguments is None
    mixed = {"requests": [{"operation": "movie_details", "title": "x"}, {"operation": "tv_details", "title": "y"}]}
    v = p.check_step("tmdb_search", mixed)
    assert v.changed and v.arguments["requests"] == [{"operation": "tv_details", "title": "y"}] and v.setting == "content_type"


def test_film_forbids_the_series_tools_and_operations():
    p = policy(content_type="film")
    assert p.check_step("tvmaze_search", {"title": "x"}).arguments is None
    assert p.check_step("rag_search", {"query": "x"}).arguments == {"query": "x"}
    assert p.check_step("tmdb_search", {"requests": [{"operation": "discover_tv"}]}).arguments is None
    assert p.check_step("tmdb_search", {"requests": [{"operation": "chart", "media": "tv", "chart": "popular"}]}).arguments is None


def test_both_forbids_nothing():
    p = policy(content_type="both")
    for tool in ("rag_search", "tvmaze_search"):
        assert p.check_step(tool, {"a": 1}).arguments == {"a": 1}


def test_the_operation_names_are_the_real_ones():
    names = {o.value for o in TmdbOperation}
    assert TMDB_FILM_OPERATIONS <= names and TMDB_SERIES_OPERATIONS <= names


def test_the_conflict_sentence_names_the_setting_and_follows_the_language():
    p = policy(content_type="series")
    it = p.conflict_sentence([{"setting": "content_type", "requested": "un film"}], "it")
    assert "«Serie»" in it and "prevale" in it and "non cerco film" in it
    assert "prevails" in p.conflict_sentence([{"setting": "content_type"}], "fr")           # any other language reads English
    assert "Vorrang" in p.conflict_sentence([{"setting": "response_length"}], "de")
    assert p.conflict_sentence([{"setting": "unknown"}], "it") == ""
    assert policy().conflict_sentence([{"setting": "spoiler_plot"}], "it").startswith("Hai disattivato gli spoiler")


# ---- the orchestrator
class Client:
    def __init__(self, plans: list[dict]):
        self.plans, self.calls, self.responses = list(plans), [], self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return reply("Ecco le serie.", kwargs)
        return reply(json.dumps(self.plans.pop(0) if self.plans else {"done": True}), kwargs)


class Tool:
    def __init__(self, name):
        self.name, self.description, self.input_schema, self.ran = name, "fake", {}, []

    def run(self, *, query, params=None, conversation_history=None):
        self.ran.append(params)
        return {"query": query, "chunks": [{"title": "X"}], "metadata": {}, "trace": []}


def orchestrator(client, *names):
    tools = [Tool(n) for n in names]
    cfg = {"orchestrator": {"fallback_tool": names[0], "final_instructions": "BASE", "allowed_tools": list(names)}}
    return LLMOrchestrator(config=cfg, tools=tools, client=client), {t.name: t for t in tools}


def run(client, orch, **kw):
    return orch.run(query="consigliami un film horror", conversation_history=[], settings_policy=policy(content_type="series"), answer_language="it", **kw)


def plan(tool, conflicts=None, **extra):
    return {"standalone_query": "q", "tool_name": tool, "arguments": extra.get("arguments", {}), "confidence": 0.9, "conflicts": conflicts or []}


def test_a_forbidden_first_step_never_runs_and_the_planner_is_asked_again():
    conflict = [{"setting": "content_type", "requested": "un film"}]
    client = Client([plan("rag_search", conflict), plan("tmdb_search", conflict, arguments={"requests": [{"operation": "discover_tv"}]})])
    orch, tools = orchestrator(client, "rag_search", "tmdb_search")
    out = run(client, orch)

    assert tools["rag_search"].ran == [] and len(tools["tmdb_search"].ran) == 1
    assert out["final_answer"].startswith("Il tipo di contenuto è impostato su «Serie»")
    assert "prevale" in out["final_answer"].split("\n")[0] and "Ecco le serie." in out["final_answer"]
    assert "blocked_by_setting" in out["planning"]["fallbacks"] and out["settings_conflicts"][0]["setting"] == "content_type"


def test_when_nothing_is_compatible_no_tool_and_no_answer_call():
    client = Client([{"standalone_query": "q", "tool_name": None, "conflicts": [{"setting": "spoiler_plot", "requested": "il finale"}]}])
    orch, tools = orchestrator(client, "tmdb_search")
    out = orch.run(query="come finisce Se7en?", conversation_history=[], settings_policy=policy(), answer_language="it")

    assert out["tool"] is None and tools["tmdb_search"].ran == []
    assert out["final_answer"].startswith("Hai disattivato gli spoiler") and "Non eseguo la parte in conflitto" in out["final_answer"]
    assert len(client.calls) == 1                                    # only the planner


def test_a_declared_conflict_with_a_compatible_part_opens_the_answer_with_the_fixed_sentence():
    client = Client([plan("tmdb_search", [{"setting": "response_length", "requested": "una riga"}])])
    orch, _ = orchestrator(client, "tmdb_search")
    seen: list[str] = []

    class Obs:
        def step(self, s): pass
        def status(self, s): pass
        def answer_delta(self, t): seen.append(t)

    out = orch.run(query="dimmi tutto in una riga", conversation_history=[], settings_policy=policy(response_length="medium"), answer_language="it", observer=Obs())
    first = out["final_answer"].split("\n")[0]
    assert first.startswith("La lunghezza della risposta è impostata su «Media»") and "Ecco le serie." in out["final_answer"]
    assert "".join(seen).startswith(first)                           # the sentence is what the user sees first


def test_without_a_policy_nothing_changes():
    client = Client([plan("tmdb_search", [{"setting": "content_type"}])])
    orch, tools = orchestrator(client, "tmdb_search")
    out = orch.run(query="q", conversation_history=[])
    assert len(tools["tmdb_search"].ran) == 1 and out["final_answer"] == "Ecco le serie." and out["settings_conflicts"] == []
