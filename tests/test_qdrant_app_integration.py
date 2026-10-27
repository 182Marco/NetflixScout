"""Qdrant inside the real application and Web API (embedded index, no network).

The index location comes from the environment, both entry points start from `build_ready_app`, the application
never imports Chroma (it is no longer a dependency), and a whole turn (HTTP -> SSE -> `handle_query` -> real
`RagTool` -> Qdrant) works with the LLM/embedding/rerank calls replaced by fakes.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from web_api_support import make_client, names, parse_sse, streamed_text

import app as app_module
from tool.rag.FromQueryEmbeddingToRes import retrieval, vectorstore
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals
from tool.rag.FromQueryEmbeddingToRes.store import StorePoint
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantUnavailable, close_clients
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client
from tool.rag.FromQueryEmbeddingToRes.tool_interface import RagTool
from turn_support import stream_decision
from web_api import create_app
from web_api.settings import WebApiSettings

ROOT = Path(__file__).resolve().parents[1]
DIM = 1536
TITLES = ["Film Alpha", "Film Beta", "Film Gamma", "Film Delta"]


def _vec(i: int, weight: float = 1.0) -> list[float]:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = weight
    return v.tolist()


def build_index(path: Path, *, model: str = "text-embedding-3-small", points: bool = True) -> None:
    """A tiny embedded Qdrant index shaped like the migrated one."""
    store = QdrantStore(open_client("embedded", path=path), "netflix_scout", IndexMeta(model, DIM))
    store.create()
    if points:
        store.upsert([
            StorePoint(id=f"legacy-{i}", vector=_vec(i), document=f"plot of {title}",
                       metadata={"title": title, "movie_id": str(100 + i), "release_year": str(1990 + i),
                                 "genres": "Drama", "source": "plots"})
            for i, title in enumerate(TITLES)
        ])
    store.close()


def env_for(path: Path, **extra: str) -> dict[str, str]:
    return {"VECTORSTORE_QDRANT_MODE": "embedded",
            "VECTORSTORE_QDRANT_PATH": str(path), **extra}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(app_module, "ensure_db_ready", lambda config: None)  # no 1.3 GB MovieLens DB here
    yield
    close_clients()


# ---------------------------------------------------------------- where the index is
def test_qdrant_is_the_only_store_and_the_environment_only_says_where_it_is():
    default = app_module.CONFIG["rag"]["vectorstore"]
    assert set(default) == {"collection", "qdrant"} and default["qdrant"]["mode"] == "server"
    assert default["qdrant"]["url"] == "http://127.0.0.1:6333"
    assert app_module.vector_store_overrides({}) == {} and app_module.vector_store_overrides({"VECTORSTORE_QDRANT_URL": " "}) == {}
    chosen = app_module.vector_store_overrides({"VECTORSTORE_QDRANT_URL": "http://h:6333", "VECTORSTORE_QDRANT_MODE": "",
                                                "QDRANT_API_KEY": "never-in-config"})
    assert chosen == {"rag": {"vectorstore": {"qdrant": {"url": "http://h:6333"}}}}
    assert "never-in-config" not in str(chosen)  # the key has a single reader, in the store package
    assert not hasattr(app_module, "ENV_VECTOR_ENGINE")  # there is no other engine to select


def test_build_ready_app_starts_on_qdrant_and_explicit_overrides_win(tmp_path):
    build_index(tmp_path / "q")
    ready = app_module.build_ready_app(env=env_for(tmp_path / "q"))
    vs = ready["config"]["rag"]["vectorstore"]
    assert vs["qdrant"]["mode"] == "embedded" and vs["qdrant"]["path"] == str(tmp_path / "q")
    assert "rag_search" in ready["orchestrator"].tools  # the RAG tool is wired on the Qdrant config
    assert ready["orchestrator"].tools["rag_search"].config["vectorstore"]["qdrant"]["path"] == str(tmp_path / "q")
    other = app_module.build_ready_app({"rag": {"vectorstore": {"qdrant": {"path": str(tmp_path / "q")}}}},
                                       env=env_for(tmp_path / "ignored"))
    assert other["config"]["rag"]["vectorstore"]["qdrant"]["path"] == str(tmp_path / "q")


# ---------------------------------------------------------------- operational errors
def test_a_missing_collection_tells_how_to_build_it(tmp_path):
    client = open_client("embedded", path=tmp_path / "q")
    client.close()
    with pytest.raises(RuntimeError, match="buildSemanticDb"):
        app_module.build_ready_app(env=env_for(tmp_path / "q"))


def test_an_empty_collection_is_reported(tmp_path):
    build_index(tmp_path / "q", points=False)
    with pytest.raises(RuntimeError, match="Qdrant collection is empty"):
        app_module.build_ready_app(env=env_for(tmp_path / "q"))


def test_an_index_of_another_model_is_refused(tmp_path):
    build_index(tmp_path / "q", model="some-other-model")
    with pytest.raises(ValueError, match="rebuild the index"):
        app_module.build_ready_app(env=env_for(tmp_path / "q"))


def test_an_unreachable_server_gives_an_operational_message_without_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("QDRANT_API_KEY", "secret-key-123")
    env = {"VECTORSTORE_QDRANT_MODE": "server", "VECTORSTORE_QDRANT_URL": "http://127.0.0.1:9"}
    with pytest.raises(QdrantUnavailable) as caught:
        app_module.build_ready_app(env=env)
    text = str(caught.value)
    assert "http://127.0.0.1:9" in text and "start_qdrant.sh" in text and "secret-key-123" not in text
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# ---------------------------------------------------------------- no Chroma anywhere
def test_the_application_runs_without_chroma_installed(tmp_path):
    build_index(tmp_path / "q")
    script = textwrap.dedent(f"""
        import sys
        class BlockChroma:
            def find_spec(self, name, path=None, target=None):
                if name == "chromadb" or name.startswith("chromadb."):
                    raise ImportError("chromadb is blocked in this process")
        sys.meta_path.insert(0, BlockChroma())
        import numpy as np
        import app
        app.ensure_db_ready = lambda config: None
        ready = app.build_ready_app(env={env_for(tmp_path / "q")!r})
        from tool.rag.FromQueryEmbeddingToRes import vectorstore
        from tool.rag.FromQueryEmbeddingToRes.runtime import _resolve_runtime_config
        v = np.zeros(1536, dtype=np.float32); v[0] = 1
        vectorstore.embed = lambda texts, backend=None, model=None: np.array([v])
        cfg = _resolve_runtime_config(ready["config"]["rag"])
        col = vectorstore.apri_collection("netflix_scout", store_config=cfg["vectorstore"])
        rows = vectorstore.search(col, "q", 2, backend="local", model="m")
        assert rows[0]["title"] == "Film Alpha", rows
        assert "chromadb" not in sys.modules
        print("OK")
    """)
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    assert done.returncode == 0 and done.stdout.strip().endswith("OK"), done.stderr[-1500:]


# ---------------------------------------------------------------- the Web API on Qdrant
class QdrantRagOrchestrator:
    """Streams like `LLMOrchestrator.run` but runs the REAL `RagTool` (Qdrant) as its tool."""

    def __init__(self, rag_tool: RagTool) -> None:
        self.rag_tool = rag_tool

    def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, final_output=None, answer_language=None):
        result = self.rag_tool.run(query=query, params={}, conversation_history=conversation_history)
        decision = {"tool": "rag_search", "tools": ["rag_search"],
                    "calls": [{"tool": "rag_search", "arguments": {}, "result": result}],
                    "standalone_query": query, "result": result, "final_lists": []}
        stream_decision(observer, query, {**decision, "final_answer": ""})
        answer = "Ti consiglio: " + ", ".join(c["title"] for c in result["chunks"]) + "."
        for i in range(0, len(answer), 9):
            observer.answer_delta(answer[i:i + 9])
        return {**decision, "final_answer": answer}


def test_a_whole_turn_over_http_and_sse_uses_the_qdrant_index(tmp_path, monkeypatch):
    build_index(tmp_path / "q")
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})
    monkeypatch.setattr(vectorstore, "embed", lambda texts, backend=None, model=None: np.array([_vec(0, 1.0)], dtype=np.float32))
    monkeypatch.setattr(retrieval, "_extract_query_signals",
                        lambda query, llm_model, hint=None, **kwargs: QuerySignals(semantic_query="a quiet drama"))
    monkeypatch.setattr(retrieval, "rerank_cohere",
                        lambda query, chunks, model, cohere_api_client=None: [{**c, "score": 1.0 - n / 10} for n, c in enumerate(chunks)])
    config = app_module.build_runtime_config(app_module.vector_store_overrides(env_for(tmp_path / "q")))
    config = app_module.build_runtime_config({"rag": config["rag"]})
    bot = {"config": config, "orchestrator": QdrantRagOrchestrator(RagTool(config=config["rag"]))}

    with TestClient(create_app(WebApiSettings(), bot, client=object())) as client:  # type: ignore[arg-type]
        conversation_id = client.post("/conversations").json()["conversation_id"]
        response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "un dramma tranquillo"})
        events = parse_sse(response.text)

    assert response.status_code == 200 and names(events)[0] == "turn_start" and names(events)[-1] == "done"
    steps = [data for _, name, data in events if name == "step"]
    assert [s["kind"] for s in steps] == ["retrieval", "rerank"]
    assert "Film Alpha" in streamed_text(events)  # the closest point of the Qdrant index
    end = next(data for _, name, data in events if name == "answer_end")
    assert end["tool"] == "rag_search" and not end["blocked"]


def test_the_web_api_builds_its_bot_on_qdrant_from_the_environment(tmp_path, monkeypatch):
    build_index(tmp_path / "q")
    for key, value in env_for(tmp_path / "q").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("OPENAI_API_KEY", "not-used-no-call-is-made")
    with TestClient(create_app(WebApiSettings())) as client:  # real lifespan: build_ready_app()
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/conversations").status_code == 201
        bot = client.app.state.web_api.bot_app
        assert bot["config"]["rag"]["vectorstore"]["qdrant"]["mode"] == "embedded"


def test_the_web_api_refuses_to_start_when_the_index_is_missing(tmp_path, monkeypatch):
    open_client("embedded", path=tmp_path / "q").close()
    for key, value in env_for(tmp_path / "q").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")
    with pytest.raises(RuntimeError, match="buildSemanticDb"):
        with TestClient(create_app(WebApiSettings())):
            pass


def test_the_default_web_api_tests_still_use_the_fake_bot():
    from web_api_support import FakeOrchestrator

    with make_client(FakeOrchestrator()) as client:
        assert client.get("/health").status_code == 200


def test_every_entry_point_starts_from_the_same_configuration():
    """Terminal (`run_terminal_chat`), web API (`create_app`) and the legacy loop all start from `build_ready_app`
    / the same CONFIG: one default location (CONFIG, or the VECTORSTORE_QDRANT_* variables)."""
    import inspect

    assert "build_ready_app_or_exit()" in inspect.getsource(app_module.run_terminal_chat)
    assert "build_ready_app_or_exit" in (Path(__file__).resolve().parents[1] / "web_api" / "main.py").read_text()
    assert app_module.build_runtime_config()["rag"]["vectorstore"]["qdrant"]["mode"] == "server"


def _down(*a, **k):
    from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantUnavailable

    raise QdrantUnavailable("Cannot reach Qdrant at http://127.0.0.1:6333 (X). Start the server.")


def test_entry_points_report_an_unreachable_qdrant_server_in_one_line(monkeypatch):
    monkeypatch.setattr(app_module, "build_ready_app", _down)
    with pytest.raises(SystemExit) as stop:
        app_module.build_ready_app_or_exit()
    assert str(stop.value) == "Error: Cannot reach Qdrant at http://127.0.0.1:6333 (X). Start the server."
    assert stop.value.__cause__ is None and stop.value.code != 0
    with pytest.raises(SystemExit):  # the terminal goes through it
        app_module.run_terminal_chat()


def test_other_startup_errors_keep_their_traceback(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("the MovieLens database is missing")

    monkeypatch.setattr(app_module, "build_ready_app", broken)
    with pytest.raises(RuntimeError, match="MovieLens"):
        app_module.build_ready_app_or_exit()


def test_a_working_server_returns_the_bot_unchanged(tmp_path):
    build_index(tmp_path / "q")
    ready = app_module.build_ready_app_or_exit(env=env_for(tmp_path / "q"))
    assert "rag_search" in ready["orchestrator"].tools
