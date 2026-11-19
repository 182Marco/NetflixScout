"""Phase 7: the clean catalogue as a NEW collection, `wikipedia_films_it_v2`. The existing `wikipedia_films_it` and `netflix_scout`
are only read (point counts and an id digest, before and after).

    python -m pipelines.wikipedia_films.indexing.v2 plan        # what is reused and what must be embedded (no API call)
    python -m pipelines.wikipedia_films.indexing.v2 embed       # embeds ONLY the units whose text changed (hard cap MAX_USD_V2)
    python -m pipelines.wikipedia_films.indexing.v2 index       # creates and fills the v2 collection (refuses if it already exists)
    python -m pipelines.wikipedia_films.indexing.v2 check       # source ↔ embeddings ↔ Qdrant, exclusions, filters, old collections untouched

Vectors are never recomputed when the text of a unit is the same as in the verified Phase 3 shards (same film_id, same text hash)."""
from __future__ import annotations

import hashlib
import json
import sys
import time

import numpy as np
from qdrant_client import models

from . import settings as S
from .embed_run import _Pause, _request, usd
from .qdrant_index import build_index, check_index, create_collection, make_client, point_id
from .units import Unit, units_for
from .verify_embeddings import load_all

V2 = S.COLLECTION_V2
CLEAN = S.ROOT / "data" / "clean" / "films.clean.jsonl"
DATA_V2 = S.ROOT / "data" / "embeddings" / (S.RUN_ID + "-v2")
NEW_VECTORS = DATA_V2 / "new_vectors.npz"
REPORT = DATA_V2 / "v2_report.json"
MAX_USD_V2 = 0.01          # the owner's cap for this step
OLD_COLLECTIONS = ("netflix_scout", S.COLLECTION)
EXTRA_INDEXES = [("catalog_status", models.PayloadSchemaType.KEYWORD), ("unverified", models.PayloadSchemaType.BOOL)]


def clean_films() -> dict[str, dict]:
    """The clean records, in file order, with the boolean `unverified` next to `catalog_status` (so it can be filtered)."""
    out = {}
    for line in CLEAN.open(encoding="utf-8"):
        f = json.loads(line)
        f["unverified"] = f["catalog_status"] == "unverified"
        out[f["film_id"]] = f
    return out


def new_units(films: dict[str, dict]) -> list[Unit]:
    units: list[Unit] = []
    for f in films.values():
        units += units_for(f)
    assert len({u.unit_id for u in units}) == len(units)
    return units


def old_vectors() -> dict[tuple[str, str], np.ndarray]:
    """(film_id, text hash) → vector for every unit of the verified Phase 3 shards."""
    from .units import build_units
    units = build_units()
    vectors, _ = load_all(units)
    return {(u.film_id, u.text_sha256): vectors[i] for i, u in enumerate(units)}


def split_reuse(units: list[Unit], old: dict) -> tuple[list[int], list[int]]:
    reuse = [i for i, u in enumerate(units) if (u.film_id, u.text_sha256) in old]
    missing = [i for i, u in enumerate(units) if (u.film_id, u.text_sha256) not in old]
    return reuse, missing


def assemble(units: list[Unit], old: dict, fresh: dict[str, np.ndarray]) -> np.ndarray:
    rows = []
    for u in units:
        v = old.get((u.film_id, u.text_sha256))
        rows.append(v if v is not None else fresh[u.unit_id])
    return np.vstack(rows).astype(np.float32)


def load_fresh(units: list[Unit], missing: list[int], path=None) -> dict[str, np.ndarray]:
    """unit id → vector for the `missing` units found in the file of new vectors (default: the Phase 7 file; v3 passes its own)."""
    path = path or NEW_VECTORS
    if not path.exists():
        return {}
    with np.load(path, allow_pickle=False) as z:
        ids, shas, vec = [str(x) for x in z["unit_ids"]], [str(x) for x in z["text_sha256"]], z["vectors"]
    want = {units[i].unit_id: units[i].text_sha256 for i in missing}
    return {i: vec[k] for k, (i, h) in enumerate(zip(ids, shas)) if want.get(i) == h}


def embed_missing(client=None) -> dict:
    films = clean_films()
    units = new_units(films)
    old = old_vectors()
    _, missing = split_reuse(units, old)
    todo = [units[i] for i in missing]
    tokens = sum(u.tokens for u in todo)
    if usd(tokens) > MAX_USD_V2:
        raise SystemExit(f"estimated {usd(tokens):.5f} USD exceeds the authorised {MAX_USD_V2} USD")
    have = load_fresh(units, missing)
    todo = [u for u in todo if u.unit_id not in have]
    started = time.time()
    spent = 0
    if todo:
        client = client or __import__("pipelines.wikipedia_films.indexing.embed_run", fromlist=["make_client"]).make_client()
        vec, used, rid = _request(client, todo, _Pause())
        spent = used
        if usd(used) > MAX_USD_V2:
            raise SystemExit("the API reported more tokens than authorised")
        for u, v in zip(todo, vec):
            have[u.unit_id] = v
        DATA_V2.mkdir(parents=True, exist_ok=True)
        allu = [units[i] for i in missing]
        tmp = NEW_VECTORS.with_name(NEW_VECTORS.name + ".tmp")
        with tmp.open("wb") as f:
            np.savez(f, vectors=np.vstack([have[u.unit_id] for u in allu]).astype(np.float32), unit_ids=np.array([u.unit_id for u in allu]),
                     text_sha256=np.array([u.text_sha256 for u in allu]),
                     meta=np.array(json.dumps({"usage_tokens": used, "request_id": rid, "model": S.MODEL, "dimensions": S.DIMENSIONS,
                                               "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})))
        tmp.replace(NEW_VECTORS)
    return {"units": len(units), "reused": len(units) - len(missing), "to_embed": len(missing), "requested_now": len(todo),
            "api_tokens": spent, "usd": round(usd(spent), 6), "estimated_usd": round(usd(tokens), 6),
            "seconds": round(time.time() - started, 1)}


def plan() -> dict:
    films = clean_films()
    units = new_units(films)
    old = old_vectors()
    reuse, missing = split_reuse(units, old)
    return {"films": len(films), "units": len(units), "reused": len(reuse), "to_embed": len(missing),
            "tokens": sum(units[i].tokens for i in missing), "estimated_usd": round(usd(sum(units[i].tokens for i in missing)), 6),
            "to_embed_films": [units[i].film_id for i in missing], "cap_usd": MAX_USD_V2}


def old_digest(client, name: str) -> dict:
    """Count and a digest of all point ids: proof that a collection was not changed."""
    h, n, offset = hashlib.sha256(), 0, None
    while True:
        pts, offset = client.scroll(name, limit=5000, offset=offset, with_payload=False, with_vectors=False)
        for p in sorted(pts, key=lambda p: str(p.id)):
            h.update(str(p.id).encode()); n += 1
        if offset is None:
            break
    return {"points": n, "ids_sha256": h.hexdigest()}


def index() -> dict:
    S.assert_own_collection(V2)
    assert V2 != S.COLLECTION
    client = make_client()
    names = {c.name for c in client.get_collections().collections}
    if V2 in names:
        raise SystemExit(f"{V2} already exists: refusing to touch it (drop it by hand if you really want to rebuild)")
    before = {n: old_digest(client, n) for n in OLD_COLLECTIONS}
    films = clean_films()
    units = new_units(films)
    old = old_vectors()
    _, missing = split_reuse(units, old)
    fresh = load_fresh(units, missing)
    if len(fresh) != len(missing):
        raise SystemExit(f"{len(missing) - len(fresh)} vectors are still to be embedded: run `embed` first")
    vectors = assemble(units, old, fresh)
    if not np.isfinite(vectors).all() or vectors.shape != (len(units), S.DIMENSIONS):
        raise SystemExit("assembled vectors are invalid")
    create_collection(client, V2)
    for field, schema in EXTRA_INDEXES:
        client.create_payload_index(V2, field, schema)
    res = build_index(client=client, collection=V2, units=units, vectors=vectors, films=films)
    after = {n: old_digest(client, n) for n in OLD_COLLECTIONS}
    res.update({"old_before": before, "old_after": after, "old_untouched": before == after})
    res.pop("other_collections_before", None); res.pop("other_collections_after", None)
    DATA_V2.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(res, indent=1))
    return res


def check() -> dict:
    client = make_client()
    films = clean_films()
    units = new_units(films)
    old = old_vectors()
    _, missing = split_reuse(units, old)
    fresh = load_fresh(units, missing)
    vectors = assemble(units, old, fresh)
    base = check_index(client=client, collection=V2, units=units, vectors=vectors, films=films, sample=1500)
    excluded = {json.loads(l)["film"]["film_id"] for l in (S.ROOT / "data/clean/excluded.jsonl").open()}
    present = set()
    offset = None
    while True:
        pts, offset = client.scroll(V2, limit=5000, offset=offset, with_payload=["film_id", "catalog_status", "unverified"], with_vectors=False)
        present |= {p.payload["film_id"] for p in pts}
        if offset is None:
            break
    flt = lambda v: models.Filter(must=[models.FieldCondition(key="unverified", match=models.MatchValue(value=v))])
    expected_unv = sum(1 for f in films.values() if f["unverified"])
    # the freshly embedded vectors, exactly (all of them, not a sample)
    ids = [point_id(units[i].film_id, units[i].chunk_index) for i in missing]
    got = {str(p.id): p for p in client.retrieve(V2, ids=ids, with_vectors=True)}
    fresh_bad = 0
    for i, pid in zip(missing, ids):
        want = vectors[i] / np.linalg.norm(vectors[i])
        if pid not in got or not np.allclose(np.asarray(got[pid].vector, dtype=np.float32), want, atol=1e-6):
            fresh_bad += 1
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    now = {n: old_digest(client, n) for n in OLD_COLLECTIONS}
    out = {"index_check": {k: base[k] for k in ("points", "expected_points", "distinct_films", "expected_films", "vector_size", "distance",
                                                 "ids_match_plan", "sampled", "sample_vector_mismatch", "sample_payload_mismatch", "status",
                                                 "indexed_vectors")},
           "records_in_dataset": len(films), "films_in_collection": len(present), "points_equal_records": base["points"] == len(films),
           "film_ids_equal_dataset": present == set(films), "excluded_present": sorted(present & excluded), "excluded_total": len(excluded),
           "chunked_points": len([u for u in units if u.chunk_count > 1]),
           "unverified_expected": expected_unv, "unverified_by_filter": client.count(V2, count_filter=flt(True), exact=True).count,
           "verified_by_filter": client.count(V2, count_filter=flt(False), exact=True).count,
           "fresh_vectors": len(missing), "fresh_vectors_wrong": fresh_bad,
           "old_collections_now": now, "old_collections_before": report.get("old_before"), "old_untouched": report.get("old_before") == now}
    out["ok"] = bool(base["ok"] and out["points_equal_records"] and out["film_ids_equal_dataset"] and not out["excluded_present"]
                     and out["unverified_expected"] == out["unverified_by_filter"] and fresh_bad == 0 and out["old_untouched"]
                     and out["chunked_points"] == 0)
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "plan"
    fn = {"plan": plan, "embed": embed_missing, "index": index, "check": check}.get(cmd)
    if not fn:
        print(__doc__); return 2
    res = fn()
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
