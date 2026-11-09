"""Reads the aggregated results and writes eval/results/ANALYSIS.md: dataset effect vs algorithm effect, stability of the judge, best and worst answers."""
from __future__ import annotations

import json

from .ab import CASES, RES, jl_read
from .report import det_hit


def main():
    S = json.loads((RES / "summary.json").read_text())
    R = S["retrieval"]
    L = ["# Analisi: effetto del dataset, effetto dell'algoritmo, stabilità del giudice, esempi", ""]
    pct = lambda x: f"{100 * x:.0f}%"
    L += ["## 1. Dataset contro algoritmo (domande A–G, 56 liste da 5 film)", "",
          "Percentuale di film **validi** (pertinenti e senza violazioni) e di **violazioni**. Effetto del dataset = NEW − OLD con lo stesso algoritmo; "
          "effetto dell'algoritmo = strategia − S0 sullo stesso corpus.", "",
          "| Algoritmo | OLD validi | NEW validi | effetto dataset | OLD violaz. | NEW violaz. |", "|---|---|---|---|---|---|"]
    for s in ("S0", "S1", "S2n", "S3", "S5", "S6"):
        o, n = R[f"OLD-{s}"], R[f"NEW-{s}"]
        L.append(f"| {s} | {pct(o['valid'])} | {pct(n['valid'])} | {100 * (n['valid'] - o['valid']):+.0f} pt | {pct(o['violation'])} | {pct(n['violation'])} |")
    L += ["", "| Corpus | S0 validi | S5 validi | S6 validi | guadagno S0→S5 | guadagno S0→S6 |", "|---|---|---|---|---|---|"]
    for c in ("OLD", "NEW"):
        v = [R[f"{c}-{s}"]["valid"] for s in ("S0", "S5", "S6")]
        L.append(f"| {c} | {pct(v[0])} | {pct(v[1])} | {pct(v[2])} | {100 * (v[1] - v[0]):+.0f} pt | {100 * (v[2] - v[0]):+.0f} pt |")
    L += ["", "La pipeline antica come gira nell'applicazione (OLD-NATIVE): validi " + pct(R["OLD-NATIVE"]["valid"]) + ", violazioni " + pct(R["OLD-NATIVE"]["violation"]) +
          f"; il nuovo con l'algoritmo completo (NEW-S6): validi {pct(R['NEW-S6']['valid'])}, violazioni {pct(R['NEW-S6']['violation'])}.", ""]

    # ---- judge stability
    p1 = {(p["id"], tuple(p["pair"])): p["winner"] for p in jl_read("pairwise.jsonl")}
    p2 = {(p["id"], tuple(p["pair"])): p["winner"] for p in jl_read("pairwise_swap.jsonl")}
    same = sum(1 for k in p1 if k in p2 and p1[k] == p2[k])
    both = [k for k in p1 if k in p2]
    flip = sum(1 for k in both if p1[k] != "tie" and p2[k] != "tie" and p1[k] != p2[k])
    L += ["## 2. Stabilità del giudice (secondo passaggio con un altro ordine casuale)", "",
          f"Stesso vincitore in {same}/{len(both)} confronti ({pct(same / len(both))}); vincitori opposti (senza pareggi) in {flip}.", ""]
    tot = {}
    for k in both:
        pair = k[1]
        for w in (p1[k], p2[k]):
            d = tot.setdefault(" vs ".join(pair), {"first": 0, "second": 0, "tie": 0})
            d["first" if w == pair[0] else "second" if w == pair[1] else "tie"] += 1
    L += ["| Confronto (due passaggi, 124 giudizi) | primo | secondo | pareggi |", "|---|---|---|---|"]
    for k, d in tot.items():
        L.append(f"| {k} | {d['first']} | {d['second']} | {d['tie']} |")
    L += ["", "Limiti: il giudice è lo stesso modello che esegue il parser e il rerank (possibile preferenza per i propri criteri); le trame del nuovo sono in italiano "
          "come la domanda e quelle del vecchio in inglese, quindi nel confronto sulle risposte la lingua dell'evidenza può avvantaggiare il nuovo; per questo le "
          "metriche per film (sezioni 1–3 del REPORT) restano il riferimento principale.", ""]

    # ---- examples
    ans = {(a["id"], a["corpus"], a["strategy"]): a for a in jl_read("answers.jsonl")}
    pw = [p for p in jl_read("pairwise.jsonl") if "old/NATIVE" in p["pair"][1]]
    gap = []
    for p in pw:
        s = p["scores"]
        new, old = s["new/S6"], s["old/NATIVE"]
        gap.append((sum(new.values()) - sum(old.values()), p))
    gap.sort(key=lambda x: x[0])

    def show(label, items, key_new, key_old):
        out = [f"### {label}", ""]
        for g, p in items:
            q = p["id"]
            out += [f"**Domanda {q}** — {CASES[q]['question']}  (scarto di punteggio nuovo−vecchio: {g:+d})", "",
                    f"- NEW-S6: {ans[(q,'new','S6')]['answer'][:600]}", f"- OLD-NATIVE: {ans[(q,'old','NATIVE')]['answer'][:600]}", f"- Giudice: {p['reason'][:300]}", ""]
        return out
    L += ["## 3. Migliori e peggiori risposte", ""] + show("Dove il nuovo vince di più (NEW-S6 contro OLD-NATIVE)", gap[::-1][:3], "new", "old") + \
         show("Dove il vecchio fa meglio o il nuovo vince di meno", gap[:3], "new", "old")
    ret = {(r["id"], r["corpus"], r["strategy"]): r for r in jl_read("retrieval.jsonl")}
    L += ["### Violazioni residue nelle risposte finali (film consigliati che violano un'esclusione)", ""]
    judg = {(j["id"], j["corpus"], j["point_id"]): j for j in jl_read("film_judgments.jsonl")}
    for (q, c, s), a in sorted(ans.items()):
        if CASES[q]["category"] == "H" or (c, s) not in (("new", "S6"), ("old", "NATIVE")):
            continue
        by = {f["point_id"]: f for f in ret[(q, c, s)]["films"]}
        bad = []
        for pid in a["recommended_point_ids"]:
            j = judg.get((q, c, pid))
            f = by.get(pid)
            if f and j and (j["shows_avoid"] or j["is_excluded"] or det_hit(CASES[q], f)):
                bad.append(f"{f['title']} ({j['reason'][:90]})")
        if bad:
            L.append(f"- {c.upper()}-{s}, domanda {q} «{CASES[q]['question'][:70]}…»: " + "; ".join(bad))
    (RES / "ANALYSIS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:50]))


if __name__ == "__main__":
    main()
