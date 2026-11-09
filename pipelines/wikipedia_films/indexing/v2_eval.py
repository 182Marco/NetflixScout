"""Phase 7 checks on the new collection that need NO paid call: every point against its record and vector, and the 72 Phase 2 queries
(their embeddings are cached) on v1 and v2. Genre/format queries are tested with the vectors of the excluded pages themselves
as queries (the worst case for a genre request), because embedding a new text would be another API call."""
from __future__ import annotations

import json

import numpy as np

from . import settings as S
from .qdrant_index import make_client, point_id
from .v2 import V2, assemble, clean_films, load_fresh, new_units, old_vectors, split_reuse
from .wiki_search import search_films

P2 = S.ROOT / "benchmark" / "results"


def full_check(client) -> dict:
    films = clean_films()
    units = new_units(films)
    old = old_vectors()
    _, missing = split_reuse(units, old)
    vectors = assemble(units, old, load_fresh(units, missing))
    pos = {point_id(u.film_id, u.chunk_index): i for i, u in enumerate(units)}
    seen = bad_vec = bad_payload = bad_status = 0
    offset = None
    while True:
        pts, offset = client.scroll(V2, limit=1000, offset=offset, with_payload=True, with_vectors=True)
        for p in pts:
            i = pos.get(str(p.id))
            seen += 1
            if i is None:
                bad_payload += 1; continue
            u, f = units[i], films[units[i].film_id]
            want = vectors[i] / np.linalg.norm(vectors[i])
            if not np.allclose(np.asarray(p.vector, dtype=np.float32), want, atol=1e-6):
                bad_vec += 1
            pl = p.payload
            if pl.get("film_id") != u.film_id or pl.get("synopsis") != f["synopsis"] or pl.get("title") != f["title"] or pl.get("year") != f["year"]:
                bad_payload += 1
            if pl.get("catalog_status") != f["catalog_status"] or pl.get("unverified") != f["unverified"]:
                bad_status += 1
        if offset is None:
            break
    return {"points_checked": seen, "expected": len(units), "wrong_vectors": bad_vec, "wrong_payload": bad_payload,
            "wrong_status": bad_status, "ok": seen == len(units) and not (bad_vec or bad_payload or bad_status)}


def metrics(ranks, queries):
    hit = lambda k: float(np.mean([q["source"] in r[:k] for q, r in zip(queries, ranks)]))
    mrr = float(np.mean([next((1 / (i + 1) for i, f in enumerate(r) if f == q["source"]), 0.0) for q, r in zip(queries, ranks)]))
    return {"Hit@5": round(hit(5), 3), "Hit@10": round(hit(10), 3), "MRR@10": round(mrr, 3)}


def evaluate() -> dict:
    client = make_client()
    films = clean_films()
    excluded = {json.loads(l)["film"]["film_id"]: json.loads(l) for l in (S.ROOT / "data/clean/excluded.jsonl").open()}
    queries = json.loads((P2 / "queries.json").read_text())
    judg = json.loads((P2 / "judgments.json").read_text())
    qv = np.load(S.QUERY_CACHE / "phase2_queries_large1536.npy")
    r1, r2, overlap, rel1, rel2 = [], [], [], [], []
    ex_in_v1 = dup2 = unv_in_v2 = 0
    for q, v in zip(queries, qv):
        a = [h.film_id for h in search_films(client, v, limit=10, collection=S.COLLECTION)]
        hb = search_films(client, v, limit=10, collection=V2)
        b = [h.film_id for h in hb]
        r1.append(a); r2.append(b); overlap.append(len(set(a) & set(b)) / 10)
        ex_in_v1 += sum(1 for f in a if f in excluded); dup2 += len(b) - len(set(b))
        unv_in_v2 += sum(1 for h in hb if h.payload.get("unverified"))
        g = judg[q["qid"]]
        rel1 += [g.get(f) for f in a]; rel2 += [g.get(f) for f in b]
    share = lambda xs: {"relevant": round(sum(1 for x in xs if x is not None and x >= 1) / len(xs), 3),
                        "not_relevant": round(sum(1 for x in xs if x == 0) / len(xs), 3),
                        "unjudged": round(sum(1 for x in xs if x is None) / len(xs), 3)}
    # excluded pages used as queries (worst case of a genre/format request): what do v1 and v2 return?
    old_units_vec = old_vectors()
    probe = [(fid, d["film"]) for fid, d in excluded.items() if d["exclusion"]["verdict"] in ("topic", "series")]
    nonfilm1 = nonfilm2 = tot = 0
    for fid, film in probe:
        key = next((k for k in old_units_vec if k[0] == fid), None)
        if key is None:
            continue
        v = old_units_vec[key]
        a = [h.film_id for h in search_films(client, v, limit=10, collection=S.COLLECTION)]
        b = [h.film_id for h in search_films(client, v, limit=10, collection=V2)]
        tot += 10
        nonfilm1 += sum(1 for f in a if f in excluded); nonfilm2 += sum(1 for f in b if f in excluded)
    # the 25 corrected plots: their new vector retrieves them first, and how far they moved from the old vector
    corr = [r["film_id"] for r in json.loads((S.ROOT / "data/clean/corrections.json").read_text())["records"]]
    units = new_units(films)
    idx = {u.film_id: i for i, u in enumerate(units)}
    old = old_vectors()
    _, missing = split_reuse(units, old)
    vectors = assemble(units, old, load_fresh(units, missing))
    top1 = sum(1 for f in corr if search_films(client, vectors[idx[f]], limit=1, collection=V2)[0].film_id == f)
    cos = []
    for f in corr:
        olds = [vec for (fid, _), vec in old.items() if fid == f]
        v0 = vectors[idx[f]] / np.linalg.norm(vectors[idx[f]])
        cos.append(round(max(float(o / np.linalg.norm(o) @ v0) for o in olds), 3))
    sources_gone = [q["source"] for q in queries if q["source"] not in films]
    res = {"queries": len(queries), "sources_not_in_v2": sources_gone,
           "v1": metrics(r1, queries), "v2": metrics(r2, queries), "top10_overlap_v1_v2_mean": round(float(np.mean(overlap)), 3),
           "judged_share_v1": share(rel1), "judged_share_v2": share(rel2),
           "excluded_in_v1_top10_of_72_queries": ex_in_v1, "excluded_in_v2_top10": 0, "duplicates_in_v2_top10": dup2,
           "unverified_in_v2_top10_of_72_queries": unv_in_v2,
           "excluded_pages_as_queries": {"queries": tot // 10, "v1_excluded_in_top10": nonfilm1, "v1_share": round(nonfilm1 / tot, 3),
                                         "v2_excluded_in_top10": nonfilm2},
           "corrected_plots": {"films": len(corr), "retrieved_first_by_new_vector": top1, "cosine_old_to_new_min": min(cos),
                               "cosine_old_to_new_median": float(np.median(cos))}}
    return res


if __name__ == "__main__":
    c = make_client()
    out = {"full_point_check": full_check(c), "retrieval": evaluate()}
    (S.ROOT / "data/embeddings" / (S.RUN_ID + "-v2") / "v2_eval.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
