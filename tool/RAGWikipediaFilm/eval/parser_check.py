"""Checks the query parser against what the battery says each request contains. Offline when the parses are cached.

    python -m tool.RAGWikipediaFilm.eval.parser_check        # writes eval/results/PARSER_REPORT.md and parser_check.jsonl"""
from __future__ import annotations

import json
from collections import Counter

from ..retrieval import parser
from ..retrieval.corpus import norm
from .ab import RES, ROOT, jl_write

CATALOGUE = ROOT / "data" / "clean_v3" / "films.v3.jsonl"
MAX_SHARE = 0.08                      # an avoided genre term that matches more than this share of the catalogue is a too-wide filter

EXPECT_EXTRA = {   # id -> expected positive filters
    101: {"directors": ["fincher"]}, 102: {"actors": ["hanks"], "years": (1990, 1999)}, 103: {"countries": ["ital"], "years": (1970, 1979)},
    104: {"actors": ["murray"]}, 105: {"year_from": 2015}, 106: {"countries": ["giappon"], "years": (1950, 1959)}, 107: {"directors": ["miyazaki"]},
    108: {"countries": ["franc"]}, 109: {"actors": ["curtis"], "franchise": ["halloween"]}, 110: {"actors": ["streep"], "year_from": 2004},
    111: {"years": (2023, 2023)}, 112: {"directors": ["nolan"]}, 113: {"actors": ["eastwood"], "directors": ["eastwood"]},
    114: {"actors": ["zalone"], "years": (2000, 2009)},
}


def genre_shares() -> Counter:
    labels = Counter()
    n = 0
    for line in CATALOGUE.open(encoding="utf-8"):
        f = json.loads(line)
        n += 1
        for g in set(f.get("genres_norm") or []):
            labels[g] += 1
    return labels, n


def share(term_norm: str, labels: Counter, n: int, films=None) -> float:
    return sum(c for g, c in labels.items() if term_norm in g) / n     # upper bound (a film with two matching labels counts twice)


def main():
    cases = []
    for name in ("battery.json", "battery_extra.json"):
        cases += json.loads((ROOT / "eval" / name).read_text())["cases"]
    labels, n = genre_shares()
    rows = []
    for c in cases:
        s = parser.parse(c["question"])
        issues = []
        cited = {norm(t.title_it) for t in s.like_titles + s.avoid_titles} | {norm(t.title_original) for t in s.like_titles + s.avoid_titles}
        for t in c["exclude_titles"]:
            if norm(t) not in cited and not any(norm(t) in x or x in norm(t) for x in cited):
                issues.append(f"titolo da escludere non estratto: {t}")
        fr = [norm(x) for x in s.avoid_franchise_names]
        for name in c["avoid_franchise"]:
            if not any(norm(name) in x or x in norm(name) for x in fr) and not any(norm(name) in norm(t.title_original) for t in s.like_titles):
                issues.append(f"franchise non estratto: {name}")
        if c["category"] in "ACDF" and c["must_avoid"] and not (s.avoid_descriptions_it or s.avoid_genres_it or s.avoid_franchise_names or s.avoid_titles):
            issues.append("nessun segnale negativo estratto")
        if c["category"] in "ACDF" and s.avoid_descriptions_it and len(s.avoid_descriptions_it) != len(s.avoid_descriptions_en):
            issues.append("descrizioni negative it/en di numero diverso")
        keep = [norm(x) for x in s.keep_genres_it]
        for t in s.avoid_genres_it:
            tn = norm(t)
            sh = share(tn, labels, n)
            if sh > MAX_SHARE:
                issues.append(f"filtro di genere troppo ampio: «{t}» ({sh:.0%} del catalogo)")
            if any(tn == k for k in keep):
                issues.append(f"genere evitato = genere voluto: «{t}»")
        if len(s.avoid_genres_it) > 3:
            issues.append("troppi generi evitati")
        for p in s.avoid_descriptions_it:
            low = p.lower()
            if low.startswith(("senza ", "non ", "niente ", "evitare ")) or " senza " in low[:12]:
                issues.append(f"descrizione negativa formulata in negativo: «{p}»")
        if c["category"] == "D" and len(s.like_titles) < 2:
            issues.append("meno di 2 riferimenti positivi in una domanda D")
        if c["category"] == "H" and not s.contradictory:
            issues.append("contraddizione non rilevata")
        if c["category"] not in ("H",) and s.contradictory:
            issues.append("contraddizione rilevata dove non c'è")
        exp = EXPECT_EXTRA.get(c["id"])
        if exp:
            for k in ("directors", "actors", "countries"):
                for w in exp.get(k, []):
                    if not any(w in norm(x) for x in getattr(s, k)):
                        issues.append(f"{k} atteso «{w}» non estratto")
            if "years" in exp and (s.year_from, s.year_to) != exp["years"]:
                issues.append(f"anni attesi {exp['years']}, estratti {(s.year_from, s.year_to)}")
            if "year_from" in exp and (s.year_from or 0) < exp["year_from"]:
                issues.append(f"year_from atteso ≥{exp['year_from']}, estratto {s.year_from}")
            for w in exp.get("franchise", []):
                if not any(w in norm(x) for x in s.avoid_franchise_names):
                    issues.append(f"franchise atteso «{w}» non estratto")
        elif c["id"] < 100 and (s.year_from or s.year_to or s.directors or s.actors or s.countries):
            issues.append(f"filtri positivi inventati: anni {(s.year_from, s.year_to)}, registi {s.directors}, attori {s.actors}, paesi {s.countries}")
        rows.append({"id": c["id"], "category": c["category"], "question": c["question"], "issues": issues})
    jl_write("parser_check.jsonl", rows)
    bad = [r for r in rows if r["issues"]]
    L = ["# Verifica del parser sulle 76 domande (62 originali + 14 supplementari)", "",
         f"Domande senza problemi: {len(rows) - len(bad)}/{len(rows)}.", ""]
    kinds = Counter(i.split(":")[0].split(" (")[0] for r in bad for i in r["issues"])
    L += ["| Tipo di problema | Casi |", "|---|---|"] + [f"| {k} | {v} |" for k, v in kinds.most_common()] + [""]
    for r in bad:
        L.append(f"- **{r['id']}** ({r['category']}) {r['question'][:80]}: " + "; ".join(r["issues"]))
    (RES / "PARSER_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
