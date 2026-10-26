"""Capture the Chroma retrieval baseline for the Qdrant migration (one JSON per query).

Reads a COPY of the Chroma index (never `dbVettoriale/`). Per query it records:
signals (OpenAI parser), the embedded query vector, the engine-independent exact top-50
(brute force on the stored vectors), Chroma's own top-50, the production retrieval for
`semantic` and `hybrid`, and (with --cohere) the reranked final top-k.

    python docs/qdrant_migration/capture_baseline.py --chroma-dir DIR --out DIR [--cohere]

Resumable: queries whose JSON already exists are skipped.
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

from app import CONFIG  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes import retrieval, vectorstore  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.embeddings import embed  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.models import SearchMode  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.runtime import _resolve_runtime_config  # noqa: E402

PAGE = 5000
POOL = 50


def load_matrix(collection) -> tuple[list[str], np.ndarray]:
    ids: list[str] = []
    parts: list[np.ndarray] = []
    total = collection.count()
    for offset in range(0, total, PAGE):
        page = collection.get(limit=PAGE, offset=offset, include=["embeddings"])
        ids.extend(page["ids"])
        parts.append(np.asarray(page["embeddings"], dtype=np.float32))
    matrix = np.vstack(parts)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return ids, matrix


def rows(chunks: list[dict]) -> list[dict]:
    return [{"id": c["id"], "score": float(c["score"]), "title": c.get("title")} for c in chunks]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--queries", default=str(Path(__file__).with_name("queries.json")))
    parser.add_argument("--cohere", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))

    base = {**CONFIG["rag"], "vectorstore": {**CONFIG["rag"]["vectorstore"], "db_dir": args.chroma_dir}}
    config = _resolve_runtime_config(base)
    collection = vectorstore.apri_collection(
        config["vectorstore"]["collection"], db_dir=config["vectorstore"]["db_dir"]
    )
    print(f"collection count: {collection.count()}", flush=True)
    ids, matrix = load_matrix(collection)
    print(f"exact matrix: {matrix.shape}", flush=True)

    model = config["embedding"]["model"]
    backend = config["embedding"]["backend"]

    for item in queries:
        target = out / f"{item['id']}.json"
        if target.exists():
            continue
        query = item["query"]
        signals = retrieval._build_signal_aware_query(query, config)
        if not signals.semantic_query:
            print(f"{item['id']}: EMPTY semantic_query (parser failed?) - stopping", flush=True)
            return 1
        text = signals.semantic_query
        vector = embed([text], backend=backend, model=model)[0]
        unit = vector / np.linalg.norm(vector)
        np.save(out / f"{item['id']}.vec.npy", vector)

        sims = matrix @ unit
        order = np.argsort(-sims, kind="stable")[:POOL]
        exact = [{"id": ids[i], "score": float(sims[i])} for i in order]

        raw = collection.query(query_embeddings=[vector.tolist()], n_results=POOL)
        chroma_raw = [
            {"id": raw["ids"][0][i], "score": 1 - raw["distances"][0][i]}
            for i in range(len(raw["ids"][0]))
        ]

        record: dict = {
            **item,
            "signals": signals.model_dump(),
            "embedded_text": text,
            "exact_top50": exact,
            "chroma_raw_top50": chroma_raw,
        }

        # Production retrieval, with the embedding call replaced by the saved vector.
        original_embed = vectorstore.embed
        vectorstore.embed = lambda texts, backend=None, model=None, _v=vector: np.asarray(
            [_v] * len(texts), dtype=np.float32
        )
        full: dict[str, list[dict]] = {}
        try:
            for mode in (SearchMode.semantic, SearchMode.hybrid):
                cfg = {**config, "retrieval": {**config["retrieval"], "search_mode": mode}}
                full[mode.value] = retrieval._retrieve(query, cfg, signals=signals)
                record[f"retrieve_{mode.value}"] = rows(full[mode.value])
        finally:
            vectorstore.embed = original_embed

        if args.cohere:
            rerank_query = retrieval.compose_rerank_query(signals, query)
            final = retrieval._rerank(rerank_query, full["semantic"], config, signals=signals)
            record["rerank_query"] = rerank_query
            record["final_top"] = rows(final)
            time.sleep(7)  # Cohere trial: 10 calls/min

        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{item['id']}: ok", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
