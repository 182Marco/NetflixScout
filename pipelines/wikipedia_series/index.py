"""Phase S8: the Qdrant collection `wikipedia_series_it_v1` (one point per embedded unit) and its verification.

A NEW collection: the film collections and `netflix_scout` are only read (count + digest of ids) to prove they were not touched.
No embedding is requested here: the vectors come from `data/s7/shards` (see `embed.py`).

    python -m pipelines.wikipedia_series.index plan     # offline: expected points per type and what exists
    python -m pipelines.wikipedia_series.index build    # creates the collection (refuses if it exists) and upserts every point
    python -m pipelines.wikipedia_series.index check    # every point against its record and its vector; other collections intact
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import unicodedata
import re
import uuid

import numpy as np
from qdrant_client import QdrantClient, models

from . import embed as E
from .build_relations import read
from .common import DATA_DIR
from tool.rag.series.retrieval import base_title_norm

COLLECTION = "wikipedia_series_it_v1"
URL = "http://127.0.0.1:6333"
NAMESPACE = uuid.UUID("5d0f4a9e-3c71-4b86-8e2a-71c9b1d4f6a3")   # fixed forever; different from the film namespace
PROTECTED = ("netflix_scout", "wikipedia_films_it", "wikipedia_films_it_v2", "wikipedia_films_it_v3")
S5 = DATA_DIR / "s5"
REPORT = E.OUT / "index_report.json"
BATCH = 256
KW, INT, BOOL = models.PayloadSchemaType.KEYWORD, models.PayloadSchemaType.INTEGER, models.PayloadSchemaType.BOOL
INDEXES = [("entity_type", KW), ("subtype", KW), ("series_id", KW), ("season_id", KW), ("season_number", INT),
           ("episode_number", INT), ("year", INT), ("default_search_eligible", BOOL), ("catalog_class", KW),
           ("ids_reliable", BOOL), ("text_kind", KW), ("title_norm", KW), ("original_title_norm", KW),
           ("series_title_norm", KW), ("title_base_norm", KW), ("country", KW), ("genres_norm", KW), ("imdb_id", KW), ("record_id", KW),
           ("flags", KW), ("network_norm", KW)]
TEXT = models.TextIndexParams(type=models.TextIndexType.TEXT, tokenizer=models.TokenizerType.WORD, min_token_len=2,
                              max_token_len=30, lowercase=True, ascii_folding=True)
TEXT_FIELDS = ("plot_text", "cast", "creators", "director")


def norm(t) -> str:
    s = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


def point_id(record_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, record_id))


def records() -> dict[str, dict]:
    out = {}
    for name in ("series", "seasons", "episodes", "tv_movies"):
        for r in read(S5 / f"{name}.jsonl"):
            out[r["record_id"]] = r
    return out


def build_payload(rec: dict, unit: E.Unit) -> dict:
    p = {k: v for k, v in rec.items() if k not in ("lead_text",)}
    p["lead_text"] = rec.get("lead_text") or ""
    ids = rec.get("ids") or {}
    p.update({
        "unit_id": unit.unit_id, "embedded_text_kind": rec.get("text_kind"), "title_norm": norm(rec.get("title")),
        "original_title_norm": norm(rec.get("original_title")), "title_base_norm": base_title_norm(rec.get("title")), "series_title_norm": norm(rec.get("series_title")),
        "genres_norm": [norm(g) for g in rec.get("genres") or []], "imdb_id": ids.get("imdb_id"),
        "network_norm": norm(rec.get("network")),
        "default_search_eligible": rec.get("default_search_eligible", True) if rec["entity_type"] in ("series", "tv_movie") else True,
    })
    if rec["entity_type"] == "episode":
        p["text_embedded_prefix"] = unit.text.split("\n", 1)[0]
    return p


def client() -> QdrantClient:
    return QdrantClient(url=URL, timeout=180)


def digest(c: QdrantClient, name: str) -> dict:
    ids, off = [], None
    while True:
        pts, off = c.scroll(name, limit=5000, offset=off, with_payload=False, with_vectors=False)
        ids += [str(p.id) for p in pts]
        if off is None:
            break
    return {"count": len(ids), "sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()}


def plan() -> dict:
    units = E.read_units()
    c = client()
    names = {x.name for x in c.get_collections().collections}
    by = {}
    for u in units:
        by[u.entity_type] = by.get(u.entity_type, 0) + 1
    return {"collection": COLLECTION, "exists": COLLECTION in names, "expected_points": len(units), "by_type": by}


def build() -> dict:
    assert COLLECTION not in PROTECTED
    units, recs = E.read_units(), records()
    missing = [u.unit_id for u in units if u.unit_id not in recs]
    if missing:
        raise SystemExit(f"{len(missing)} units without a record, e.g. {missing[:3]}")
    vec = E.load_all(units)          # raises if a shard is missing: this module never calls the embedding API
    if not np.isfinite(vec).all() or vec.shape != (len(units), E.DIMENSIONS):
        raise SystemExit("invalid vectors")
    c = client()
    if COLLECTION in {x.name for x in c.get_collections().collections}:
        raise SystemExit(f"{COLLECTION} already exists: refusing to touch it")
    before = {n: digest(c, n) for n in PROTECTED}
    t0 = time.time()
    c.create_collection(COLLECTION, vectors_config=models.VectorParams(size=E.DIMENSIONS, distance=models.Distance.COSINE),
                        on_disk_payload=True)
    for f, s in INDEXES:
        c.create_payload_index(COLLECTION, f, s)
    for f in TEXT_FIELDS:
        c.create_payload_index(COLLECTION, f, TEXT)
    for i in range(0, len(units), BATCH):
        b = units[i:i + BATCH]
        c.upsert(COLLECTION, wait=True, points=[
            models.PointStruct(id=point_id(u.unit_id), vector=vec[i + k].tolist(), payload=build_payload(recs[u.unit_id], u))
            for k, u in enumerate(b)])
    while not str(c.get_collection(COLLECTION).status).lower().endswith("green"):
        time.sleep(2)
    after = {n: digest(c, n) for n in PROTECTED}
    res = {"collection": COLLECTION, "points": c.count(COLLECTION, exact=True).count, "expected": len(units),
           "protected_before": before, "protected_after": after, "protected_untouched": before == after,
           "seconds": round(time.time() - t0, 1)}
    E.OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(res, indent=1))
    res["ok"] = res["points"] == res["expected"] and res["protected_untouched"]
    return res


def patch_title_base() -> dict:
    """Adds `title_base_norm` (payload only, no vector touched) to a collection built before the field existed. Idempotent."""
    assert COLLECTION not in PROTECTED
    units, recs = E.read_units(), records()
    c = client()
    c.create_payload_index(COLLECTION, "title_base_norm", KW)
    ops = [models.SetPayloadOperation(set_payload=models.SetPayload(payload={"title_base_norm": base_title_norm(recs[u.unit_id].get("title"))},
                                                                    points=[point_id(u.unit_id)])) for u in units]
    for i in range(0, len(ops), 1000):
        c.batch_update_points(COLLECTION, ops[i:i + 1000], wait=True)
    return {"patched": len(ops), "ok": True}


def check() -> dict:
    units, recs = E.read_units(), records()
    vec = E.load_all(units)
    c = client()
    info = c.get_collection(COLLECTION)
    mism = {"missing": 0, "vector": 0, "payload": 0}
    ids = [point_id(u.unit_id) for u in units]
    for i in range(0, len(units), 500):
        got = {str(p.id): p for p in c.retrieve(COLLECTION, ids=ids[i:i + 500], with_payload=True, with_vectors=True)}
        for k, u in enumerate(units[i:i + 500]):
            p = got.get(ids[i + k])
            if p is None:
                mism["missing"] += 1
                continue
            want = vec[i + k] / np.linalg.norm(vec[i + k])
            if not np.allclose(np.asarray(p.vector, dtype=np.float32), want, atol=1e-6):
                mism["vector"] += 1
            r = recs[u.unit_id]
            if any(p.payload.get(f) != r.get(f) for f in ("record_id", "entity_type", "title", "year", "series_id", "season_number",
                                                          "episode_number", "plot_text", "wikipedia_url")) or p.payload.get("title_base_norm") != base_title_norm(r.get("title")):
                mism["payload"] += 1
    present, off = [], None
    while True:
        pts, off = c.scroll(COLLECTION, limit=5000, offset=off, with_payload=["record_id"], with_vectors=False)
        present += [p.payload["record_id"] for p in pts]
        if off is None:
            break
    flt = lambda k, v: c.count(COLLECTION, count_filter=models.Filter(must=[models.FieldCondition(key=k, match=models.MatchValue(value=v))]), exact=True).count
    by = {t: flt("entity_type", t) for t in ("series", "season", "episode", "tv_movie")}
    expected_by = {}
    for u in units:
        expected_by[u.entity_type] = expected_by.get(u.entity_type, 0) + 1
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    now = {n: digest(c, n) for n in PROTECTED}
    out = {"points": c.count(COLLECTION, exact=True).count, "units": len(units), "distinct_record_ids": len(set(present)),
           "duplicates": len(present) - len(set(present)), "ids_equal_units": set(present) == {u.unit_id for u in units},
           "by_type": by, "expected_by_type": expected_by, "mismatches_every_point": mism,
           "vector_size": info.config.params.vectors.size, "distance": str(info.config.params.vectors.distance),
           "status": str(info.status), "protected_untouched": report.get("protected_before") == now,
           "logical_seasons_present": c.count(COLLECTION, count_filter=models.Filter(must=[models.FieldCondition(
               key="logical", match=models.MatchValue(value=True))]), exact=True).count}
    out["ok"] = bool(out["points"] == out["units"] == out["distinct_record_ids"] and not out["duplicates"] and out["ids_equal_units"]
                     and by == expected_by and not any(mism.values()) and out["vector_size"] == E.DIMENSIONS
                     and "cosine" in out["distance"].lower() and out["protected_untouched"] and out["logical_seasons_present"] == 0)
    return out


def main(argv: list[str]) -> int:
    fn = {"plan": plan, "build": build, "check": check, "patch-title-base": patch_title_base}.get(argv[0] if argv else "plan")
    if not fn:
        print(__doc__); return 2
    res = fn()
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
