"""Phase 5: what the reading of the stratified sample found (see sample_review.py for how it is drawn).
Verdicts are mine, from the page text; `certain` = not a film by the owner's rules, `borderline` = could be argued either way."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# stratum -> (population, sample, certain false positives, borderline)
FINDINGS = {
    "tv_film": (735, 60, {"Q9262969": "miniserie in 4 puntate (Uccelli di rovo)"},
                {"Q61184609": "intervista TV di 25 minuti, non un film"}),
    "feature": (301, 40, {}, {"Q3794237": "Il giovane Mussolini: probabile miniserie TV in due parti",
                              "Q86662229": "Vette di libertà: forse film TV, nessun dato di regia"}),
    "animated": (180, 30, {}, {}),
    "other": (103, 103, {"Q140393354": "Lobo Paramilitary Christmas Special: è un fumetto"},
              {"Q138800393": "2 Girls 1 Cup: video virale di 1 minuto, non un film",
               "Q1473406": "Rabbits: serie web di Lynch montata in un'opera",
               "Q139898922": "Grachi Sweet 16: puntata speciale di una serie TV"}),
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - a) / d), min(1.0, (c + a) / d)


def summary() -> dict:
    out = {}
    for name, (pop, n, certain, border) in FINDINGS.items():
        k = len(certain)
        lo, hi = wilson(k, n) if n < pop else (k / pop, k / pop)   # a full census has no sampling error
        out[name] = {"population": pop, "sample": n, "certain_false_positives": certain, "borderline": border,
                     "rate": round(100 * k / n, 1), "ci95_pct": [round(100 * lo, 1), round(100 * hi, 1)],
                     "estimated_false_positives": round(pop * k / n), "estimated_range": [round(pop * lo), round(pop * hi)]}
    return out


if __name__ == "__main__":
    s = summary()
    (ROOT / "audit" / "sample_findings.json").write_text(json.dumps({"version": 1, "seed": 20261104, "strata": s},
                                                                     ensure_ascii=False, indent=1) + "\n")
    for k, v in s.items():
        print(k, v["sample"], "/", v["population"], v["rate"], v["ci95_pct"], v["estimated_false_positives"], v["estimated_range"])
