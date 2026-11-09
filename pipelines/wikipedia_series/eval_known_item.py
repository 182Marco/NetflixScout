"""Design benchmark (open item 3 of PROGRESS): does ONE collection with a mandatory level filter retrieve as well as it should, and what does an
unfiltered (mixed) search cost? Known-item retrieval at scale, ground truth by construction.

For a seeded sample of units an LLM writes a short description of the text WITHOUT its title (the way a user who does not remember the title would),
then the description is searched in four ways:
  filtered     entity_type = level of the target (+ default_search_eligible for series / TV movies)         <- the design
  mixed        no entity_type filter, no eligibility filter                                                  <- never default, measured here
  unrestricted entity_type = level, WITHOUT the eligibility filter (does hiding the manga+anime pages cost recall?)
  named        (episodes/seasons only) filter + series_id of the named series                                <- what the retriever does when the series is named
Metrics: hit@1/5/10 of the target record id, MRR@10, and for `mixed` the share of top-10 results of the wrong level.

    python -m pipelines.wikipedia_series.eval_known_item gen      # PAID (small): descriptions with the LLM, cached in data/s8/known_queries.jsonl
    python -m pipelines.wikipedia_series.eval_known_item run      # PAID (embeddings of the descriptions, cached): searches + data/s8/known_item_results.json
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from qdrant_client import models

from . import embed as E
from tool.rag.series import retrieval as R  # the retriever the agent runs: evaluated, not copied
from .common import DATA_DIR, load_env
from .index import records

OUT = DATA_DIR / "s8"
QUERIES = OUT / "known_queries.jsonl"
VECS = OUT / "known_vectors.npz"
RESULTS = OUT / "known_item_results.json"
SAMPLE = {"series": 200, "season": 100, "episode": 300, "tv_movie": 100}
GEN_MODEL = "gpt-5.6-luna"
PROMPT = ("Sei un utente che ricorda vagamente una {what} e la descrive a un motore di ricerca in 1-2 frasi in italiano, con parole tue, "
          "senza dire il titolo{extra}. Parti dal testo seguente; descrivi la storia, non copiare le frasi.\n\nTesto:\n{text}")
WHAT = {"series": "serie TV", "season": "stagione di una serie TV", "episode": "puntata di una serie TV", "tv_movie": "film per la televisione"}


def sample_units() -> list[dict]:
    units, recs = E.read_units(), records()
    rng = random.Random(20261108)
    by = defaultdict(list)
    for u in units:
        by[u.entity_type].append(u)
    out = []
    for et, n in SAMPLE.items():
        for u in rng.sample(by[et], n):
            r = recs[u.unit_id]
            out.append({"record_id": u.unit_id, "entity_type": et, "title": r["title"], "series_id": r.get("series_id"),
                        "series_title": r.get("series_title"), "season_number": r.get("season_number"),
                        "eligible": r.get("default_search_eligible", True), "text": u.text})
    return out


def gen() -> int:
    load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["record_id"] for l in QUERIES.open()} if QUERIES.exists() else set()
    todo = [s for s in sample_units() if s["record_id"] not in done]
    client = R._openai(max_retries=3, timeout=90)

    def one(s):
        extra = " né il nome della serie" if s["entity_type"] in ("episode", "season") else ""
        r = client.responses.create(model=GEN_MODEL, input=PROMPT.format(what=WHAT[s["entity_type"]], extra=extra, text=s["text"][:2500]))
        return {k: v for k, v in s.items() if k != "text"} | {"query": r.output_text.strip()}

    with ThreadPoolExecutor(8) as ex, QUERIES.open("a") as f:
        for row in ex.map(one, todo):
            f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
    print(f"generated {len(todo)} (already {len(done)})")
    return 0


def _flt(level: str, *, eligible: bool, series_ids=None, season=None) -> models.Filter:
    must = []
    if level:
        must.append(models.FieldCondition(key="entity_type", match=models.MatchValue(value=level)))
    if eligible and level in ("series", "tv_movie"):
        must.append(models.FieldCondition(key="default_search_eligible", match=models.MatchValue(value=True)))
    if series_ids:
        must.append(models.FieldCondition(key="series_id", match=models.MatchAny(any=series_ids)))
    return models.Filter(must=must) if must else None


def run() -> int:
    load_env()
    rows = [json.loads(l) for l in QUERIES.open()]
    if VECS.exists():
        z = np.load(VECS, allow_pickle=False)
        cache = dict(zip([str(x) for x in z["ids"]], z["vecs"]))
    else:
        cache = {}
    need = [r for r in rows if r["record_id"] not in cache]
    if need:
        emb = R.make_embed(client=R._openai(max_retries=3, timeout=90))
        for i in range(0, len(need), 64):
            b = need[i:i + 64]
            for r, v in zip(b, emb([x["query"] for x in b])):
                cache[r["record_id"]] = v
        np.savez(VECS, ids=np.array(list(cache)), vecs=np.stack(list(cache.values())))
    index = R.SeriesIndex()
    res = defaultdict(lambda: defaultdict(list))
    wrong_level = defaultdict(list)
    for r in rows:
        v = R.unit(cache[r["record_id"]])
        lvl, tgt = r["entity_type"], r["record_id"]
        modes = {"filtered": _flt(lvl, eligible=True), "mixed": _flt("", eligible=False), "unrestricted": _flt(lvl, eligible=False)}
        if lvl in ("episode", "season") and r["series_id"]:
            modes["named"] = _flt(lvl, eligible=False, series_ids=[r["series_id"]])
        for mode, flt in modes.items():
            got = index.client.query_points(index.collection, query=v.tolist(), limit=10, query_filter=flt, with_payload=["record_id", "entity_type"]).points
            ids = [p.payload["record_id"] for p in got]
            rank = ids.index(tgt) + 1 if tgt in ids else None
            res[lvl][mode].append(rank)
            if mode == "mixed":
                wrong_level[lvl].append(sum(p.payload["entity_type"] != lvl for p in got) / max(len(got), 1))
    summary = {}
    for lvl, modes in res.items():
        summary[lvl] = {"n": len(next(iter(modes.values())))}
        for mode, ranks in modes.items():
            n = len(ranks)
            hit = lambda k: round(sum(1 for x in ranks if x and x <= k) / n, 3)
            summary[lvl][mode] = {"hit@1": hit(1), "hit@5": hit(5), "hit@10": hit(10), "mrr@10": round(sum(1 / x for x in ranks if x) / n, 3)}
        summary[lvl]["mixed_wrong_level_share_top10"] = round(float(np.mean(wrong_level[lvl])), 3)
    elig = [r for r in rows if r["entity_type"] in ("series", "tv_movie") and not r["eligible"]]
    summary["_ineligible_targets_in_sample"] = len(elig)
    RESULTS.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit({"gen": gen, "run": run}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
