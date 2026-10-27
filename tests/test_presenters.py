from __future__ import annotations

import pytest

import app as app_module
from presenters import OutputChannel, present
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, RagChunk, RagResult, RerankBackend, SearchMode
from tool.rag.FromQueryEmbeddingToRes.tool_interface import RagTool
from turn import TraceStep, TurnResult
from turn_support import stream_decision


def _chunk(idx: int, title: str) -> RagChunk:
    return RagChunk(id=f"c{idx}", testo=f"trama {idx}", score=0.9 - idx / 10, title=title, release_year="1999")


def _fake_run_rag(*, config, query, history=None, query_hint=None, **kwargs) -> RagResult:
    return RagResult(
        query=query,
        search_mode=SearchMode.semantic,
        rerank_backend=RerankBackend.cohere,
        chunks=[_chunk(1, "Matrix")],
        candidates=[_chunk(1, "Matrix"), _chunk(2, "Dark City")],
        signals=QuerySignals(semantic_query="Movies about robots", genres=["Science Fiction"]),
        embedded_text="Movies about robots",
    )


def test_rag_tool_returns_trace_outside_metadata(monkeypatch) -> None:
    monkeypatch.setattr("tool.rag.FromQueryEmbeddingToRes.tool_interface.run_rag", _fake_run_rag)

    result = RagTool(config={}).run(query="film con robot", params={}, conversation_history=[])

    assert [step["kind"] for step in result["trace"]] == ["retrieval", "rerank"]
    assert len(result["trace"][0]["data"]["chunks"]) == 2
    assert result["trace"][1]["data"]["chunks"] == result["chunks"]
    assert "trace" not in result["metadata"]
    assert result["trace"][0]["data"]["embedded_text"] == "Movies about robots"
    assert result["trace"][0]["data"]["signals"]["genres"] == ["Science Fiction"]


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_overrides = None

    def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, answer_language=None):
        self.calls += 1
        self.tool_overrides = tool_overrides
        decision = {
            "tool": "rag_search",
            "standalone_query": "film di fantascienza con robot più recenti",
            "result": {"trace": [{"kind": "retrieval", "title": "K largo", "data": {"chunks": []}}]},
            "final_answer": "Guarda Matrix.",
        }
        stream_decision(observer, query, decision)
        return decision


def _fake_app() -> dict:
    return {"config": app_module.build_runtime_config(), "orchestrator": _FakeOrchestrator()}


def test_handle_query_records_steps_in_order(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})

    turn = app_module.handle_query(_fake_app(), "un film con robot", history=[])

    assert [s.kind for s in turn.steps] == ["classification", "query_rewrite", "tool_selection", "tool_outcome", "retrieval"]
    assert turn.steps[1].data == {
        "original": "un film con robot",
        "used": "film di fantascienza con robot più recenti",
        "rewritten": True,
    }
    assert turn.answer == "Guarda Matrix."
    assert turn.tool == "rag_search"
    assert turn.history[-1] == {"role": "assistant", "content": "Guarda Matrix."}


def test_handle_query_passes_the_turn_language_to_the_tools(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "en"})
    fake_app = _fake_app()

    turn = app_module.handle_query(fake_app, "Who directed Dune?", history=[])

    assert turn.language == "en"
    assert fake_app["orchestrator"].tool_overrides == {"turn_language": "en"}


def test_handle_query_blocks_non_cinema_without_orchestrator(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": False, "language": "en"})
    fake_app = _fake_app()

    turn = app_module.handle_query(fake_app, "what's the weather?", history=[])

    assert turn.blocked is True
    assert turn.answer == app_module.NON_CINEMA_BLOCK_MESSAGES["en"]
    assert fake_app["orchestrator"].calls == 0


def _sample_turn() -> TurnResult:
    chunks = [c.model_dump(mode="json") for c in (_chunk(1, "Matrix"), _chunk(2, "Dark City"))]
    return TurnResult(
        query="film con robot",
        language="it",
        blocked=False,
        answer="Guarda Matrix.",
        tool="rag_search",
        steps=[
            TraceStep(
                kind="classification",
                title="Classificazione",
                data={"is_cinema": True, "language": "it"},
            ),
            TraceStep(
                kind="query_rewrite",
                title="Query usata dai tool",
                data={"original": "e uno più recente?", "used": "film con robot recenti", "rewritten": True},
            ),
            TraceStep(kind="tool_selection", title="Tool scelto", data={"tool": "rag_search"}),
            TraceStep(
                kind="tool_outcome",
                title="Esito",
                data={"tool": "rag_search", "elapsed_ms": 2400, "status": "ok", "reason": None},
            ),
            TraceStep(
                kind="retrieval",
                title="K largo",
                data={
                    "embedded_text": "Movies about robots",
                    "signals": {"genres": ["Science Fiction"]},
                    "chunks": chunks,
                },
            ),
            TraceStep(kind="rerank", title="Reranking", data={"chunks": chunks[:1]}),
            TraceStep(kind="future_tool_step", title="Passo nuovo", data={"esito": "ok"}),
        ],
    )


def test_terminal_channel_prints_full_procedure(capsys) -> None:
    assert present(_sample_turn(), OutputChannel.terminal) is None

    out = capsys.readouterr().out
    assert "Cerco tra le trame dei film" in out
    assert "Trame: trovato, 2 s" in out
    assert "Classificatore" not in out
    assert "RAG PIPELINE COMPLETATA" not in out
    assert "Ho inteso la domanda così: film con robot recenti" in out
    assert "Testo usato per l'embedding: Movies about robots" in out
    assert "Generi richiesti: Science Fiction" in out
    assert "K LARGO — 2 CHUNK RECUPERATI" in out
    assert "RERANKING — 1 CHUNK SELEZIONATI" in out
    assert "PASSO NUOVO" in out
    assert "Guarda Matrix." in out
    assert out.index("K LARGO") < out.index("RERANKING") < out.index("Guarda Matrix.")


def test_web_channel_returns_the_payload_without_printing(capsys) -> None:
    payload = present(_sample_turn(), OutputChannel.web)

    assert capsys.readouterr().out == ""
    assert payload["answer"] == "Guarda Matrix." and payload["tool"] == "rag_search"
    assert [step["kind"] for step in payload["steps"]] == ["retrieval", "rerank", "future_tool_step"]


def test_handle_query_gives_recent_history_to_the_classifier(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_classifier(query, history=None):
        captured["history"] = history
        return {"is_cinema": True, "language": "it"}

    monkeypatch.setattr(app_module, "classify_query_domain", fake_classifier)
    history = [
        {"role": "user", "content": "vecchia domanda"},
        {"role": "assistant", "content": "vecchia risposta"},
        {"role": "user", "content": "Consigliami 3 film di fantascienza"},
        {"role": "assistant", "content": "Alien, Blade Runner, Stargate (1994)"},
    ]

    app_module.handle_query(_fake_app(), "Ne puoi trovare 3 più recenti rispetto al 94?", history=history)

    size = app_module.CONFIG["orchestrator"]["classifier_context_messages"]
    assert captured["history"] == history[-size:]


class _ClarifyingOrchestrator:
    def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, answer_language=None):
        decision = {
            "tool": None,
            "clarification": True,
            "standalone_query": query,
            "result": {"query": query, "chunks": [], "metadata": {}, "trace": []},
            "final_answer": "Quale film di Sorrentino intendi?",
        }
        stream_decision(observer, query, decision)
        return decision


def test_clarification_turn_is_recorded_and_printed_without_a_tool(monkeypatch, capsys) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})
    fake_app = {"config": app_module.build_runtime_config(), "orchestrator": _ClarifyingOrchestrator()}

    turn = app_module.handle_query(fake_app, "chi c'era in quel film di Sorrentino?", history=[])
    present(turn, OutputChannel.terminal)

    assert turn.tool is None and turn.answer == "Quale film di Sorrentino intendi?"
    assert turn.steps[2].data == {"tool": None, "clarification": True}
    assert turn.history[-1] == {"role": "assistant", "content": "Quale film di Sorrentino intendi?"}
    out = capsys.readouterr().out
    assert "Mi serve un chiarimento prima di cercare." in out


def test_handle_query_records_one_selection_per_tool_each_followed_by_its_trace(monkeypatch) -> None:
    """A multi-tool turn shows only the steps of the tools that ran (no RAG steps here)."""
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})

    class _TwoTools(_FakeOrchestrator):
        def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, answer_language=None):
            decision = {
                "tool": "tmdb_search",
                "tools": ["tmdb_search", "youtube_search"],
                "calls": [
                    {"tool": "tmdb_search", "arguments": {}, "result": {"trace": [{"kind": "tmdb_calls", "title": "TMDb", "data": {}}]}},
                    {"tool": "youtube_search", "arguments": {}, "result": {"trace": [{"kind": "youtube_calls", "title": "YouTube", "data": {}}]}},
                ],
                "standalone_query": query,
                "result": {"trace": []},
                "final_answer": "Ecco film e intervista.",
            }
            stream_decision(observer, query, decision)
            return decision

    app = {"config": app_module.build_runtime_config(), "orchestrator": _TwoTools()}

    turn = app_module.handle_query(app, "un film con DiCaprio e un'intervista", history=[])

    assert [s.kind for s in turn.steps] == [
        "classification", "query_rewrite", "tool_selection", "tool_outcome", "tmdb_calls",
        "tool_selection", "tool_outcome", "youtube_calls",
    ]
    assert [s.data["tool"] for s in turn.steps if s.kind == "tool_selection"] == ["tmdb_search", "youtube_search"]
    assert turn.tool == "tmdb_search" and turn.tools == ["tmdb_search", "youtube_search"]
    assert not any(s.kind in ("retrieval", "rerank") for s in turn.steps)


def test_planning_step_is_recorded_and_printed_when_a_part_was_not_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})

    class _Pending(_FakeOrchestrator):
        def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, answer_language=None):
            part = {"part": "un'intervista", "tool": "youtube_search"}
            decision = {
                "tool": "tmdb_search",
                "tools": ["tmdb_search"],
                "calls": [{"tool": "tmdb_search", "arguments": {}, "result": {"trace": []}}],
                "planning": {
                    "parts": [{"part": "un film", "tool": "tmdb_search"}, part],
                    "tools": ["tmdb_search"],
                    "pending": [part],
                    "stop_reason": "done",
                },
                "standalone_query": query,
                "result": {"trace": []},
                "final_answer": "Ecco il film.",
            }
            stream_decision(observer, query, decision)
            return decision

    app = {"config": app_module.build_runtime_config(), "orchestrator": _Pending()}

    turn = app_module.handle_query(app, "un film e un'intervista", history=[])
    present(turn, OutputChannel.terminal)

    assert turn.steps[-1].kind == "planning" and turn.steps[-1].data["stop_reason"] == "done"
    out = capsys.readouterr().out
    assert "Non ho cercato: un'intervista" in out


def test_a_single_tool_turn_has_no_planning_step(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})

    turn = app_module.handle_query(_fake_app(), "un film con robot", history=[])

    assert "planning" not in [s.kind for s in turn.steps]
