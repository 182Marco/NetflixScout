from __future__ import annotations

import pytest

import app as app_module
from presenters import OutputChannel, present
from rag.FromQueryEmbeddingToRes.models import QuerySignals, RagChunk, RagResult, RerankBackend, SearchMode
from rag.FromQueryEmbeddingToRes.tool_interface import RagTool
from turn import TraceStep, TurnResult


def _chunk(idx: int, title: str) -> RagChunk:
    return RagChunk(id=f"c{idx}", testo=f"trama {idx}", score=0.9 - idx / 10, title=title, release_year="1999")


def _fake_run_rag(*, config, query, history=None) -> RagResult:
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
    monkeypatch.setattr("rag.FromQueryEmbeddingToRes.tool_interface.run_rag", _fake_run_rag)

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

    def run(self, *, query, conversation_history=None):
        self.calls += 1
        return {
            "tool": "rag_search",
            "standalone_query": "film di fantascienza con robot più recenti",
            "result": {"trace": [{"kind": "retrieval", "title": "K largo", "data": {"chunks": []}}]},
            "final_answer": "Guarda Matrix.",
        }


def _fake_app() -> dict:
    return {"config": app_module.build_runtime_config(), "orchestrator": _FakeOrchestrator()}


def test_handle_query_records_steps_in_order(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})

    turn = app_module.handle_query(_fake_app(), "un film con robot", history=[])

    assert [s.kind for s in turn.steps] == ["classification", "query_rewrite", "tool_selection", "retrieval"]
    assert turn.steps[1].data == {
        "original": "un film con robot",
        "used": "film di fantascienza con robot più recenti",
        "rewritten": True,
    }
    assert turn.answer == "Guarda Matrix."
    assert turn.tool == "rag_search"
    assert turn.history[-1] == {"role": "assistant", "content": "Guarda Matrix."}


def test_handle_query_blocks_non_cinema_without_orchestrator(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": False, "is_italian": False})
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
            TraceStep(kind="classification", title="Classificazione", data={"is_cinema": True}),
            TraceStep(
                kind="query_rewrite",
                title="Query usata dai tool",
                data={"original": "e uno più recente?", "used": "film con robot recenti", "rewritten": True},
            ),
            TraceStep(kind="tool_selection", title="Tool scelto", data={"tool": "rag_search"}),
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
    assert "rag_search" in out
    assert "Query riscritta con il contesto: film con robot recenti" in out
    assert "Testo usato per l'embedding: Movies about robots" in out
    assert "Generi richiesti: Science Fiction" in out
    assert "K LARGO — 2 CHUNK RECUPERATI" in out
    assert "RERANKING — 1 CHUNK SELEZIONATI" in out
    assert "PASSO NUOVO" in out
    assert "Guarda Matrix." in out
    assert out.index("K LARGO") < out.index("RERANKING") < out.index("Guarda Matrix.")


def test_web_channel_is_prepared_but_not_implemented(capsys) -> None:
    with pytest.raises(NotImplementedError):
        present(_sample_turn(), OutputChannel.web)
    assert capsys.readouterr().out == ""


def test_handle_query_gives_recent_history_to_the_classifier(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_classifier(query, history=None):
        captured["history"] = history
        return {"is_cinema": True, "is_italian": True}

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
