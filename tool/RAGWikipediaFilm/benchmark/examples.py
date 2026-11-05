"""Concrete cases for the report (offline)."""
from __future__ import annotations

import json

from common import RESULTS, load_films, ntok
from retrieval import rankings

films = load_films()
queries = json.loads((RESULTS / "queries.json").read_text())
judg = json.loads((RESULTS / "judgments.json").read_text())
runs = rankings()
KEYS = [("A", "small-1536"), ("A", "large-3072"), ("B1", "large-3072"), ("C500", "large-3072")]


def rank(key, qi, src):
    r = runs[key]
    top = [r["films"][j] for j in r["top"][qi, :100]]
    return top.index(src) + 1 if src in top else None


def title(f): return f"{films[f]['title']} ({films[f]['year']})"


rows = []
for qi, q in enumerate(queries):
    rows.append((qi, q, {k: rank(k, qi, q["source"]) for k in KEYS}))
def show(tag, qi, q, ranks):
    print(f"\n### {tag} — {q['qid']} [{q['type']}] source: {title(q['source'])}, {ntok(films[q['source']]['synopsis'])} tok")
    print("query:", q["text"])
    print("rank of source:", {f"{k[0]}|{k[1]}": v for k, v in ranks.items()})
    key = ("A", "large-3072"); r = runs[key]
    for j in r["top"][qi, :3]:
        f = r["films"][j]; print(f"   A|large top: {title(f)}  grade={judg[q['qid']].get(f, 0)}")
ok = [x for x in rows if x[2][KEYS[1]] == 1]
sl = [x for x in rows if x[2][KEYS[1]] and x[2][KEYS[1]] <= 3 and not (x[2][KEYS[0]] and x[2][KEYS[0]] <= 10)]
fail = [x for x in rows if not x[2][KEYS[1]] or x[2][KEYS[1]] > 10]
ch = [x for x in rows if x[2][KEYS[3]] and x[2][KEYS[3]] <= 3 and not (x[2][KEYS[1]] and x[2][KEYS[1]] <= 10)]
sm = [x for x in rows if x[2][KEYS[2]] and x[2][KEYS[2]] <= 3 and not (x[2][KEYS[1]] and x[2][KEYS[1]] <= 10)]
print("counts: success@1", len(ok), "large ok/small fail", len(sl), "large fail@10", len(fail), "chunk rescues", len(ch), "B1 rescues", len(sm))
for tag, group in (("SUCCESS (large rank 1)", ok[:2]), ("LARGE OK / SMALL FAIL", sl[:2]), ("FAIL (large >10)", fail[:3]), ("CHUNK RESCUE", ch[:1]), ("SUMMARY RESCUE", sm[:1])):
    for x in group: show(tag, *x)
