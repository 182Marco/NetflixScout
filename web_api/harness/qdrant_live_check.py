"""Manual check (like `live_stream_check.py`): a full web turn (HTTP -> SSE -> handle_query -> real
RagTool) on the REAL Qdrant server and the REAL 42,522-point index. No paid call.

    VECTORSTORE_ENGINE=qdrant VECTORSTORE_QDRANT_URL=http://127.0.0.1:6333 \
        python -m web_api.harness.qdrant_live_check --baseline DIR

What is real: the application config and `build_ready_app` checks, the Qdrant server and index,
`vectorstore.search`, constraints, `RagTool`, `handle_query`, the SSE presenters and the HTTP layer.
What is replaced by saved data: the domain classifier, the query embedding, the query-signal parser
(all OpenAI) and the Cohere reranker (an order-preserving stub: rerank QUALITY is not measured).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes import retrieval, vectorstore  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.collection import close_clients  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.tool_interface import RagTool  # noqa: E402
from turn import STEP_QUERY_REWRITE, STEP_TOOL_OUTCOME, STEP_TOOL_SELECTION, TraceStep  # noqa: E402
from web_api import create_app  # noqa: E402
from web_api.settings import WebApiSettings  # noqa: E402

OUT_DEFAULT = ROOT / "docs" / "qdrant_migration" / "phase6" / "qdrant_live_check_result.json"


def parse_sse(text: str) -> list[tuple[int, str, dict]]:
    events = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return events


def stream_rag_turn(observer, query: str, result: dict) -> None:
    """The steps `LLMOrchestrator.run` emits for one tool call, in the same order."""
    observer.step(TraceStep(kind=STEP_QUERY_REWRITE, title="Query usata dai tool",
                            data={"original": query, "used": query, "rewritten": False}))
    observer.step(TraceStep(kind=STEP_TOOL_SELECTION, title="Tool scelto",
                            data={"tool": "rag_search", "purpose": query, "arguments": {}}))
    observer.step(TraceStep(kind=STEP_TOOL_OUTCOME, title="Esito",
                            data={"tool": "rag_search", "elapsed_ms": 0, **result["outcome"]}))
    for step in result["trace"]:
        observer.step(TraceStep(**step))

CASES = ("q03", "q10", "q13", "q21")


class RagOrchestrator:
    """Streams like `LLMOrchestrator.run`, with the real `RagTool` as its tool."""

    def __init__(self, rag_tool: RagTool) -> None:
        self.rag_tool = rag_tool

    def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, final_output=None):
        result = self.rag_tool.run(query=query, params={}, conversation_history=conversation_history)
        decision = {"tool": "rag_search", "tools": ["rag_search"],
                    "calls": [{"tool": "rag_search", "arguments": {}, "result": result}],
                    "standalone_query": query, "result": result, "final_lists": []}
        stream_rag_turn(observer, query, result)
        answer = "Dal catalogo: " + "; ".join(f"{c['title']} ({c.get('release_year') or '?'})" for c in result["chunks"]) + "."
        for i in range(0, len(answer), 12):
            observer.answer_delta(answer[i:i + 12])
        return {**decision, "final_answer": answer}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()
    base = Path(args.baseline)

    ready = app_module.build_ready_app()  # the same startup checks as `python app.py` and the web API
    engine = ready["config"]["rag"]["vectorstore"]["engine"]
    if engine != "qdrant":
        raise SystemExit(f"refused: engine is {engine!r}; set VECTORSTORE_ENGINE=qdrant (this smoke must not open Chroma)")
    bot = {"config": ready["config"], "orchestrator": RagOrchestrator(RagTool(config=ready["config"]["rag"]))}

    state: dict = {}
    app_module.classify_query_domain = lambda q, history=None: {"is_cinema": True, "is_italian": True}
    vectorstore.embed = lambda texts, backend=None, model=None: np.array([state["vec"]], dtype=np.float32)
    retrieval._extract_query_signals = lambda query, llm_model, hint=None: QuerySignals(**state["signals"])
    retrieval.rerank_cohere = lambda query, chunks, model, cohere_api_client=None: [
        {**c, "score": 1.0 - n / 100} for n, c in enumerate(chunks)]

    results = []
    with TestClient(create_app(WebApiSettings(), bot, client=object())) as client:  # type: ignore[arg-type]
        for key in CASES:
            rec = json.loads((base / f"{key}.json").read_text())
            state["vec"] = np.load(base / f"{key}.vec.npy")
            state["signals"] = rec["signals"]
            conversation = client.post("/conversations").json()["conversation_id"]
            t0 = time.perf_counter()
            response = client.post(f"/conversations/{conversation}/messages", json={"content": rec["query"]})
            elapsed = time.perf_counter() - t0
            events = parse_sse(response.text)
            names = lambda evs: [n for _, n, _ in evs]  # noqa: E731
            steps = [d for _, n, d in events if n == "step"]
            retrieval_step = next(s for s in steps if s["kind"] == "retrieval")
            pool = [c["id"] for c in retrieval_step["chunks"]]
            baseline_pool = [r["id"] for r in rec["retrieve_semantic"]]
            end = next(d for _, n, d in events if n == "answer_end")
            results.append({
                "query_id": key, "query": rec["query"], "http": response.status_code,
                "events": names(events)[:1] + ["..."] + names(events)[-3:], "n_events": len(events),
                "step_kinds": [s["kind"] for s in steps], "tool": end["tool"], "blocked": end["blocked"],
                "answer": "".join(d["text"] for _, n, d in events if n == "answer_delta"), "seconds": round(elapsed, 2),
                "pool_equals_chroma_baseline": pool == baseline_pool,
                "pool_overlap_with_chroma_baseline": len(set(pool) & set(baseline_pool)) / max(len(baseline_pool), 1),
            })
            print(f"{key}: HTTP {response.status_code}, {len(events)} events, steps {results[-1]['step_kinds']}, "
                             f"pool==Chroma baseline: {results[-1]['pool_equals_chroma_baseline']}\n  {results[-1]['answer']}")
    close_clients()
    Path(args.out).write_text(json.dumps({"engine": engine, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
