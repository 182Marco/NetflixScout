"""Reliability of the LLM judge: (1) judge the source film itself for every query (it must be relevant: the query was written
from it) and (2) re-judge the pools of a few queries with a second independent call and measure agreement."""
from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS, SEED, llm_json, load_films
from judge import BATCH, INSTRUCTIONS, shown

films = load_films()
queries = {q["qid"]: q for q in json.loads((RESULTS / "queries.json").read_text())}
judg = json.loads((RESULTS / "judgments.json").read_text())
pools = json.loads((RESULTS / "pools.json").read_text())


def ask(q, fids):
    listing = "\n\n".join(f"[{n}] {shown(films[f]['synopsis'])}" for n, f in enumerate(fids, 1))
    g = llm_json("judgecheck", INSTRUCTIONS, f"Richiesta: {q['text']}\n\nTrame:\n\n{listing}")["gradi"]
    return {f: int(g[str(n)]) for n, f in enumerate(fids, 1)}


def sanity(q):
    return q["qid"], ask(q, [q["source"]])[q["source"]]


rng = random.Random(SEED)
with ThreadPoolExecutor(6) as ex:
    src = dict(ex.map(sanity, queries.values()))
res = {"source_grades": src}
print("source film judged >=1:", sum(v >= 1 for v in src.values()), "/", len(src), "; ==2:", sum(v == 2 for v in src.values()))

chosen = rng.sample(sorted(queries), 6)


def redo(qid):
    q = queries[qid]
    fids = [f for f in pools[qid] if f != q["source"]]
    out = {}
    for i in range(0, len(fids), BATCH):
        out.update(ask(q, fids[i:i + BATCH]))
    return qid, out


with ThreadPoolExecutor(6) as ex:
    again = dict(ex.map(redo, chosen))
pairs = [(judg[qid][f], g) for qid, d in again.items() for f, g in d.items()]
exact = sum(a == b for a, b in pairs) / len(pairs)
rel = sum((a >= 1) == (b >= 1) for a, b in pairs) / len(pairs)
within1 = sum(abs(a - b) <= 1 for a, b in pairs) / len(pairs)
print(f"re-judged pairs {len(pairs)}: exact agreement {exact:.3f}, relevant/not agreement {rel:.3f}, within 1 {within1:.3f}")
res.update({"rejudged_pairs": len(pairs), "exact": exact, "binary": rel, "within1": within1})
(RESULTS / "judge_checks.json").write_text(json.dumps(res))
