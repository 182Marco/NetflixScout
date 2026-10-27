"""One language per turn, from the LATEST user message: fixed texts, prompts, fallbacks, channels."""
from __future__ import annotations

import json

import pytest

import app as app_module
from orchestrator import FALLBACK_NO_ANSWER, NO_ANSWER_TEXTS, LLMOrchestrator
from presenters import OutputChannel, present, story_view
from presenters import api_view, rag_view, wikipedia_view, youtube_view
from presenters.terminal import blocks as terminal_blocks
from presenters.terminal.texts import TEXTS
from presenters.web import to_payload
from stream_support import reply
from tool.wikipedia.queries import api_url, page_url
from turn import SUPPORTED_LABEL_LANGUAGES, TraceStep, TurnResult
from turn_support import stream_decision
from web_api_support import FakeOrchestrator, make_client, parse_sse

LANGS = ("it", "en", "de")


# --- fixed texts: every table has the same keys in every supported language ---------------------------------


@pytest.mark.parametrize(
    "table",
    [
        story_view.TEXT, story_view.TOOLS, story_view.REASONS, story_view.FALLBACKS, api_view.LABELS,
        wikipedia_view.LABELS, wikipedia_view.CODE_LABELS, youtube_view.LABELS, youtube_view.KIND_LABELS,
        youtube_view.CODE_LABELS, youtube_view.BLOCKED_IN, rag_view.RETRIEVAL_TITLE, rag_view.RERANK_TITLE,
        TEXTS, NO_ANSWER_TEXTS, app_module.NON_CINEMA_BLOCK_MESSAGES,
    ],
    ids=lambda table: str(sorted(table["en"])[:2]),
)
def test_every_fixed_text_table_covers_italian_english_and_german(table) -> None:
    assert set(table) == set(LANGS) == set(SUPPORTED_LABEL_LANGUAGES)
    if isinstance(table["en"], dict):
        assert set(table["it"]) == set(table["en"]) == set(table["de"])


@pytest.mark.parametrize("language", [*LANGS, "fr", "ja", "xx"])
def test_the_story_exists_in_every_language_and_other_languages_read_english(language) -> None:
    steps = [
        TraceStep(kind="classification", title="x", data={"language": language}),
        TraceStep(kind="tool_selection", title="x", data={"tool": "tmdb_search", "purpose": "p"}),
        TraceStep(kind="tool_outcome", title="x", data={"tool": "tmdb_search", "status": "ok", "elapsed_ms": 1500}),
    ]

    texts = [line.text for line in story_view.build_story(steps)]

    expected = {
        "it": ["Cerco su TMDb: p", "TMDb: trovato, 2 s"],
        "de": ["Ich suche auf TMDb: p", "TMDb: gefunden, 2 s"],
    }.get(language, ["Searching on TMDb: p", "TMDb: found, 2 s"])
    assert texts == expected


def test_the_story_builder_keeps_any_language_code_learned_from_the_classification() -> None:
    builder = story_view.StoryBuilder()
    builder.step(TraceStep(kind="classification", title="x", data={"language": "fr"}))
    assert builder.language == "fr"
    assert builder.status("answering")[0].text == "Writing the answer…"


def test_a_german_turn_has_german_tool_labels_in_both_channels(capsys) -> None:
    step = TraceStep(
        kind="tmdb_calls", title="TMDb", data={"calls": ["https://api.themoviedb.org/3/movie/1?api_key=***"], "attributions": []}
    )
    turn = TurnResult(query="q", language="de", blocked=False, answer="a", tool="tmdb_search", steps=[step])

    present(turn, OutputChannel.terminal)
    printed = capsys.readouterr().out
    payload = to_payload(turn)

    assert "TMDB-ANFRAGEN" in printed and "Aufgerufen" in printed
    assert payload["language"] == "de"
    assert payload["steps"][0]["title"] == "TMDB-ANFRAGEN"


def test_the_terminal_answer_header_and_notice_follow_the_language(capsys) -> None:
    for language, title in (("it", "RISPOSTA FINALE"), ("en", "FINAL ANSWER"), ("de", "ENDGÜLTIGE ANTWORT"), ("fr", "FINAL ANSWER")):
        terminal_blocks.print_answer_header(language)
        terminal_blocks.print_compact_notice(language)
        out = capsys.readouterr().out.splitlines()
        box = [line for line in out if line.startswith(("╔", "║", "╚"))]
        assert title in box[1]
        # The robot emoji is two columns wide: the box stays rectangular in every language.
        assert len({len(line) + line.count("🤖") for line in box}) == 1
        assert TEXTS["en" if language == "fr" else language]["compact"] in out


def test_a_german_rag_step_has_a_german_title_and_the_web_and_terminal_titles_agree(capsys) -> None:
    from presenters.terminal.rag import render_retrieval
    from presenters.web.rag.serializer import serialize_rag_step

    step = TraceStep(kind="retrieval", title="x", data={"chunks": [], "embedded_text": "robots", "signals": {"genres": ["Sci-Fi"]}})

    render_retrieval(step, "de")
    printed = capsys.readouterr().out

    assert "WEITES K — 0 CHUNKS ABGERUFEN" in printed and "Für das Embedding verwendeter Text" in printed
    assert serialize_rag_step(step, "de")["title"] == "WEITES K — 0 CHUNKS ABGERUFEN"
    assert serialize_rag_step(step, "fr")["title"] == "WIDE K — 0 CHUNKS RETRIEVED"


# --- prompts: one language rule, never duplicated, absent when no language is given --------------------------


class _Tool:
    name = "rag_search"
    description = "fake"
    input_schema: dict = {}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [{"title": "Alien", "testo": "Trama"}], "metadata": {}}


class _Client:
    def __init__(self, plan: dict, final: str = "Antwort.") -> None:
        self.plan, self.final, self.calls = plan, final, []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(json.dumps(self.plan) if len(self.calls) == 1 else self.final, kwargs)


def _orchestrator(plan: dict, **config):
    client = _Client(plan)
    cfg = {"fallback_tool": "rag_search", "tool_confidence_threshold": 0.6, **config}
    return LLMOrchestrator(config={"orchestrator": cfg}, tools=[_Tool()], client=client), client


PLAN = {"standalone_query": "q", "tool_name": "rag_search", "confidence": 0.9}


@pytest.mark.parametrize(("code", "name"), [("de", "German"), ("it", "Italian"), ("fr", "French")])
def test_the_final_answer_prompt_has_one_language_rule(code, name) -> None:
    orch, client = _orchestrator(PLAN, final_instructions="Regole base.", tool_final_instructions={"rag_search": "Regole RAG."})

    orch.run(query="Welche Filme?", answer_language=code)

    final = client.calls[1]["instructions"]
    assert final.count("Scrivi la risposta in") == 1 and f"in {name} (la lingua dell'ultimo messaggio" in final
    assert final.startswith("Regole base. Regole RAG. Scrivi la risposta in")  # after the tool rules


def test_the_language_rule_goes_before_the_user_preferences_so_they_still_govern_the_form() -> None:
    orch, client = _orchestrator(PLAN, final_instructions="Base.")

    orch.run(query="q", answer_language="de", prompt_parts={"planner": "", "answer": "Sii conciso."})

    final = client.calls[1]["instructions"]
    assert final.index("German") < final.index("Sii conciso.") and final.endswith("Sii conciso.")


def test_without_a_language_both_prompts_are_exactly_as_before() -> None:
    orch, client = _orchestrator(PLAN, final_instructions="Base.")
    baseline, baseline_client = _orchestrator(PLAN, final_instructions="Base.")

    orch.run(query="q")
    baseline.run(query="q", answer_language=None)

    assert [c["instructions"] for c in client.calls] == [c["instructions"] for c in baseline_client.calls]
    assert "Scrivi la risposta in" not in client.calls[1]["instructions"]
    assert "clarification_question" not in client.calls[0]["instructions"].split("Allowed tools")[-1].split("Tool catalog")[0]


def test_the_planner_is_told_the_language_for_a_clarification_question() -> None:
    orch, client = _orchestrator(PLAN, instructions="Regole del planner.")

    orch.run(query="Wer spielte in diesem Film?", conversation_history=[], answer_language="de")

    planner = client.calls[0]["instructions"]
    assert planner.count("L'ultimo messaggio dell'utente è in German") == 1
    assert "clarification_question" in planner.split("L'ultimo messaggio dell'utente è in German")[1]


def test_a_german_clarification_question_is_the_answer_and_costs_no_final_call() -> None:
    question = "Welchen Film meinst du?"
    plan = {"needs_clarification": True, "clarification_question": question, "standalone_query": "q"}
    orch, client = _orchestrator(plan)

    decision = orch.run(query="Wer spielte in diesem Film?", answer_language="de")

    assert decision["clarification"] and decision["final_answer"] == question and len(client.calls) == 1


# --- fixed fallbacks by language ----------------------------------------------------------------------------


@pytest.mark.parametrize(("code", "text"), [("it", FALLBACK_NO_ANSWER), ("en", NO_ANSWER_TEXTS["en"]), ("de", NO_ANSWER_TEXTS["de"]), ("fr", NO_ANSWER_TEXTS["en"]), (None, FALLBACK_NO_ANSWER)])
def test_the_empty_answer_fallback_follows_the_turn_language(code, text) -> None:
    orch, client = _orchestrator(PLAN)
    client.final = "   "

    decision = orch.run(query="q", answer_language=code)

    assert decision["final_answer"] == text


# --- handle_query: the latest message decides, turn after turn ----------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.languages: list = []
        self.overrides: list = []

    def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, answer_language=None, **_):
        self.languages.append(answer_language)
        self.overrides.append(tool_overrides)
        decision = {"tool": "rag_search", "standalone_query": query, "result": {"trace": []}, "final_answer": "ok"}
        stream_decision(observer, query, decision)
        return decision


def test_the_language_can_change_at_any_message_and_follows_only_the_latest(monkeypatch) -> None:
    by_query = {"Consigliami un film": "it", "Und wer hat Regie geführt?": "de", "Who stars in it?": "en", "Et la suite ?": "fr"}
    monkeypatch.setattr(
        app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": by_query[q], "block_reply": None}
    )
    recorder = _Recorder()
    app = {"config": app_module.build_runtime_config(), "orchestrator": recorder}
    history: list = []
    turns = []
    for query in [*by_query] * 3:  # twelve messages: the language changes at every one
        turn = app_module.handle_query(app, query, history=history)
        history = turn.history
        turns.append(turn)

    assert [t.language for t in turns] == [by_query[q] for q in [*by_query] * 3]
    assert recorder.languages == [t.language for t in turns]
    assert [o["turn_language"] for o in recorder.overrides] == recorder.languages
    assert turns[-1].story and all(isinstance(t.language, str) for t in turns)


def test_a_german_turn_story_is_german_and_a_french_turn_story_is_english(monkeypatch) -> None:
    def run(language):
        monkeypatch.setattr(
            app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": language, "block_reply": None}
        )
        app = {"config": app_module.build_runtime_config(), "orchestrator": _Recorder()}
        return app_module.handle_query(app, "q", history=[])

    assert any("gefunden" in line.text for line in run("de").story)
    assert any("found" in line.text for line in run("fr").story)


# --- web: answer_end.language is any ISO code ---------------------------------------------------------------


@pytest.mark.parametrize("language", ["de", "fr", "ja"])
def test_answer_end_carries_the_real_language_code(monkeypatch, language) -> None:
    monkeypatch.setattr(
        app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": language, "block_reply": None}
    )
    with make_client(FakeOrchestrator()) as client:
        conversation = client.post("/conversations").json()["conversation_id"]
        response = client.post(f"/conversations/{conversation}/messages", json={"content": "q"})
    events = parse_sse(response.text)

    end = next(data for _, name, data in events if name == "answer_end")
    assert end["language"] == language
    story = [data["text"] for _, name, data in events if name == "story"]
    assert story  # the story is told in a supported language or in English, never empty


def test_a_blocked_german_turn_over_http_is_the_fixed_german_text(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": False, "language": "de", "block_reply": None}
    )
    with make_client(FakeOrchestrator()) as client:
        conversation = client.post("/conversations").json()["conversation_id"]
        events = parse_sse(client.post(f"/conversations/{conversation}/messages", json={"content": "Wer gewinnt?"}).text)

    text = "".join(data["text"] for _, name, data in events if name == "answer_delta")
    end = next(data for _, name, data in events if name == "answer_end")
    assert text == app_module.NON_CINEMA_BLOCK_MESSAGES["de"] and end["blocked"] and end["language"] == "de"


# --- Wikipedia: German edition for a local topic -------------------------------------------------------------


def test_the_german_edition_is_a_known_host() -> None:
    assert api_url("de") == "https://de.wikipedia.org/w/api.php"
    assert page_url("de", "Das Boot") == "https://de.wikipedia.org/wiki/Das_Boot"
