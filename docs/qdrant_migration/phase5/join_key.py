"""Reveal the variants: join the SAVED qualitative scores with the key. Run only after scoring.

Refuses to run if the judgments or the scores differ from the hashes recorded when they were saved.
Numeric results and the qualitative reading are written as separate sections.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIMS = ("pertinenza", "vicinanza", "assenza", "fatti")


def main() -> None:
    for line in (HERE / "qualitative_scores.sha256").read_text().splitlines():
        digest, _, name = line.partition("  ")
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"refused: {name} changed after the evaluation was saved")
    scores = json.loads((HERE / "qualitative_scores.json").read_text(encoding="utf-8"))["scores"]
    keys = json.loads((HERE / "qualitative_key.json").read_text(encoding="utf-8"))["keys"]

    by_variant: dict[str, dict[str, dict[str, int | None]]] = {v: {} for v in "ABC"}
    for case, mapping in keys.items():
        for variant, label in mapping.items():
            by_variant[variant][case] = scores[case][label]

    def mean(variant: str, dim: str, cases=None):
        vals = [s[dim] for c, s in by_variant[variant].items() if s[dim] is not None and (cases is None or c in cases)]
        return None if not vals else round(sum(vals) / len(vals), 3)

    summary = {"variants": {}, "paired_vs_A": {}, "per_case": {}, "identical_lists": []}
    for v in "ABC":
        summary["variants"][v] = {d: mean(v, d) for d in DIMS}
        summary["variants"][v]["n_cases"] = {d: sum(1 for s in by_variant[v].values() if s[d] is not None) for d in DIMS}
    for v in ("B", "C"):
        paired = {}
        for d in DIMS:
            better = equal = worse = 0
            for case in by_variant["A"]:
                a, s = by_variant["A"][case][d], by_variant[v][case][d]
                if a is None or s is None:
                    continue
                better += s > a
                worse += s < a
                equal += s == a
            paired[d] = {"better": better, "equal": equal, "worse": worse}
        summary["paired_vs_A"][v] = paired
    for case in keys:
        row = {v: {d: by_variant[v][case][d] for d in DIMS} for v in "ABC"}
        summary["per_case"][case] = row
        lists = {v: json.dumps({d: by_variant[v][case][d] for d in DIMS}, sort_keys=True) for v in "ABC"}
        for x, y in (("A", "B"), ("A", "C"), ("B", "C")):
            if lists[x] == lists[y]:
                summary["identical_lists"].append((case, x, y))
    (HERE / "qualitative_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    lines = ["# Fase 5 - valutazione qualitativa cieca: riepilogo per variante", "",
             "**Valutatore: il modello (non una persona).** Cecita' imperfetta: le metriche automatiche aggregate erano gia' note, la mappa etichetta-variante no. "
             "Un solo valutatore: evidenza indicativa, non statistica. I punteggi sono 0/1/2 per elenco di 5 risultati.", "",
             "## A. Risultati numerici (punteggi medi per variante)", "",
             "| variante | pertinenza | vicinanza | assenza del tratto da evitare | fatti |", "|---|---|---|---|---|"]
    names = {"A": "A ricerca normale", "B": "B average_vector", "C": "C best_score"}
    for v in "ABC":
        s = summary["variants"][v]
        lines.append(f"| {names[v]} | {s['pertinenza']} | {s['vicinanza']} | {s['assenza']} | {s['fatti']} |")
    n = summary["variants"]["A"]["n_cases"]
    lines += ["", f"Casi per dimensione: {n} (vicinanza e assenza esistono solo dove la scheda ha film piacevoli / da evitare).", "",
              "Confronto accoppiato con A (numero di casi migliori / uguali / peggiori):", "",
              "| variante | pertinenza | vicinanza | assenza | fatti |", "|---|---|---|---|---|"]
    for v in ("B", "C"):
        p = summary["paired_vs_A"][v]
        lines.append(f"| {names[v]} | " + " | ".join(f"{p[d]['better']}/{p[d]['equal']}/{p[d]['worse']}" for d in DIMS) + " |")
    lines += ["", "## B. Per caso (P/V/A/F per A | B | C)", "", "| caso | A | B | C |", "|---|---|---|---|"]
    fmt = lambda r: "/".join("-" if r[d] is None else str(r[d]) for d in DIMS)  # noqa: E731
    for case in sorted(keys):
        r = summary["per_case"][case]
        lines.append(f"| {case} | {fmt(r['A'])} | {fmt(r['B'])} | {fmt(r['C'])} |")
    (HERE / "qualitative_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"variants": summary["variants"], "paired_vs_A": summary["paired_vs_A"]}, indent=1))


if __name__ == "__main__":
    main()
