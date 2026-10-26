"""Phase 4: retrieval parity Chroma <-> Qdrant on the real index. No paid call.

    QDRANT_URL=http://127.0.0.1:6333 python docs/qdrant_migration/phase4/parity.py \
        --chroma-dir COPY --baseline DIR --out report.json

Same queries, same saved embedding vectors, same saved parser signals as the baseline capture.
The reranker is a stub that only records what it would receive: rerank QUALITY is not measured here.
Thresholds come from docs/qdrant_migration/protocol.md and are not tuned: recall@10 >= 0.95,
recall@50 >= 0.90 against the exact search, similarity tolerance 1e-4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402
from qdrant_client import models  # noqa: E402

from app import CONFIG  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes import hybrid, retrieval, vectorstore  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, SearchMode  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.rerank import _documento_per_rerank  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.runtime import _resolve_runtime_config  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store import year_int  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.collection import close_clients  # noqa: E402

R10_MIN, R50_MIN, TOL = 0.95, 0.90, 1e-4  # protocol.md, fixed before the baseline
PAGE = 5000


def load_truth(collection):
    ids, metas, parts = [], [], []
    for off in range(0, collection.count(), PAGE):
        page = collection.get(limit=PAGE, offset=off, include=["embeddings", "metadatas"])
        ids.extend(page["ids"])
        metas.extend(page["metadatas"])
        parts.append(np.asarray(page["embeddings"], dtype=np.float32))
    matrix = np.vstack(parts)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return ids, metas, matrix


def recall(got: list[str], truth: list[str], k: int) -> float:
    return len(set(got[:k]) & set(truth[:k])) / k


def compare(a: list[str], b: list[str], k: int, sim) -> dict:
    """Differences between two top-k lists, split into numerical ties and significant ones.

    protocol.md: a difference is an element leaving the top-k while another enters. Each leaving
    element is paired with the entering one of closest rank (both sorted by exact similarity);
    the swap is a tie when their similarities differ by at most TOL, otherwise significant. An
    inversion between two common elements is a tie when their similarities are within TOL.
    `set_ties`/`set_significant` count swaps (not elements).
    """
    a, b = a[:k], b[:k]
    sa, sb = set(a), set(b)
    only_a = sorted(sa - sb, key=sim, reverse=True)
    only_b = sorted(sb - sa, key=sim, reverse=True)
    set_ties = set_sig = 0
    for x, y in zip(only_a, only_b):
        if abs(sim(x) - sim(y)) <= TOL:
            set_ties += 1
        else:
            set_sig += 1
    set_sig += abs(len(only_a) - len(only_b))  # unpaired: the lists differ in size
    common = [i for i in a if i in sb]
    pos_b = {i: n for n, i in enumerate(b)}
    inv_ties = inv_sig = 0
    for x in range(len(common)):
        for y in range(x + 1, len(common)):
            if pos_b[common[x]] > pos_b[common[y]]:
                if abs(sim(common[x]) - sim(common[y])) <= TOL:
                    inv_ties += 1
                else:
                    inv_sig += 1
    return {"overlap": len(sa & sb) / k, "set_ties": set_ties, "set_significant": set_sig,
            "inversion_ties": inv_ties, "inversion_significant": inv_sig}


def agg(values: list[float]) -> dict:
    return {"mean": round(float(np.mean(values)), 4), "min": round(float(np.min(values)), 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma-dir", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    url = os.environ["QDRANT_URL"]

    chroma = chromadb.PersistentClient(path=args.chroma_dir).get_collection("netflix_scout")
    t = time.time()
    ids, metas, matrix = load_truth(chroma)
    index_of = {i: n for n, i in enumerate(ids)}
    year_of = {i: year_int((m or {}).get("release_year")) for i, m in zip(ids, metas)}
    log = {"truth_matrix": list(matrix.shape), "truth_load_s": round(time.time() - t, 1)}

    base = Path(args.baseline)
    queries = {p.stem: json.loads(p.read_text()) for p in sorted(base.glob("q??.json"))}
    vecs = {k: np.load(base / f"{k}.vec.npy") for k in queries}

    def cfg(engine: str, mode: SearchMode, exact: bool = False) -> dict:
        rag = {**CONFIG["rag"], "vectorstore": {**CONFIG["rag"]["vectorstore"], "db_dir": args.chroma_dir,
                                                  "engine": engine,
                                                  "qdrant": {"mode": "server", "url": url, "path": None,
                                                             "exact": exact}}}
        resolved = _resolve_runtime_config(rag)
        resolved["retrieval"] = {**resolved["retrieval"], "search_mode": mode}
        return resolved

    qd_cfg = cfg("qdrant", SearchMode.semantic)
    qcol = vectorstore.apri_collection("netflix_scout", store_config=qd_cfg["vectorstore"])
    client = qcol.store.client
    log["qdrant_count"], log["chroma_count"] = qcol.count(), chroma.count()

    # BM25 indexes built once (the cache key is (name, count): the engines would collide).
    from rank_bm25 import BM25Okapi

    bm25: dict[str, dict] = {}
    for engine in ("chroma", "qdrant"):
        hybrid._BM25_CACHE.clear()
        t = time.time()
        collection = vectorstore.apri_collection(
            "netflix_scout", db_dir=args.chroma_dir, store_config=cfg(engine, SearchMode.hybrid)["vectorstore"])
        index = hybrid.costruisci_indice_bm25(collection)
        bm25[engine] = {"cache": dict(hybrid._BM25_CACHE), "seconds": round(time.time() - t, 1),
                        "chunks": {c["id"]: c for c in index["chunks"]}}
    sorted_chunks = sorted(bm25["qdrant"]["chunks"].values(), key=lambda c: c["id"])
    key_ = next(iter(bm25["qdrant"]["cache"]))
    bm25["qdrant_sorted"] = {"cache": {key_: {"bm25": BM25Okapi([hybrid.tokenizza(c["testo"]) for c in sorted_chunks]),
                                              "chunks": sorted_chunks}}}
    a_chunks, b_chunks = bm25["chroma"]["chunks"], bm25["qdrant"]["chunks"]
    log["bm25_index"] = {
        "chunks": [len(a_chunks), len(b_chunks)], "same_ids": a_chunks.keys() == b_chunks.keys(),
        "chunks_identical": a_chunks == b_chunks, "build_seconds": {e: bm25[e]["seconds"] for e in ("chroma", "qdrant")},
        "same_order": [c for c in a_chunks] == [c for c in b_chunks],
        "chroma_order_is_sorted_by_id": [c for c in a_chunks] == sorted(a_chunks),
        "qdrant_order_is_sorted_by_id": [c for c in b_chunks] == sorted(b_chunks)}

    per_query: dict[str, dict] = {}
    original_embed = vectorstore.embed
    original_rerank = retrieval.rerank_cohere
    captured: dict = {}

    def stub_rerank(query, chunks, model, cohere_api_client=None):
        docs = [_documento_per_rerank(c) for c in chunks]
        captured["docs"] = docs
        # order-independent on purpose: a stable function of the document text
        order = sorted(range(len(chunks)), key=lambda i: hashlib.sha256(docs[i].encode()).hexdigest())
        return [{**chunks[i], "score": float(len(chunks) - n)} for n, i in enumerate(order)]

    retrieval.rerank_cohere = stub_rerank
    try:
        for key, rec in queries.items():
            vec = vecs[key]
            unit = vec / np.linalg.norm(vec)
            sims = matrix @ unit
            sim = lambda i, s=sims: float(s[index_of[i]])  # noqa: E731
            exact = [ids[i] for i in np.argsort(-sims, kind="stable")[:50]]
            row: dict = {"query": rec["query"], "kind": rec["kind"]}

            # ---- A. raw top-50
            ch = chroma.query(query_embeddings=[vec.tolist()], n_results=50)["ids"][0]
            raw = {
                "chroma": ch,
                "chroma_baseline_file": [r["id"] for r in rec["chroma_raw_top50"]],
                "qdrant_default": [r["id"] for r in qcol.store.query(vec.tolist(), 50)],
                "qdrant_ef128": [p.payload["legacy_id"] for p in client.query_points(
                    "netflix_scout", query=vec.tolist(), limit=50, with_payload=["legacy_id"],
                    search_params=models.SearchParams(hnsw_ef=128)).points],
                "qdrant_exact": [p.payload["legacy_id"] for p in client.query_points(
                    "netflix_scout", query=vec.tolist(), limit=50, with_payload=["legacy_id"],
                    search_params=models.SearchParams(exact=True)).points],
            }
            row["raw"] = {name: {"recall10": recall(lst, exact, 10), "recall50": recall(lst, exact, 50)}
                          for name, lst in raw.items()}
            row["raw_vs_chroma"] = {name: {f"k{k}": compare(lst, ch, k, sim) for k in (10, 50)}
                                    for name, lst in raw.items() if name.startswith("qdrant")}
            row["raw_vs_exact"] = {name: {f"k{k}": compare(lst, exact, k, sim) for k in (10, 50)}
                                   for name, lst in raw.items()}
            row["chroma_now_equals_baseline_file"] = raw["chroma"] == raw["chroma_baseline_file"]

            # ---- B/C. production retrieval + rerank input, saved vectors and signals
            signals = QuerySignals(**rec["signals"])
            vectorstore.embed = lambda texts, backend=None, model=None, _v=vec: np.asarray(
                [_v] * len(texts), dtype=np.float32)

            def run_pipeline(engine: str, mode: SearchMode, bm25_key: str, exact: bool = False) -> dict:
                hybrid._BM25_CACHE.clear()
                hybrid._BM25_CACHE.update(bm25[bm25_key]["cache"])
                config = cfg(engine, mode, exact)
                pool = retrieval._retrieve(rec["query"], config, signals=signals)
                rq = retrieval.compose_rerank_query(signals, rec["query"])
                final = retrieval._rerank(rq, pool, config, signals=signals)
                return {"pool": pool, "docs": list(captured["docs"]), "final": final, "rq": rq}

            pipeline: dict = {}
            for mode in (SearchMode.semantic, SearchMode.hybrid):
                runs = {
                    "chroma": run_pipeline("chroma", mode, "chroma"),
                    "qdrant": run_pipeline("qdrant", mode, "qdrant"),
                    # reference: exact semantic search; for hybrid also Chroma's BM25 order
                    "reference_exact": run_pipeline("qdrant", mode, "chroma", exact=True),
                }
                if mode == SearchMode.hybrid:
                    runs["qdrant_sorted_bm25"] = run_pipeline("qdrant", mode, "qdrant_sorted")
                ids_of = {n: [c["id"] for c in r["pool"]] for n, r in runs.items()}
                ref = ids_of["reference_exact"]
                a, b = runs["chroma"], runs["qdrant"]
                common = {c["id"]: c for c in a["pool"]}
                entry = {
                    "pool_size": [len(ids_of["chroma"]), len(ids_of["qdrant"])],
                    "same_ids_same_order": ids_of["chroma"] == ids_of["qdrant"],
                    "metadata_identical_on_common_ids": all(
                        {k: v for k, v in c.items() if k != "score"} == {k: v for k, v in common[c["id"]].items() if k != "score"}
                        for c in b["pool"] if c["id"] in common),
                    "rerank_query_equal": a["rq"] == b["rq"],
                    "rerank_input_sets_equal": sorted(a["docs"]) == sorted(b["docs"]),
                    "final_ids_equal_with_stub": [c["id"] for c in a["final"]] == [c["id"] for c in b["final"]],
                    "chroma_pool_equals_baseline_file": ids_of["chroma"] == [r["id"] for r in rec[f"retrieve_{mode.value}"]],
                    "overlap_with_reference": {n: len(set(i) & set(ref)) / max(len(ref), 1) for n, i in ids_of.items() if n != "reference_exact"},
                    "same_as_reference": {n: i == ref for n, i in ids_of.items() if n != "reference_exact"},
                }
                if mode == SearchMode.semantic:
                    # cosine order is meaningful here: classify against both the other engine and the reference
                    entry["qdrant_vs_chroma"] = compare(ids_of["qdrant"], ids_of["chroma"], len(ids_of["chroma"]), sim)
                    entry["chroma_vs_reference"] = compare(ids_of["chroma"], ref, len(ref), sim)
                    entry["qdrant_vs_reference"] = compare(ids_of["qdrant"], ref, len(ref), sim)
                else:
                    entry["qdrant_vs_chroma_sets_only"] = {"only_chroma": sorted(set(ids_of["chroma"]) - set(ids_of["qdrant"])),
                                                            "only_qdrant": sorted(set(ids_of["qdrant"]) - set(ids_of["chroma"]))}
                pipeline[mode.value] = entry
            row["pipeline"] = pipeline
            vectorstore.embed = original_embed

            # ---- D. native Qdrant filters against the brute-force truth
            excl = {metas[index_of[i]].get("movie_id") for i in exact[:3]} - {None}
            truth_excl = [i for i in np.argsort(-sims, kind="stable")
                          if metas[i].get("movie_id") not in excl][:50]
            got_excl = [r["id"] for r in qcol.store.query(vec.tolist(), 50, exclude_movie_ids=sorted(excl))]
            ids_excl = [ids[i] for i in truth_excl]
            row["exclusion_by_movie_id"] = {
                "excluded": len(excl), "recall10": recall(got_excl, ids_excl, 10), "recall50": recall(got_excl, ids_excl, 50),
                "leaked": [i for i in got_excl if metas[index_of[i]].get("movie_id") in excl]}
            lo, hi = 1950, 1969
            allowed = np.array([year_of[i] is not None and lo <= year_of[i] <= hi for i in ids])
            truth_y = [ids[i] for i in np.argsort(-np.where(allowed, sims, -9), kind="stable")[:50] if allowed[i]]
            got_y = [p.payload["legacy_id"] for p in client.query_points(
                "netflix_scout", query=vec.tolist(), limit=50, with_payload=["legacy_id"],
                query_filter=models.Filter(must=[models.FieldCondition(
                    key="release_year_int", range=models.Range(gte=lo, lte=hi))])).points]
            row["year_range_filter"] = {"candidates": int(allowed.sum()), "recall10": recall(got_y, truth_y, 10),
                                        "recall50": recall(got_y, truth_y, 50)}
            per_query[key] = row
            sys.stdout.write(f"{key} done\n")
            sys.stdout.flush()
    finally:
        vectorstore.embed = original_embed
        retrieval.rerank_cohere = original_rerank
        close_clients()

    # ---- aggregates
    def col(path):
        out = []
        for r in per_query.values():
            v = r
            for p in path:
                v = v[p]
            out.append(v)
        return out

    summary: dict = {"raw_vs_exact": {}}
    for name in ("chroma", "qdrant_default", "qdrant_ef128", "qdrant_exact"):
        summary["raw_vs_exact"][name] = {"recall10": agg(col(["raw", name, "recall10"])),
                                         "recall50": agg(col(["raw", name, "recall50"]))}
    summary["thresholds"] = {"recall10_min": R10_MIN, "recall50_min": R50_MIN, "tolerance": TOL}
    q = summary["raw_vs_exact"]["qdrant_default"]
    below10 = [k for k, r in per_query.items() if r["raw"]["qdrant_default"]["recall10"] < R10_MIN]
    below50 = [k for k, r in per_query.items() if r["raw"]["qdrant_default"]["recall50"] < R50_MIN]
    summary["qdrant_default_threshold_check"] = {
        "recall10_mean_ok": q["recall10"]["mean"] >= R10_MIN, "recall50_mean_ok": q["recall50"]["mean"] >= R50_MIN,
        "queries_below_recall10": below10, "queries_below_recall50": below50}
    summary["qdrant_vs_chroma_raw"] = {
        f"k{k}": {"overlap": agg([r["raw_vs_chroma"]["qdrant_default"][f"k{k}"]["overlap"] for r in per_query.values()]),
                  "set_ties": sum(r["raw_vs_chroma"]["qdrant_default"][f"k{k}"]["set_ties"] for r in per_query.values()),
                  "set_significant": sum(r["raw_vs_chroma"]["qdrant_default"][f"k{k}"]["set_significant"] for r in per_query.values()),
                  "inversion_ties": sum(r["raw_vs_chroma"]["qdrant_default"][f"k{k}"]["inversion_ties"] for r in per_query.values()),
                  "inversion_significant": sum(r["raw_vs_chroma"]["qdrant_default"][f"k{k}"]["inversion_significant"] for r in per_query.values())}
        for k in (10, 50)}
    summary["chroma_now_equals_baseline_file"] = sum(col(["chroma_now_equals_baseline_file"]))
    for mode in ("semantic", "hybrid"):
        rows = [r["pipeline"][mode] for r in per_query.values()]
        d = {
            "queries": len(rows),
            "same_ids_same_order_chroma_vs_qdrant": sum(r["same_ids_same_order"] for r in rows),
            "queries_with_different_pool": [k for k, r in per_query.items() if not r["pipeline"][mode]["same_ids_same_order"]],
            "metadata_identical": sum(r["metadata_identical_on_common_ids"] for r in rows),
            "rerank_query_equal": sum(r["rerank_query_equal"] for r in rows),
            "rerank_input_sets_equal": sum(r["rerank_input_sets_equal"] for r in rows),
            "final_ids_equal_with_stub": sum(r["final_ids_equal_with_stub"] for r in rows),
            "chroma_pool_equals_baseline_file": sum(r["chroma_pool_equals_baseline_file"] for r in rows),
            "overlap_with_reference": {n: agg([r["overlap_with_reference"][n] for r in rows]) for n in rows[0]["overlap_with_reference"]},
            "identical_to_reference": {n: sum(r["same_as_reference"][n] for r in rows) for n in rows[0]["same_as_reference"]},
        }
        if mode == "semantic":
            for name in ("qdrant_vs_chroma", "chroma_vs_reference", "qdrant_vs_reference"):
                d[name] = {k: sum(r[name][k] for r in rows) for k in ("set_ties", "set_significant", "inversion_ties", "inversion_significant")}
            d["qdrant_worse_than_chroma_vs_reference"] = [
                k for k, r in per_query.items()
                if r["pipeline"]["semantic"]["overlap_with_reference"]["qdrant"] < r["pipeline"]["semantic"]["overlap_with_reference"]["chroma"]]
            d["qdrant_better_than_chroma_vs_reference"] = [
                k for k, r in per_query.items()
                if r["pipeline"]["semantic"]["overlap_with_reference"]["qdrant"] > r["pipeline"]["semantic"]["overlap_with_reference"]["chroma"]]
        summary[f"pipeline_{mode}"] = d
    summary["raw_qdrant_worse_than_chroma_vs_exact"] = {
        "recall10": [k for k, r in per_query.items() if r["raw"]["qdrant_default"]["recall10"] < r["raw"]["chroma"]["recall10"]],
        "recall50": [k for k, r in per_query.items() if r["raw"]["qdrant_default"]["recall50"] < r["raw"]["chroma"]["recall50"]]}
    summary["raw_qdrant_better_than_chroma_vs_exact"] = {
        "recall10": [k for k, r in per_query.items() if r["raw"]["qdrant_default"]["recall10"] > r["raw"]["chroma"]["recall10"]],
        "recall50": [k for k, r in per_query.items() if r["raw"]["qdrant_default"]["recall50"] > r["raw"]["chroma"]["recall50"]]}
    summary["exclusion_by_movie_id"] = {"recall10": agg(col(["exclusion_by_movie_id", "recall10"])),
                                        "recall50": agg(col(["exclusion_by_movie_id", "recall50"])),
                                        "leaks": sum(len(r["exclusion_by_movie_id"]["leaked"]) for r in per_query.values())}
    summary["year_range_filter"] = {"recall10": agg(col(["year_range_filter", "recall10"])),
                                    "recall50": agg(col(["year_range_filter", "recall50"]))}

    report = {"log": log, "summary": summary, "per_query": per_query}
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps(summary, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
