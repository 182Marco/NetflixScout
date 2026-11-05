"""Phase 3 retrieval check, part 2: precision of the FULL-corpus top 10 with the same LLM judge and prompt as Phase 2.

The top 10 of the 72 Phase 2 queries (one result per film, from the real Qdrant collection) is mostly new (not judged in
Phase 2): only those pairs are sent to the judge (a few hundred, ~0.2 USD). Results are stored apart from the Phase 2
judgments; the Phase 2 files are only read. Needs the benchmark helpers (OPENAI_API_KEY via .env, cost ledger)."""
from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import settings as S
from .qdrant_index import make_client
from .wiki_search import search_films

P2 = S.ROOT / "benchmark" / "results"
OUT = S.DATA / "retrieval_judgments.json"
MAX_EXTRA_USD = 0.5


def evaluate() -> dict:
    sys.path.insert(0, str(S.ROOT / "benchmark"))
    import common as bc                       # noqa: E402  (benchmark helpers: ledger, llm_json)
    from judge import BATCH, INSTRUCTIONS, shown  # noqa: E402

    start_spent = bc.spent()
    queries = json.loads((P2 / "queries.json").read_text())
    p2 = json.loads((P2 / "judgments.json").read_text())
    films = bc.load_films()
    qv = np.load(S.QUERY_CACHE / "phase2_queries_large1536.npy")
    qd = make_client()
    tops = {q["qid"]: [h.film_id for h in search_films(qd, v, limit=10)] for q, v in zip(queries, qv)}
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    jobs = []
    for q in queries:
        known = {**p2[q["qid"]], **data.get(q["qid"], {})}
        todo = [f for f in tops[q["qid"]] if f not in known and f != q["source"]]
        for i in range(0, len(todo), BATCH):
            jobs.append((q, todo[i:i + BATCH]))
    print("pairs to judge:", sum(len(t) for _, t in jobs), "calls:", len(jobs), flush=True)

    def run(job):
        q, fids = job
        if bc.spent() - start_spent > MAX_EXTRA_USD:
            raise SystemExit("extra budget for the retrieval judge exhausted")
        listing = "\n\n".join(f"[{n}] {shown(films[f]['synopsis'])}" for n, f in enumerate(fids, 1))
        g = bc.llm_json("p3judge", INSTRUCTIONS, f"Richiesta: {q['text']}\n\nTrame:\n\n{listing}")["gradi"]
        return q["qid"], {f: int(g[str(n)]) for n, f in enumerate(fids, 1)}

    with ThreadPoolExecutor(6) as ex:
        for qid, g in ex.map(run, jobs):
            data.setdefault(qid, {}).update(g)
    OUT.write_text(json.dumps(data))
    rows = []
    for q in queries:
        grade = {**p2[q["qid"]], **data.get(q["qid"], {}), q["source"]: 2}
        gr = [grade[f] for f in tops[q["qid"]]]
        ideal = sorted(grade.values(), reverse=True)
        dcg = lambda xs: sum(x / math.log2(i + 2) for i, x in enumerate(xs))
        rows.append({"P@5": sum(x >= 1 for x in gr[:5]) / 5, "P@10": sum(x >= 1 for x in gr) / 10,
                     "Ps@10": sum(x == 2 for x in gr) / 10, "nDCG@10": dcg(gr) / dcg(ideal[:10]),
                     "hit": q["source"] in tops[q["qid"]]})
    m = lambda k: round(float(np.mean([r[k] for r in rows])), 3)
    res = {"queries": len(queries), "judged_now": sum(len(g) for g in data.values()),
           "full_corpus_top10": {"P@5": m("P@5"), "P@10": m("P@10"), "Ps@10": m("Ps@10"), "source_hit@10": m("hit"),
                                 "note": "nDCG not comparable: ideal DCG grows with the extra relevant films found in the 41k corpus"},
           "phase2_pool_reference_A_large_1536": {"P@5": 0.706, "P@10": 0.624, "Ps@10": 0.150, "Hit@10": 0.708},
           "judge_cost_usd": round(bc.spent() - start_spent, 4)}
    (S.DATA / "retrieval_eval_judged.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=1))
