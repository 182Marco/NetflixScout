"""Render ab_results.json as markdown (read-only): per-case table, per-variant table, criteria verdict."""
from __future__ import annotations

import json
import sys
from pathlib import Path

r = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = ["# Fase 5 - risultati automatici A/B/C (nessun giudizio qualitativo)", ""]
info = r["info"]
out += ["## Medie per variante (casi con il dato disponibile)", "",
        "| variante | pertinenza testo | vicinanza positivi | vicinanza negativi | max coseno a un positivo | latenza mediana (ms) |", "|---|---|---|---|---|---|"]
for v, name in (("A", "A normale"), ("B", "B average_vector"), ("C", "C best_score")):
    m = info["means_by_variant"][v]
    out.append(f"| {name} | {m['text_sim']:.3f} | {m['pos_mean']:.3f} | {m['neg_mean']:.3f} | {m['max_single_pos_mean']:.3f} | {info['latency_ms_median_of_medians'][v]} |")
out += ["", f"Casi: {info['case_counts']}. Sovrapposizione media con A: {info['overlap_with_A_mean']}. HNSW ef=128 contro esatta, sovrapposizione minima: {info['hnsw_ef128_min_overlap_with_exact']}.", ""]
out += ["## Criteri del protocollo (scritti prima della misura)", "", "| criterio | B average_vector | C best_score |", "|---|---|---|"]
b, c = r["verdict"]["B"], r["verdict"]["C"]
flag = lambda ok: "OK" if ok else "**NON soddisfatto**"  # noqa: E731
out += [
    f"| 1 negativi: calo medio >= 0,02 e in >= 60% dei casi | {flag(b['1_negatives']['ok'])}: media {b['1_negatives']['mean_delta']:+.4f}, calo in {b['1_negatives']['share_with_drop']:.0%} ({b['1_negatives']['cases']} casi) | {flag(c['1_negatives']['ok'])}: media {c['1_negatives']['mean_delta']:+.4f}, calo in {c['1_negatives']['share_with_drop']:.0%} |",
    f"| 2 pertinenza al testo: calo medio <= 0,02 | {flag(b['2_text_relevance']['ok_mean'])}: media {b['2_text_relevance']['mean_delta']:+.4f} | {flag(c['2_text_relevance']['ok_mean'])}: media {c['2_text_relevance']['mean_delta']:+.4f} |",
    f"| 2 (per caso) nessuna perdita > 0,05 | {len(b['2_text_relevance']['exceptions_per_case'])} eccezioni su {b['2_text_relevance']['cases']} | {len(c['2_text_relevance']['exceptions_per_case'])} eccezioni su {c['2_text_relevance']['cases']} |",
    f"| 3 positivi: calo medio <= 0,02 | {flag(b['3_positives']['ok_mean'])}: media {b['3_positives']['mean_delta']:+.4f} | {flag(c['3_positives']['ok_mean'])}: media {c['3_positives']['mean_delta']:+.4f} |",
    f"| 3 (per riferimento) nessuna perdita > 0,05 | {len(b['3_positives']['exceptions_per_reference'])} eccezioni | {len(c['3_positives']['exceptions_per_reference'])} eccezioni |",
    f"| 4 vincoli: violazioni totali <= A | {flag(b['4_constraints']['ok_total'])}: {b['4_constraints']['total_B']} contro {b['4_constraints']['total_A']} | {flag(c['4_constraints']['ok_total'])}: {c['4_constraints']['total_C']} contro {c['4_constraints']['total_A']} |",
    f"| 5 riferimenti nei risultati = 0 | {flag(b['5_reference_leaks']['ok'])}: {b['5_reference_leaks']['standard_config_leaks']} (senza esclusioni del parser: {b['5_reference_leaks']['without_hard_exclusions_resolved_refs']}) | {flag(c['5_reference_leaks']['ok'])}: {c['5_reference_leaks']['standard_config_leaks']} (senza: {c['5_reference_leaks']['without_hard_exclusions_resolved_refs']}) |",
    f"| 6 controlli senza riferimenti validi = A | {flag(b['6_controls_identical_to_A']['ok'])}: {b['6_controls_identical_to_A']['identical']}/{b['6_controls_identical_to_A']['controls']} | {flag(c['6_controls_identical_to_A']['ok'])}: {c['6_controls_identical_to_A']['identical']}/{c['6_controls_identical_to_A']['controls']} |",
    f"| **Tutti i criteri** | **{'SI' if b['all_ok'] else 'NO'}** | **{'SI' if c['all_ok'] else 'NO'}** |",
    "",
    f"Esito: **{'nessuna variante migliora abbastanza la baseline' if not (b['all_ok'] or c['all_ok']) else 'almeno una variante soddisfa i criteri'}**.", "",
    "## Per caso (differenza rispetto ad A: negativi, testo, positivi; violazioni A/B/C; sovrapposizione con A)", "",
    "| caso | categoria | riferimenti usabili (+/-) | neg B/C | testo B/C | pos B/C | viol. A/B/C | sovrapp. B/C |", "|---|---|---|---|---|---|---|---|"]
for case in r["cases"]:
    V = case["variants"]

    def d(v, k):
        a, s = V["A"].get(k), V[v].get(k)
        return "-" if a is None or s is None else f"{s - a:+.3f}"

    note = " (controllo)" if case["control"] else ""
    out.append(f"| {case['id']}{note} | {case['category']} | {case['usable_positive']}/{case['usable_negative']} | {d('B','neg_mean')} / {d('C','neg_mean')} | {d('B','text_sim')} / {d('C','text_sim')} | {d('B','pos_mean')} / {d('C','pos_mean')} | {V['A']['violations_total']}/{V['B']['violations_total']}/{V['C']['violations_total']} | {V['B']['overlap_with_A']:.1f} / {V['C']['overlap_with_A']:.1f} |")
out += ["", "## Stato di risoluzione dei riferimenti", ""]
counts: dict[str, int] = {}
for case in r["cases"]:
    for e in case["references"]:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
out.append(", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + f". Anomalie di risoluzione rispetto all'atteso congelato: {r['anomalies'] or 'nessuna'}.")
sys.stdout.write("\n".join(out) + "\n")
