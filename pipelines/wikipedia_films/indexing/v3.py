"""v3 collection `wikipedia_films_it_v3`: the 2026-11-04 catalogue (v2 + Aftershock) with the fields of the new retriever.

    python -m pipelines.wikipedia_films.indexing.v3 plan     # what is reused and what must be embedded (no API call)
    python -m pipelines.wikipedia_films.indexing.v3 embed    # PAID: embeds only the vectors that are missing (needs FILMS_EMBED_AUTHORIZED=yes)
    python -m pipelines.wikipedia_films.indexing.v3 index    # creates and fills v3 (refuses if it exists); no embedding is requested
    python -m pipelines.wikipedia_films.indexing.v3 check    # source ↔ embeddings ↔ Qdrant, point by point; the older collections untouched

Vectors come from three places, in this order: the Phase 3 shards (by film id and text hash), the Phase 7 file (the 25 corrected plots of the
original build) and the file written by `embed` (everything else). On the machine where the project was built nothing is missing; on a NEW
machine run `plan`, then `embed` (the Phase 3 shards are optional: without them every vector is requested, about 3.1 USD for the whole
catalogue; see docs/REBUILD.md). `index` stops if any vector is missing: it never calls the embedding API.
netflix_scout, wikipedia_films_it and wikipedia_films_it_v2 are only read, and only if they exist."""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
from qdrant_client import models

from . import settings as S
from . import v2 as V2M
from .embed_run import _Pause, _request, usd
from .embed_run import make_client as make_openai_client
from .qdrant_index import build_index, check_index, create_collection, make_client, point_id
from .units import make_shards, units_for

V3 = S.COLLECTION_V3
CATALOGUE = S.ROOT / "data" / "clean_v3" / "films.v3.jsonl"
DATA_V3 = S.ROOT / "data" / "embeddings" / (S.RUN_ID + "-v3")
REPORT = DATA_V3 / "v3_report.json"
NEW_VECTORS = DATA_V3 / "new_vectors.npz"   # written by `embed`: the vectors that no Phase 3 shard or Phase 7 file has
MAX_USD_V3 = 4.0                              # default cap of `embed` (the whole catalogue costs about 3.1 USD); --max-usd changes it
AUTH_ENV = "FILMS_EMBED_AUTHORIZED"
OLD_COLLECTIONS = ("netflix_scout", S.COLLECTION, S.COLLECTION_V2)
KW, BOOL = models.PayloadSchemaType.KEYWORD, models.PayloadSchemaType.BOOL
EXTRA_INDEXES = [
    ("catalog_status", KW), ("unverified", BOOL), ("actor_names", KW), ("actor_names_norm", KW), ("director_names_norm", KW),
    ("original_title_norm", KW), ("genres_norm", KW), ("work_format", KW), ("format_confidence", KW), ("franchise_id", KW),
    ("franchise_ids", KW),
]
SYNOPSIS_TEXT_INDEX = models.TextIndexParams(type=models.TextIndexType.TEXT, tokenizer=models.TokenizerType.WORD, min_token_len=2,
                                             max_token_len=30, lowercase=True, ascii_folding=True)


def catalogue() -> dict[str, dict]:
    out = {}
    for line in CATALOGUE.open(encoding="utf-8"):
        f = json.loads(line)
        f["unverified"] = f["catalog_status"] == "unverified"
        out[f["film_id"]] = f
    return out


def all_units(films):
    units = []
    for f in films.values():
        units += units_for(f)
    assert len({u.unit_id for u in units}) == len(units)
    return units


def _old_vectors() -> dict:
    """Phase 3 vectors by (film id, text hash); empty when the shards are not on this machine (a fresh clone): then `embed` requests them."""
    try:
        return V2M.old_vectors()
    except (FileNotFoundError, ValueError):
        return {}


def _load_fresh(units, missing) -> dict:
    """unit id → vector for the units the Phase 3 shards lack: first the Phase 7 file, then the file written by `embed`."""
    got = V2M.load_fresh(units, missing)
    rest = [i for i in missing if units[i].unit_id not in got]
    got.update(V2M.load_fresh(units, rest, NEW_VECTORS))
    return got


def _digests(client) -> dict:
    """Count and id digest of the legacy collections that exist (a new machine has none: nothing to protect)."""
    present = {c.name for c in client.get_collections().collections}
    return {n: V2M.old_digest(client, n) for n in OLD_COLLECTIONS if n in present}


def vectors_for(units):
    old = _old_vectors()
    _, missing = V2M.split_reuse(units, old)
    fresh = _load_fresh(units, missing)
    if len(fresh) != len(missing):
        raise SystemExit(f"{len(missing) - len(fresh)} vectors are not available: `index` never calls the embedding API; "
                         f"run `python -m pipelines.wikipedia_films.indexing.v3 plan`, then `embed` ({AUTH_ENV}=yes)")
    return V2M.assemble(units, old, fresh), missing


def plan() -> dict:
    films = catalogue()
    units = all_units(films)
    old = _old_vectors()
    reuse, missing = V2M.split_reuse(units, old)
    fresh = _load_fresh(units, missing)
    todo = [units[i] for i in missing if units[i].unit_id not in fresh]
    return {"films": len(films), "units": len(units), "phase3_shards_found": bool(old), "reused_from_phase3": len(reuse),
            "from_new_vector_files": len(fresh), "unavailable": len(todo), "tokens_to_embed": sum(u.tokens for u in todo),
            "estimated_usd_to_embed": round(usd(sum(u.tokens for u in todo)), 4), "api_calls": 0,
            "aftershock_vector_reused": any(u.film_id == "Q2421745" and (u.film_id, u.text_sha256) in old for u in units)}


def _save_fresh(units, missing, have, used_tokens, request_id) -> None:
    """Rewrites the file of new vectors with everything obtained so far, so an interrupted `embed` resumes where it stopped."""
    rows = [units[i] for i in missing if units[i].unit_id in have]
    NEW_VECTORS.parent.mkdir(parents=True, exist_ok=True)
    tmp = NEW_VECTORS.with_name(NEW_VECTORS.name + ".tmp")
    with tmp.open("wb") as f:
        np.savez(f, vectors=np.vstack([have[u.unit_id] for u in rows]).astype(np.float32), unit_ids=np.array([u.unit_id for u in rows]),
                 text_sha256=np.array([u.text_sha256 for u in rows]),
                 meta=np.array(json.dumps({"usage_tokens": used_tokens, "last_request_id": request_id, "model": S.MODEL, "dimensions": S.DIMENSIONS,
                                           "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})))
    tmp.replace(NEW_VECTORS)


def embed(client=None, *, max_usd: float = MAX_USD_V3) -> dict:
    """PAID. Embeds only the units of the v3 catalogue for which no vector exists yet (no Phase 3 shard, no Phase 7 file, nothing from an
    earlier `embed`). Refuses without FILMS_EMBED_AUTHORIZED=yes and when the estimate is over the cap; resumable."""
    if os.environ.get(AUTH_ENV, "").strip().lower() != "yes":
        raise SystemExit(f"this step calls the paid OpenAI embeddings API: run `plan` first, then set {AUTH_ENV}=yes to authorise it")
    films = catalogue()
    units = all_units(films)
    old = _old_vectors()
    _, missing = V2M.split_reuse(units, old)
    have = _load_fresh(units, missing)
    todo = [units[i] for i in missing if units[i].unit_id not in have]
    estimated = usd(sum(u.tokens for u in todo))
    if estimated > max_usd:
        raise SystemExit(f"estimated {estimated:.4f} USD exceeds the cap of {max_usd} USD (raise it with --max-usd if that is intended)")
    started, spent, requests, last_id = time.time(), 0, 0, None
    if todo:
        client = client or make_openai_client()
        pause = _Pause()
        for shard in make_shards(todo):
            vectors, used, last_id = _request(client, shard, pause)
            spent += used
            requests += 1
            if usd(spent) > max_usd:
                raise SystemExit("the API reported more tokens than the cap: stopped (what was obtained is saved)")
            for u, v in zip(shard, vectors):
                have[u.unit_id] = v
            _save_fresh(units, missing, have, spent, last_id)
    return {"units": len(units), "reused": len(units) - len(missing), "to_embed": len(missing), "requested_now": len(todo), "requests": requests,
            "api_tokens": spent, "usd": round(usd(spent), 6), "estimated_usd": round(estimated, 6), "cap_usd": max_usd,
            "seconds": round(time.time() - started, 1)}


def index() -> dict:
    S.assert_own_collection(V3)
    client = make_client()
    if V3 in {c.name for c in client.get_collections().collections}:
        raise SystemExit(f"{V3} already exists: refusing to touch it (drop it by hand if you really want to rebuild)")
    before = _digests(client)
    films = catalogue()
    units = all_units(films)
    vectors, _ = vectors_for(units)
    if not np.isfinite(vectors).all() or vectors.shape != (len(units), S.DIMENSIONS):
        raise SystemExit("assembled vectors are invalid")
    create_collection(client, V3)
    for field, schema in EXTRA_INDEXES:
        client.create_payload_index(V3, field, schema)
    client.create_payload_index(V3, "synopsis", SYNOPSIS_TEXT_INDEX)
    res = build_index(client=client, collection=V3, units=units, vectors=vectors, films=films)
    after = _digests(client)
    res.update({"old_before": before, "old_after": after, "old_untouched": before == after})
    res.pop("other_collections_before", None); res.pop("other_collections_after", None)
    DATA_V3.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(res, indent=1))
    return res


def check() -> dict:
    client = make_client()
    films = catalogue()
    units = all_units(films)
    vectors, _ = vectors_for(units)
    # every point against its record (the base check only samples): vector, film id, title, year, plot, new fields
    mism = {"vector": 0, "payload": 0, "missing": 0}
    ids = [point_id(u.film_id, u.chunk_index) for u in units]
    for i in range(0, len(units), 500):
        got = {str(p.id): p for p in client.retrieve(V3, ids=ids[i:i + 500], with_payload=True, with_vectors=True)}
        for k, u in enumerate(units[i:i + 500]):
            p = got.get(ids[i + k])
            if p is None:
                mism["missing"] += 1
                continue
            want = vectors[i + k] / np.linalg.norm(vectors[i + k])
            if not np.allclose(np.asarray(p.vector, dtype=np.float32), want, atol=1e-6):
                mism["vector"] += 1
            f = films[u.film_id]
            if any(p.payload.get(k2) != f[k2] for k2 in ("film_id", "title", "year", "synopsis", "work_format", "format_confidence",
                                                          "franchise_id", "franchise_ids", "actor_names_norm", "unverified", "imdb_id")):
                mism["payload"] += 1
    base = check_index(client=client, collection=V3, units=units, vectors=vectors, films=films, sample=300)
    excluded = {json.loads(l)["film"]["film_id"] for l in (S.ROOT / "data/clean/excluded.jsonl").open()} - {"Q2421745"}
    present, offset = set(), None
    while True:
        pts, offset = client.scroll(V3, limit=5000, offset=offset, with_payload=["film_id"], with_vectors=False)
        present |= {p.payload["film_id"] for p in pts}
        if offset is None:
            break
    cnt = lambda key, val: client.count(V3, count_filter=models.Filter(must=[models.FieldCondition(key=key, match=models.MatchValue(value=val))]), exact=True).count
    now = _digests(client)
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    out = {"points": base["points"], "records": len(films), "points_equal_records": base["points"] == len(films),
           "film_ids_equal_dataset": present == set(films), "excluded_present": sorted(present & excluded),
           "aftershock_present": "Q2421745" in present, "mismatches_every_point": mism,
           "base_check_ok": base["ok"], "unverified_expected": sum(1 for f in films.values() if f["unverified"]),
           "unverified_by_filter": cnt("unverified", True), "feature_by_filter": cnt("work_format", "feature"),
           "feature_expected": sum(1 for f in films.values() if f["work_format"] == "feature"),
           "with_franchise_by_filter": client.count(V3, count_filter=models.Filter(must_not=[models.IsNullCondition(is_null=models.PayloadField(key="franchise_id"))]), exact=True).count,
           "with_franchise_expected": sum(1 for f in films.values() if f["franchise_id"]),
           "old_collections_now": now, "old_untouched": report.get("old_before") == now}
    out["ok"] = bool(out["points_equal_records"] and out["film_ids_equal_dataset"] and not out["excluded_present"] and out["aftershock_present"]
                     and not any(mism.values()) and base["ok"] and out["unverified_expected"] == out["unverified_by_filter"]
                     and out["feature_expected"] == out["feature_by_filter"] and out["with_franchise_by_filter"] == out["with_franchise_expected"]
                     and out["old_untouched"])
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "plan"
    fn = {"plan": plan, "embed": embed, "index": index, "check": check}.get(cmd)
    if not fn:
        print(__doc__); return 2
    if cmd == "embed" and "--max-usd" in argv:
        res = embed(max_usd=float(argv[argv.index("--max-usd") + 1]))
    else:
        res = fn()
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
