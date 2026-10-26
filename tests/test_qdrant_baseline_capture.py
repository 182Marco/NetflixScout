"""Offline checks of the Chroma baseline capture script (docs/qdrant_migration)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, SearchMode

SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "qdrant_migration" / "capture_baseline.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("capture_baseline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_baseline"] = module
    spec.loader.exec_module(module)
    return module


class FakeCollection:
    name = "fake"

    def __init__(self, vectors):
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.ids = [f"id{i}" for i in range(len(self.vectors))]

    def count(self):
        return len(self.ids)

    def get(self, limit, offset, include):
        sl = slice(offset, offset + limit)
        return {"ids": self.ids[sl], "embeddings": self.vectors[sl].tolist()}

    def query(self, query_embeddings, n_results):
        q = np.asarray(query_embeddings[0], dtype=np.float32)
        sims = self.vectors @ q / (np.linalg.norm(self.vectors, axis=1) * np.linalg.norm(q))
        order = np.argsort(-sims, kind="stable")[:n_results]
        return {
            "ids": [[self.ids[i] for i in order]],
            "distances": [[float(1 - sims[i]) for i in order]],
        }


def _chunk(i, score=0.5):
    return {"id": f"id{i}", "testo": "t", "score": score, "title": f"T{i}"}


def _run(monkeypatch, tmp_path, signals, cohere=True):
    module = _load_script()
    collection = FakeCollection([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0]])
    queries = tmp_path / "q.json"
    queries.write_text(json.dumps([{"id": "q1", "kind": "t", "query": "domanda"}]), encoding="utf-8")
    calls = {"rerank": [], "retrieve_modes": [], "sleep": 0}

    monkeypatch.setattr(module.vectorstore, "apri_collection", lambda *a, **k: collection)
    monkeypatch.setattr(module.retrieval, "_build_signal_aware_query", lambda q, c: signals)
    monkeypatch.setattr(module, "embed", lambda texts, backend, model: np.array([[1.0, 0.2, 0.0]]))

    def fake_retrieve(query, cfg, signals=None):
        calls["retrieve_modes"].append(cfg["retrieval"]["search_mode"])
        return [_chunk(0, 0.9), _chunk(3, 0.8)]

    def fake_rerank(rerank_query, chunks, cfg, signals=None):
        calls["rerank"].append((rerank_query, [c["id"] for c in chunks]))
        return list(reversed(chunks))

    monkeypatch.setattr(module.retrieval, "_retrieve", fake_retrieve)
    monkeypatch.setattr(module.retrieval, "_rerank", fake_rerank)
    monkeypatch.setattr(module.time, "sleep", lambda s: calls.__setitem__("sleep", calls["sleep"] + 1))
    original_embed = module.vectorstore.embed

    argv = ["--chroma-dir", str(tmp_path / "chroma"), "--out", str(tmp_path / "out"),
            "--queries", str(queries)]
    if cohere:
        argv.append("--cohere")
    monkeypatch.setattr(sys, "argv", ["capture_baseline.py", *argv])
    code = module.main()
    assert module.vectorstore.embed is original_embed  # the embed swap is always undone
    return code, calls, tmp_path / "out"


def test_cohere_branch_reranks_once_the_semantic_pool(monkeypatch, tmp_path):
    code, calls, out = _run(monkeypatch, tmp_path, QuerySignals(semantic_query="a sentence"))
    assert code == 0
    assert calls["retrieve_modes"] == [SearchMode.semantic, SearchMode.hybrid]
    assert len(calls["rerank"]) == 1
    assert calls["rerank"][0][1] == ["id0", "id3"]
    assert calls["sleep"] == 1
    record = json.loads((out / "q1.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in record["final_top"]] == ["id3", "id0"]
    assert record["exact_top50"][0]["id"] == "id0"
    assert record["embedded_text"] == "a sentence"
    assert (out / "q1.vec.npy").exists()


def test_without_cohere_no_rerank_and_no_sleep(monkeypatch, tmp_path):
    code, calls, out = _run(monkeypatch, tmp_path, QuerySignals(semantic_query="x"), cohere=False)
    assert code == 0 and calls["rerank"] == [] and calls["sleep"] == 0
    assert "final_top" not in json.loads((out / "q1.json").read_text(encoding="utf-8"))


def test_empty_semantic_query_stops_and_writes_nothing(monkeypatch, tmp_path):
    code, _, out = _run(monkeypatch, tmp_path, QuerySignals(semantic_query=""))
    assert code == 1
    assert not (out / "q1.json").exists()


def test_existing_results_are_not_overwritten(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "q1.json").write_text('{"keep": true}', encoding="utf-8")
    code, calls, _ = _run(monkeypatch, tmp_path, QuerySignals(semantic_query="x"))
    assert code == 0 and calls["rerank"] == []
    assert json.loads((out / "q1.json").read_text(encoding="utf-8")) == {"keep": True}


def test_script_has_no_dead_branches():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "if False" not in text and "del pool" not in text
