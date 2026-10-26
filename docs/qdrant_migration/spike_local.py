"""Phase 2 spike: Qdrant embedded on the real 42,522 vectors. Reads only the Chroma COPY."""
from __future__ import annotations

import json
import re
import resource
import shutil
import sys
import time
import unicodedata
import uuid
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/filippo.milzagmail.com/Desktop/NetflixScout")
import chromadb  # noqa: E402  (spike venv has chromadb installed separately)
from qdrant_client import QdrantClient, models  # noqa: E402
import qdrant_client  # noqa: E402

S = Path("/private/tmp/claude-501/-Users-filippo-milzagmail-com-Desktop-NetflixScout/5bfd1d87-098f-47f2-91bf-6c2ea5a37f18/scratchpad")
CHROMA = S / "work" / "chroma_openai"
STORE = S / "spike" / "qdrant_store"
BASE = S / "baseline"
NS = uuid.UUID("6f1c2e1e-0c53-4b57-9d1a-4f5d3c1e7a10")
COLL = "netflix_scout"


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # macOS: bytes


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t).strip()
    t = re.sub(r"^(the|a|an) ", "", t)
    return re.sub(r"\s+", " ", t)


def year_int(y):
    return int(y) if y and re.fullmatch(r"\d{4}", y) and 1850 <= int(y) <= 2100 else None


def pct(xs, p):
    return float(np.percentile(xs, p)) * 1000


def main() -> None:
    out: dict = {"qdrant_client": qdrant_client.__version__ if hasattr(qdrant_client, "__version__") else "?"}
    if STORE.exists():
        shutil.rmtree(STORE)  # spike store only, inside the scratchpad
    STORE.parent.mkdir(parents=True, exist_ok=True)

    # ---- ingest from the Chroma copy
    chroma = chromadb.PersistentClient(path=str(CHROMA)).get_collection(COLL)
    total = chroma.count()
    t0 = time.time()
    client = QdrantClient(path=str(STORE))
    client.create_collection(COLL, vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE))
    legacy_ids: list[str] = []
    for off in range(0, total, 1000):
        page = chroma.get(limit=1000, offset=off, include=["embeddings", "documents", "metadatas"])
        pts = []
        for i, lid in enumerate(page["ids"]):
            md = dict(page["metadatas"][i] or {})
            payload = {**md, "document": page["documents"][i], "legacy_id": lid,
                       "title_norm": norm_title(md.get("title", ""))}
            yi = year_int(md.get("release_year"))
            if yi is not None:
                payload["release_year_int"] = yi
            pts.append(models.PointStruct(id=str(uuid.uuid5(NS, lid)), vector=page["embeddings"][i], payload=payload))
            legacy_ids.append(lid)
        client.upsert(COLL, pts)
    out["ingest_s"] = round(time.time() - t0, 1)
    out["count_after_ingest"] = client.count(COLL).count
    out["peak_rss_mb_after_ingest"] = round(rss_mb())
    client.close()
    out["store_size_mb"] = round(sum(p.stat().st_size for p in STORE.rglob("*") if p.is_file()) / 1e6)

    # ---- reopen from disk
    t0 = time.time()
    client = QdrantClient(path=str(STORE))
    out["open_s"] = round(time.time() - t0, 2)
    out["count_reopen"] = client.count(COLL).count

    # ---- lock: a second client on the same path
    try:
        QdrantClient(path=str(STORE))
        out["second_client_same_path"] = "ALLOWED (no lock)"
    except Exception as exc:  # noqa: BLE001
        out["second_client_same_path"] = f"{type(exc).__name__}: {str(exc)[:120]}"

    # ---- queries from the baseline
    recs = {p.stem: json.loads(p.read_text()) for p in sorted(BASE.glob("q??.json"))}
    vecs = {k: np.load(BASE / f"{k}.vec.npy") for k in recs}
    lat_normal, lat_avg, lat_best, rec10, rec50 = [], [], [], [], []
    for k, rec in recs.items():
        v = vecs[k].tolist()
        t = time.perf_counter()
        res = client.query_points(COLL, query=v, limit=50, with_payload=["legacy_id"]).points
        lat_normal.append(time.perf_counter() - t)
        got = [p.payload["legacy_id"] for p in res]
        exact = [r["id"] for r in rec["exact_top50"]]
        rec10.append(len(set(got[:10]) & set(exact[:10])) / 10)
        rec50.append(len(set(got) & set(exact)) / 50)
    out["normal_latency_ms"] = {"p50": round(pct(lat_normal, 50), 1), "p95": round(pct(lat_normal, 95), 1)}
    out["recall_vs_exact_local"] = {"r10_min": min(rec10), "r10_mean": round(float(np.mean(rec10)), 4),
                                    "r50_min": min(rec50), "r50_mean": round(float(np.mean(rec50)), 4)}

    # ---- positive/negative: positive = text vector of q13 (Matrix-like) + q14, negative = q15 vector
    def titles(points):
        return [p.payload.get("title") for p in points]

    pos = [vecs["q13"].tolist(), vecs["q14"].tolist()]
    neg = [vecs["q15"].tolist()]
    for strategy, bucket in ((models.RecommendStrategy.AVERAGE_VECTOR, lat_avg), (models.RecommendStrategy.BEST_SCORE, lat_best)):
        ts = []
        for _ in range(5):
            t = time.perf_counter()
            r = client.query_points(
                COLL,
                query=models.RecommendQuery(recommend=models.RecommendInput(positive=pos, negative=neg, strategy=strategy)),
                limit=10, with_payload=["title", "legacy_id"],
            ).points
            ts.append(time.perf_counter() - t)
        out[f"recommend_{strategy.value}"] = {"p50_ms": round(pct(ts, 50), 1), "top5": titles(r)[:5],
                                              "scores": [round(p.score, 4) for p in r[:3]]}
    # average_vector equals the manual formula 2*avg_pos - avg_neg, searched normally
    avg_pos = np.mean(np.array(pos), axis=0)
    avg_neg = np.mean(np.array(neg), axis=0)
    manual = (2 * avg_pos - avg_neg)
    m = client.query_points(COLL, query=manual.tolist(), limit=10, with_payload=["legacy_id"]).points
    a = client.query_points(
        COLL,
        query=models.RecommendQuery(recommend=models.RecommendInput(positive=pos, negative=neg)),
        limit=10, with_payload=["legacy_id"]).points
    out["average_vector_matches_manual_formula"] = [p.payload["legacy_id"] for p in m] == [p.payload["legacy_id"] for p in a]
    out["average_vector_score_semantics"] = {"manual_top3": [round(p.score, 4) for p in m[:3]],
                                             "recommend_top3": [round(p.score, 4) for p in a[:3]]}

    # ---- recommend by point id: the reference point itself is excluded?
    one = client.scroll(COLL, scroll_filter=models.Filter(must=[models.FieldCondition(
        key="title_norm", match=models.MatchValue(value="casablanca"))]), limit=5, with_payload=["title", "release_year"])[0]
    out["scroll_title_norm_casablanca"] = [(p.payload["title"], p.payload.get("release_year")) for p in one]
    rid = one[0].id
    by_id = client.query_points(COLL, query=models.RecommendQuery(recommend=models.RecommendInput(positive=[rid])),
                                limit=10, with_payload=["title"]).points
    out["recommend_by_id_excludes_self"] = rid not in [p.id for p in by_id]
    raw_vec = client.retrieve(COLL, ids=[rid], with_vectors=True)[0].vector
    by_raw = client.query_points(COLL, query=models.RecommendQuery(recommend=models.RecommendInput(positive=[raw_vec])),
                                 limit=10, with_payload=["title"]).points
    out["recommend_by_raw_vector_contains_self"] = rid in [p.id for p in by_raw]

    # ---- filters: Range on integer year, must_not on movie_id, string year Range (expect no match)
    flt = models.Filter(must=[models.FieldCondition(key="release_year_int", range=models.Range(gte=1949, lte=1951))])
    r = client.query_points(COLL, query=vecs["q05"].tolist(), query_filter=flt, limit=5, with_payload=["title", "release_year"]).points
    out["range_int_year_1949_1951"] = [(p.payload["title"], p.payload["release_year"]) for p in r]
    flt_str = models.Filter(must=[models.FieldCondition(key="release_year", range=models.Range(gte=1949, lte=1951))])
    r2 = client.query_points(COLL, query=vecs["q05"].tolist(), query_filter=flt_str, limit=5).points
    out["range_on_string_year_results"] = len(r2)
    ts = []
    for _ in range(5):
        t = time.perf_counter()
        client.scroll(COLL, scroll_filter=models.Filter(must=[models.FieldCondition(
            key="title_norm", match=models.MatchValue(value="the matrix".replace("the ", "")))]), limit=10)
        ts.append(time.perf_counter() - t)
    out["scroll_filter_title_norm_ms"] = {"p50": round(pct(ts, 50), 1)}
    ts = []
    for _ in range(5):
        t = time.perf_counter()
        client.query_points(COLL, query=vecs["q05"].tolist(), query_filter=flt, limit=50)
        ts.append(time.perf_counter() - t)
    out["query_with_int_range_filter_ms"] = {"p50": round(pct(ts, 50), 1)}

    # ---- payload index / hnsw params / exact are accepted but ignored locally?
    try:
        client.create_payload_index(COLL, "title_norm", models.PayloadSchemaType.KEYWORD)
        out["create_payload_index_local"] = "accepted"
    except Exception as exc:  # noqa: BLE001
        out["create_payload_index_local"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    try:
        client.query_points(COLL, query=vecs["q01"].tolist(), limit=10,
                            search_params=models.SearchParams(exact=True, hnsw_ef=128))
        out["search_params_local"] = "accepted"
    except Exception as exc:  # noqa: BLE001
        out["search_params_local"] = f"{type(exc).__name__}: {str(exc)[:100]}"

    # ---- scroll over everything (BM25 index source)
    t0 = time.time()
    n, off = 0, None
    while True:
        pts, off = client.scroll(COLL, limit=5000, offset=off, with_payload=["document", "legacy_id", "title"])
        n += len(pts)
        if off is None:
            break
    out["full_scroll"] = {"points": n, "seconds": round(time.time() - t0, 1)}
    out["peak_rss_mb_final"] = round(rss_mb())

    # ---- vector equality for a sample (Chroma copy vs Qdrant)
    sample = legacy_ids[::2000]
    ch = chroma.get(ids=sample, include=["embeddings"])
    qd = client.retrieve(COLL, ids=[str(uuid.uuid5(NS, s)) for s in sample], with_vectors=True)
    qmap = {p.id: p.vector for p in qd}
    exact_eq = all(np.array_equal(np.asarray(ch["embeddings"][i], dtype=np.float32),
                                  np.asarray(qmap[str(uuid.uuid5(NS, s))], dtype=np.float32)) for i, s in enumerate(ch["ids"]))
    out["sample_vectors_bit_identical"] = exact_eq

    print(json.dumps(out, indent=1, ensure_ascii=False))
    (S / "spike" / "spike_local_result.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
