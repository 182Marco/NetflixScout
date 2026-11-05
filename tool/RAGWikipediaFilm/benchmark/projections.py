"""Full-dataset costs and sizes. MEASURED: token counts of the 41,421 plots, real chunking of all of them (no embedding), unit
prices, per-call usage in the pool. PROJECTED: summary output tokens (fit on the pool's real usage), wall-clock times."""
from __future__ import annotations

import json
import statistics

from common import LEDGER, PRICES, RESULTS, load_films, ntok
from summarize import LEVELS, target_words
from variants import chunk, clip

films = load_films()
ids = sorted(films)
orig_tok = {f: ntok(films[f]["synopsis"]) for f in ids}
out: dict = {"films": len(ids), "plot_tokens": sum(orig_tok.values())}

# --- real usage per summary level in the pool: output tokens per target word, input overhead
ledger = [json.loads(l) for l in LEDGER.open()]
summ = json.loads((RESULTS / "summaries.json").read_text())
fit = {}
for lv in ("B1", "B2"):
    calls = [e for e in ledger if e["label"] == f"summary:{lv}"]
    tw = [v["target_words"] for k, v in summ.items() if k.startswith(lv) and not v["kept_original"]]
    fit[lv] = {"calls": len(calls), "mean_out": sum(e["out"] for e in calls) / len(calls),
               "mean_in": sum(e["in"] for e in calls) / len(calls), "mean_target_words": sum(tw) / len(tw)}
# out_tokens = r + c * target_words  (two points: B1 and B2)
c = (fit["B1"]["mean_out"] - fit["B2"]["mean_out"]) / (fit["B1"]["mean_target_words"] - fit["B2"]["mean_target_words"])
r = fit["B1"]["mean_out"] - c * fit["B1"]["mean_target_words"]
out["summary_fit"] = {"reasoning_const_tokens": r, "out_tokens_per_target_word": c, **fit}

def summary_cost(levels):
    p = PRICES["gpt-5.6-luna"]; tot = {"calls": 0, "in": 0, "out": 0, "usd": 0.0, "kept": 0, "summary_tokens": 0}
    for lv in levels:
        for f in ids:
            t = target_words(lv, films[f]["synopsis"])
            if t is None:
                tot["kept"] += 1; tot["summary_tokens"] += orig_tok[f]; continue
            tin = orig_tok[f] + (fit[lv]["mean_in"] - statistics.mean([0]) - 0) * 0 + 150  # plot + ~150 instruction tokens
            tout = r + c * t
            tot["calls"] += 1; tot["in"] += tin; tot["out"] += tout; tot["summary_tokens"] += int(t / 0.56)
    tot["usd"] = (tot["in"] * p["in"] + tot["out"] * p["out"]) / 1e6
    return tot

out["summary_B1"] = summary_cost(["B1"]); out["summary_B2"] = summary_cost(["B2"])

# --- vectors and tokens per strategy (chunk variants really chunked)
strat = {"A": {"vectors": len(ids), "tokens": sum(min(t, 8000) for t in orig_tok.values())}}
strat["B1"] = {"vectors": len(ids), "tokens": out["summary_B1"]["summary_tokens"]}
strat["B2"] = {"vectors": len(ids), "tokens": out["summary_B2"]["summary_tokens"]}
for name, size in (("C500", 500), ("C250", 250)):
    v = tk = long = 0
    for f in ids:
        if orig_tok[f] > 2 * size:
            ch = chunk(films[f]["synopsis"], size); v += len(ch); tk += sum(ntok(c_) for c_ in ch); long += 1
        else:
            v += 1; tk += min(orig_tok[f], 8000)
    strat[name] = {"vectors": v, "tokens": tk, "chunked_films": long}
out["strategies"] = strat
for name, s in strat.items():
    s["vectors_per_film"] = round(s["vectors"] / len(ids), 3)
    s["usd_small"] = round(s["tokens"] * PRICES["text-embedding-3-small"]["in"] / 1e6, 3)
    s["usd_large"] = round(s["tokens"] * PRICES["text-embedding-3-large"]["in"] / 1e6, 3)
    for cfg, d in (("small-1536", 1536), ("large-3072", 3072), ("large-1536", 1536)):
        s[f"vec_MB_{cfg}"] = round(s["vectors"] * d * 4 / 1e6, 1)
(RESULTS / "projections.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
