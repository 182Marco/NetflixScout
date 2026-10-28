"""Offline tests of the OMDb integration: registration, routing rule text, how the `reviews` source
reaches the planner, per-tool final rules and the whole turn with fake clients.

These check wiring and prompt *text*: they are not evidence of what the real planner chooses. That is
measured only by the live routing and E2E evaluations, which need a separate authorization.
"""
from __future__ import annotations

import json

from omdb_support import by_endpoint, make_tool, record
from stream_support import reply

import app as app_module
from orchestrator import LLMOrchestrator
from preferences import build_prompt_parts, defaults, resolve_preferences
from preferences import behavior
from presenters import OutputChannel, present
from tool.omdb.tool import OMDB_TOOL_NAME, OmdbTool
from turn import STEP_OMDB_CALLS

INSTRUCTIONS = app_module.CONFIG["orchestrator"]["instructions"]
RULES = app_module.CONFIG["orchestrator"]["tool_final_instructions"]
ID = "tt1000001"


def _rule(label: str, next_label: str) -> str:
    start = INSTRUCTIONS.index(f"{label}) ")
    return INSTRUCTIONS[start : INSTRUCTIONS.index(f"{next_label}) ", start)]


class FakeClient:
    """Planning call -> `plan`; final answer otherwise. Keeps every request."""

    def __init__(self, plan: dict) -> None:
        self.outputs = [json.dumps(plan), "Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.outputs.pop(0), kwargs)


class _Other:
    """A tool that is not OMDb: any call to OMDb would show in the transport."""

    name = "tmdb_search"
    description = "TMDb"
    input_schema = {"type": "object"}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [], "metadata": {}, "trace": []}


# --- registration -----------------------------------------------------------------------------


def test_build_app_registers_omdb_from_the_omdb_config(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    orchestrator = app_module.build_app({"omdb": {"max_calls_per_turn": 3}})["orchestrator"]
    tool = orchestrator.tools[OMDB_TOOL_NAME]

    assert isinstance(tool, OmdbTool) and tool.config.max_calls_per_turn == 3
    assert tool.credentials is None  # `.env` is read on first use, not at build time
    assert set(orchestrator.enrichers) == {"rag_search"}  # no enricher: OMDb is never added to a turn on its own
    assert app_module.CONFIG["orchestrator"]["fallback_tool"] == "rag_search"


def test_omdb_is_allowed_and_in_the_planner_catalog(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    orchestrator = app_module.build_app()["orchestrator"]

    assert OMDB_TOOL_NAME in app_module.CONFIG["orchestrator"]["allowed_tools"]
    catalog = orchestrator._catalog_text(orchestrator._allowed_tool_names())
    assert '"name":"omdb_search"' in catalog and "imdb_id" in catalog
    for existing in ("rag_search", "movie_db_search", "tmdb_search", "youtube_search", "wikipedia_search"):
        assert existing in orchestrator._allowed_tool_names()


# --- routing rule text ---------------------------------------------------------------------------


def test_rule_1d_sits_after_1c_and_before_movie_db_and_leaves_the_others_alone() -> None:
    assert INSTRUCTIONS.index("1c) wikipedia_search") < INSTRUCTIONS.index("1d) omdb_search") < INSTRUCTIONS.index("2) movie_db_search")
    assert _rule("1b", "1c").startswith("1b) youtube_search") and _rule("2", "3").startswith("2) movie_db_search")
    assert _rule("3", "4").startswith("3) rag_search") and "omdb" not in _rule("3", "4")


def test_rule_1d_puts_omdb_first_only_with_the_reviews_preference_and_a_critic_request() -> None:
    rule = _rule("1d", "2")

    assert "prima di tmdb_search" in rule and "esplicitamente il giudizio o i punteggi della critica" in rule
    assert "le preferenze dell'utente indicano le recensioni come fonte preferita" in rule
    # Without the preference a generic critic question keeps its old route; naming a score forces OMDb.
    assert "Senza quella preferenza una domanda generica sulla critica segue le regole 1 e 2" in rule
    assert "nomini esplicitamente il Metascore, Rotten Tomatoes o il voto IMDb" in rule


def test_rule_1d_keeps_omdb_out_of_requests_it_cannot_serve_or_already_served() -> None:
    rule = _rule("1d", "2")

    for excluded in ("classifiche o elenchi", "cast, trama, streaming", "testi di recensioni", "voti degli utenti di MovieLens e TMDb"):
        assert excluded in rule
    assert "già nei risultati dei passi precedenti del turno" in rule


def test_rule_1d_never_lets_the_planner_invent_an_id_or_spend_a_tmdb_call_for_it() -> None:
    rule = _rule("1d", "2")

    assert "imdb_id solo se compare nella richiesta, nella conversazione o in un passo già fatto" in rule
    assert "non aggiungere una chiamata a tmdb_search solo per ottenerlo" in rule
    assert "non scrivere mai un imdb_id ricordato a memoria" in rule
    assert "non inventarli" in rule or "non assegna punteggi a un'opera dubbia" in rule


def test_rule_1_still_sends_critic_lists_to_tmdb_discover() -> None:
    assert "i giudizi della critica" in _rule("1", "1b") and "discover" in _rule("1", "1b")


# --- the reviews preference ----------------------------------------------------------------------


def _planner(sources: str) -> str:
    return build_prompt_parts(resolve_preferences({"preferred_sources": sources}).preferences)["planner"]


def test_omdb_serves_the_reviews_source_and_every_allowed_tool_is_declared() -> None:
    assert behavior.SOURCE_TOOLS["omdb_search"] == "reviews"
    assert set(app_module.CONFIG["orchestrator"]["allowed_tools"]) <= set(behavior.SOURCE_TOOLS)


def test_only_the_reviews_preference_points_the_planner_to_omdb() -> None:
    texts = {value: _planner(value) for value in behavior.SOURCES_PLANNER}

    assert [v for v, text in texts.items() if "omdb_search" in text] == ["reviews"]
    assert "regola 1d" in texts["reviews"] and "prima di tmdb_search" in texts["reviews"]
    # The other settings keep their text, and the reviews one keeps the TMDb reviews facet.
    assert "facet reviews" in texts["reviews"]
    assert "omdb" not in build_prompt_parts(defaults())["planner"].lower()


def test_the_reviews_preference_adds_no_step_and_no_call() -> None:
    text = _planner("reviews")

    assert "more_steps" not in text and "youtube_search" not in text
    assert "non aggiungono tool né passi" in text


def test_without_preferences_the_terminal_prompt_has_no_omdb_hint() -> None:
    client = FakeClient({"standalone_query": "q", "tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9})
    config = app_module.build_runtime_config()
    LLMOrchestrator(config=config, tools=[_Other()], client=client).run(query="q", conversation_history=[])

    assert "Preferenze dell'utente" not in client.calls[0]["instructions"]


def test_the_reviews_answer_text_separates_critic_scores_from_user_scores() -> None:
    text = behavior.SOURCES_ANSWER["reviews"]

    assert "Metascore, Rotten Tomatoes" in text and "voto IMDb" in text
    assert "mai recensioni o voti di utenti" in text.replace("Non presentare ", "")


def test_a_turn_planned_elsewhere_never_calls_omdb_even_with_the_reviews_preference() -> None:
    omdb, transport = make_tool(by_endpoint(by_id={ID: record()}))
    parts = build_prompt_parts(resolve_preferences({"preferred_sources": "reviews"}).preferences)
    client = FakeClient({"standalone_query": "classifica", "tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9})
    config = app_module.build_runtime_config()
    LLMOrchestrator(config=config, tools=[_Other(), omdb], client=client).run(query="q", conversation_history=[], prompt_parts=parts)

    assert transport.calls == [] and len(client.calls) == 2  # one planning call, one answer


# --- per-tool final rules ----------------------------------------------------------------------


def _turn(plan: dict, tool) -> FakeClient:
    client = FakeClient(plan)
    config = app_module.build_runtime_config()
    LLMOrchestrator(config=config, tools=[tool], client=client).run(query="domanda", conversation_history=[])
    return client


def test_omdb_final_rules_only_on_omdb_turns() -> None:
    omdb, _ = make_tool(by_endpoint(by_id={ID: record()}))

    omdb_turn = _turn({"tool_name": "omdb_search", "arguments": {"imdb_id": ID}, "confidence": 0.9}, omdb)
    other_turn = _turn({"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}, _Other())

    assert omdb_turn.calls[1]["instructions"].endswith(RULES["omdb_search"]) and RULES["omdb_search"] not in other_turn.calls[1]["instructions"]
    assert other_turn.calls[1]["instructions"] == app_module.CONFIG["orchestrator"]["final_instructions"]


def test_the_omdb_rules_forbid_estimating_and_mixing_audience_with_critics() -> None:
    text = RULES["omdb_search"]

    for required in ("not_available", "non stimarlo", "non calcolare medie", "Non presentare mai il voto IMDb come giudizio della critica", "ambiguous o unverified", "non nominare il servizio"):
        assert required in text.replace("Non nominare", "non nominare")
    assert "non hai il testo delle recensioni" in text


# --- the whole turn ------------------------------------------------------------------------------


def test_a_planned_omdb_turn_reaches_the_presenter(monkeypatch, capsys) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})
    tool, transport = make_tool(by_endpoint(by_id={ID: record(rotten=None)}))
    plan = {"standalone_query": "Cosa dice la critica", "tool_name": "omdb_search", "arguments": {"imdb_id": ID}, "confidence": 0.9}
    config = app_module.build_runtime_config()
    built = {"config": config, "orchestrator": LLMOrchestrator(config=config, tools=[tool], client=FakeClient(plan))}

    turn = app_module.handle_query(built, "Cosa dice la critica di Sample Movie?", [])
    present(turn, OutputChannel.terminal)

    assert turn.tool == "omdb_search" and STEP_OMDB_CALLS in [step.kind for step in turn.steps]
    assert len(transport.calls) == 1
    out = capsys.readouterr().out
    assert "OMDb" in out and "Metascore" in out and "non disponibile" in out
    assert "81/100" in out and "7.9/10" in out


# --- regressions of the live check (docs/omdb_routing_live_report.md) -----------------------------------------------


def test_the_final_rules_fix_the_rotten_tomatoes_format_and_forbid_a_winner_between_scales() -> None:
    text = RULES["omdb_search"]

    assert "campo display" in text and "9.3/10, 82/100, 93%" in text
    assert "Rotten Tomatoes è una percentuale e non va mai scritto «93/100»" in text
    assert "elenca separatamente per ogni fonte il nome, il punteggio e la scala" in text
    assert "non dichiarare quale sia più alto, migliore, favorito o vincente" in text
    assert "le scale non sono equivalenti" in text


def test_rule_1d_verifies_the_candidates_of_a_recommendation_with_excellent_reviews_only_with_the_reviews_source() -> None:
    rule = _rule("1d", "2")

    assert "solo con le preferenze «recensioni»" in rule and "ottime recensioni" in rule
    assert "tmdb_search per i candidati" in rule and "primi cinque candidati" in rule
    assert "title e year presi dai risultati di TMDb, mai inventati" in rule
    assert "non dedotta dal voto del pubblico" in rule
    # The default and the other sources never get the extra steps.
    for source in ("official information", "interviews", "user ratings"):
        assert "omdb" not in _planner(source)
    assert "ciascuno dei primi cinque" in _planner("reviews")


def test_the_budget_covers_five_title_lookups_and_the_final_rules_cover_several_titles() -> None:
    from tool.omdb.config import load_omdb_config

    assert load_omdb_config(app_module.CONFIG["omdb"]).max_calls_per_turn >= 2 * 5
    text = RULES["omdb_search"]
    assert "di più titoli" in text and "non hanno un punteggio della critica" in text
    assert "non presentare mai i voti del pubblico come giudizio della critica" in text
