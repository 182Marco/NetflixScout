"""Phase 2 spike on a running Qdrant SERVER with the real 42,522 vectors (reads a Chroma COPY).

    QDRANT_URL=http://127.0.0.1:6333 python docs/qdrant_migration/spike_server.py \
        --chroma-dir COPY --baseline DIR --out FILE

Uses the project's own `QdrantStore`. Creates a throwaway collection and deletes it at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402
from qdrant_client import models  # noqa: E402

from tool.rag.FromQueryEmbeddingToRes.store import StorePoint  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client  # noqa: E402


def pct(xs: list[float], p: float) -> float:
    return round(float(np.percentile(xs, p)) * 1000, 1)


def recall(got: list[str], exact: list[str], k: int) -> float:
    return len(set(got[:k]) & set(exact[:k])) / k


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma-dir", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    url = os.environ["QDRANT_URL"]
    client = open_client("server", url=url)
    name = f"spike_{uuid.uuid4().hex[:8]}"
    store = QdrantStore(client, name, IndexMeta(model="text-embedding-3-small", dimension=1536))
    out: dict = {"server_version": client.info().version, "collection": name}

    chroma = chromadb.PersistentClient(path=args.chroma_dir).get_collection("netflix_scout")
    total = chroma.count()
    t0 = time.time()
    store.create()
    for off in range(0, total, 500):
        page = chroma.get(limit=500, offset=off, include=["embeddings", "documents", "metadatas"])
        store.upsert([
            StorePoint(id=page["ids"][i], vector=page["embeddings"][i], document=page["documents"][i],
                       metadata=dict(page["metadatas"][i] or {}))
            for i in range(len(page["ids"]))
        ])
    out["load_s"] = round(time.time() - t0, 1)
    # wait until the HNSW index covers every vector
    t1 = time.time()
    while True:
        info = client.get_collection(name)
        if info.status == models.CollectionStatus.GREEN and (info.indexed_vectors_count or 0) >= total:
            break
        if time.time() - t1 > 600:
            out["index_wait"] = "timeout"
            break
        time.sleep(2)
    out["indexing_wait_s"] = round(time.time() - t1, 1)
    info = client.get_collection(name)
    out["count"] = store.count()
    out["status"] = str(info.status)
    out["indexed_vectors"] = info.indexed_vectors_count
    store.check_meta()

    base = Path(args.baseline)
    recs = {p.stem: json.loads(p.read_text()) for p in sorted(base.glob("q??.json"))}
    vecs = {k: np.load(base / f"{k}.vec.npy").tolist() for k in recs}

    def run(params: models.SearchParams | None, flt=None):
        r10, r50, lat = [], [], []
        for k, rec in recs.items():
            exact = [r["id"] for r in rec["exact_top50"]]
            t = time.perf_counter()
            pts = client.query_points(name, query=vecs[k], limit=50, with_payload=["legacy_id"],
                                      search_params=params, query_filter=flt).points
            lat.append(time.perf_counter() - t)
            got = [p.payload["legacy_id"] for p in pts]
            r10.append(recall(got, exact, 10))
            r50.append(recall(got, exact, 50))
        return {"recall10_min": min(r10), "recall10_mean": round(float(np.mean(r10)), 4),
                "recall50_min": min(r50), "recall50_mean": round(float(np.mean(r50)), 4),
                "latency_ms": {"p50": pct(lat, 50), "p95": pct(lat, 95)}}

    out["hnsw_default"] = run(None)
    out["hnsw_ef128"] = run(models.SearchParams(hnsw_ef=128))
    out["hnsw_ef256"] = run(models.SearchParams(hnsw_ef=256))
    out["exact_true"] = run(models.SearchParams(exact=True))

    # recommend: same examples as the embedded spike
    pos = [vecs["q13"], vecs["q14"]]
    neg = [vecs["q15"]]
    for strategy in ("average_vector", "best_score"):
        for label, params in (("default", None), ("ef128", models.SearchParams(hnsw_ef=128)),
                              ("exact", models.SearchParams(exact=True))):
            ts, rows = [], []
            for _ in range(8):
                t = time.perf_counter()
                found = client.query_points(
                    name,
                    query=models.RecommendQuery(recommend=models.RecommendInput(
                        positive=pos, negative=neg, strategy=models.RecommendStrategy(strategy))),
                    limit=10, with_payload=["title", "legacy_id"], search_params=params).points
                ts.append(time.perf_counter() - t)
                rows = found
            out[f"recommend_{strategy}_{label}"] = {
                "p50_ms": pct(ts, 50), "top5": [p.payload["title"] for p in rows[:5]],
                "ids": [p.payload["legacy_id"] for p in rows]}
    for strategy in ("average_vector", "best_score"):
        approx = out[f"recommend_{strategy}_default"]["ids"]
        exact = out[f"recommend_{strategy}_exact"]["ids"]
        out[f"recommend_{strategy}_recall10_default_vs_exact"] = recall(approx, exact, 10)
        out[f"recommend_{strategy}_recall10_ef128_vs_exact"] = recall(
            out[f"recommend_{strategy}_ef128"]["ids"], exact, 10)
    for k in list(out):
        if k.startswith("recommend_") and isinstance(out[k], dict):
            out[k].pop("ids", None)

    # filtered queries (payload indexes created by store.create)
    flt = models.Filter(must=[models.FieldCondition(
        key="release_year_int", range=models.Range(gte=1949, lte=1951))])
    ts = []
    for _ in range(8):
        t = time.perf_counter()
        client.query_points(name, query=vecs["q05"], limit=50, query_filter=flt)
        ts.append(time.perf_counter() - t)
    out["query_int_range_filter_ms"] = {"p50": pct(ts, 50), "p95": pct(ts, 95)}
    filt_exact = [p.id for p in client.query_points(
        name, query=vecs["q05"], limit=50, query_filter=flt,
        search_params=models.SearchParams(exact=True)).points]
    filt_hnsw = [p.id for p in client.query_points(name, query=vecs["q05"], limit=50, query_filter=flt).points]
    out["filtered_recall50_vs_exact"] = recall(filt_hnsw, filt_exact, 50)
    ts = []
    for _ in range(8):
        t = time.perf_counter()
        hits = store.find_by_title("Casablanca")
        ts.append(time.perf_counter() - t)
    out["find_by_title_ms"] = {"p50": pct(ts, 50), "hits": [(h["title"], h["release_year"]) for h in hits]}
    homonyms = store.find_by_title("Alien")
    out["find_by_title_alien"] = [(h["title"], h["release_year"]) for h in homonyms]

    # concurrency: several clients/threads at once
    def worker(i: int) -> list[float]:
        c = open_client("server", url=url)
        lat = []
        for k in list(recs)[: 14]:
            t = time.perf_counter()
            c.query_points(name, query=vecs[k], limit=50, with_payload=True)
            lat.append(time.perf_counter() - t)
        c.close()
        return lat

    for n in (1, 4, 8):
        t = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as pool:
            lats = [x for part in pool.map(worker, range(n)) for x in part]
        wall = time.perf_counter() - t
        out[f"concurrency_{n}_clients"] = {"queries": len(lats), "wall_s": round(wall, 2),
                                           "qps": round(len(lats) / wall, 1),
                                           "latency_ms": {"p50": pct(lats, 50), "p95": pct(lats, 95)}}

    # full scroll (BM25 source)
    t = time.time()
    n = sum(1 for _ in store.scroll(5000))
    out["full_scroll"] = {"points": n, "seconds": round(time.time() - t, 1)}

    # vector validation rule from protocol.md (qdrant == chroma / ||chroma||, inf-norm)
    sample = list(range(0, total, 1500))
    ids = chroma.get(limit=total, include=[])["ids"]
    chosen = [ids[i] for i in sample]
    ch = chroma.get(ids=chosen, include=["embeddings"])
    worst = 0.0
    for i, cid in enumerate(ch["ids"]):
        c_vec = np.asarray(ch["embeddings"][i], dtype=np.float32)
        c_vec = c_vec / np.linalg.norm(c_vec)
        q_vec = np.asarray(store.vector_of(cid), dtype=np.float32)
        worst = max(worst, float(np.abs(c_vec - q_vec).max()))
    out["vector_validation"] = {"sample": len(chosen), "max_abs_diff_vs_normalised_chroma": worst,
                                "tolerance": 1e-6, "ok": worst <= 1e-6}

    client.delete_collection(name)
    out["collection_deleted"] = not client.collection_exists(name)
    client.close()
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
