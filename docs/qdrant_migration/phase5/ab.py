"""Phase 5 A/B/C: plain search vs average_vector vs best_score, on the FROZEN cases. No paid call.

    QDRANT_URL=http://127.0.0.1:6333 python docs/qdrant_migration/phase5/ab.py \
        --baseline DIR --out-dir docs/qdrant_migration/phase5

Refuses to run if cases.json or the text vectors differ from the hashes recorded in cases.sha256.
The acceptance criteria are the ones written in protocol.md BEFORE the measurement; this script only
applies them. The qualitative sheets are written blind (shuffled labels, key in a separate file) and
are NOT scored here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tool.rag.FromQueryEmbeddingToRes import vectorstore  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.references import (  # noqa: E402
    ReferenceInput, ReferenceSet, resolve_references)
from tool.rag.FromQueryEmbeddingToRes.store import norm_title, year_int  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.collection import close_clients  # noqa: E402

K, FETCH_K, GENRE_BOOST = 10, 50, 0.15
# Thresholds written in protocol.md (Fase 5) before any measurement
NEG_DROP_MEAN, NEG_DROP_SHARE = 0.02, 0.60
TEXT_MEAN_TOL, TEXT_CASE_TOL = 0.02, 0.05
POS_MEAN_TOL, POS_REF_TOL = 0.02, 0.05
SEED = 20261026


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def verify_frozen(case_dir: Path, baseline: Path) -> None:
    for line in (case_dir / "cases.sha256").read_text().splitlines():
        digest, _, name = line.partition("  ")
        path = case_dir / name if name == "cases.json" else baseline / Path(name).name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"refused: {name} differs from the hash recorded before the measurement")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    base, out_dir = Path(args.baseline), Path(args.out_dir)
    verify_frozen(out_dir, base)
    url = os.environ["QDRANT_URL"]
    spec = json.loads((out_dir / "cases.json").read_text(encoding="utf-8"))

    def store_cfg(**extra) -> dict:
        return {"engine": "qdrant", "qdrant": {"mode": "server", "url": url, "model": "text-embedding-3-small",
                                                "dimension": 1536, **extra}}

    exact = vectorstore.apri_collection("netflix_scout", store_config=store_cfg(exact=True))
    hnsw = vectorstore.apri_collection("netflix_scout", store_config=store_cfg(ef=128))
    store = exact.store
    vcache: dict[str, np.ndarray] = {}

    def vec_of(legacy_id: str) -> np.ndarray:
        if legacy_id not in vcache:
            vcache[legacy_id] = unit(store.vector_of(legacy_id))
        return vcache[legacy_id]

    original_embed = vectorstore.embed
    results: list[dict] = []
    sheets: list[dict] = []
    anomalies: list[str] = []

    def search(col, text_vec, case, refs, *, with_hard: bool):
        constraints = case["constraints"]
        titles = [r["title"] for r in case["like"] + case["avoid"]]
        vectorstore.embed = lambda texts, backend=None, model=None, _v=text_vec: np.asarray([_v], dtype=np.float32)
        return vectorstore.search(
            col, "q", K, backend="local", model="m", hard_exclusions=titles if with_hard else [],
            fetch_k=FETCH_K, genres=constraints.get("genres"), genre_boost=GENRE_BOOST,
            excluded_genres=constraints.get("excluded_genres"), references=refs)

    def new_refs(entries, strategy):
        return ReferenceSet(entries=entries, strategy=strategy, text_repeat=1)

    try:
        for case in spec["cases"]:
            text_vec = np.load(base / f"{case['text_id']}.vec.npy")
            text_unit = unit(text_vec)
            baseline_rec = json.loads((base / f"{case['text_id']}.json").read_text())
            like = [ReferenceInput(r["title"], r["year"]) for r in case["like"]]
            avoid = [ReferenceInput(r["title"], r["year"]) for r in case["avoid"]]
            entries = resolve_references(store, like, avoid).entries
            for e, expected in zip(entries, [r["expected_status"] for r in case["like"] + case["avoid"]]):
                if e.status != expected:
                    anomalies.append(f"{case['id']}: '{e.title}' resolved as {e.status}, expected {expected}")
            usable = [e for e in entries if e.vector is not None and e.status in ("resolved", "estimated")]
            pos = [e for e in usable if e.role == "positive"]
            neg = [e for e in usable if e.role == "negative"]
            ref_titles = {norm_title(r["title"]): r["title"] for r in case["like"] + case["avoid"]}
            resolved_ids = {str(i): e.title for e in entries if e.status == "resolved"
                            for i in [e.movie_id, *e.homonym_movie_ids] if i}
            status_of = {norm_title(e.title): e.status for e in entries}

            def metrics(rows: list[dict]) -> dict:
                items = [vec_of(r["id"]) for r in rows]
                m: dict = {"ids": [r["id"] for r in rows], "titles": [f"{r.get('title') or r.get('source')} ({r.get('release_year') or '?'})" for r in rows]}
                m["text_sim"] = float(np.mean([it @ text_unit for it in items])) if items else None
                if pos:
                    per = [float(np.mean([it @ unit(e.vector) for it in items])) for e in pos]
                    m["pos_per_ref"] = per
                    m["pos_mean"], m["pos_min_ref"] = float(np.mean(per)), float(min(per))
                    single = [max(float(it @ unit(e.vector)) for e in pos) for it in items]
                    m["max_single_pos_mean"], m["max_single_pos_min"] = float(np.mean(single)), float(min(single))
                if neg:
                    per = [float(np.mean([it @ unit(e.vector) for it in items])) for e in neg]
                    m["neg_per_ref"] = per
                    m["neg_mean"] = float(np.mean(per))
                    m["neg_max_item"] = float(max(it @ unit(e.vector) for it in items for e in neg))
                c = case["constraints"]
                viol = {"excluded_genre": 0, "required_genre_missing": 0, "year_out_of_range": 0, "year_unknown": 0}
                for r in rows:
                    if c.get("excluded_genres") and vectorstore.has_excluded_genre(r, c["excluded_genres"]):
                        viol["excluded_genre"] += 1
                    if c.get("genres") and not vectorstore._matches_genres(r, c["genres"]):
                        viol["required_genre_missing"] += 1
                    if c.get("year_range"):
                        y = year_int(r.get("release_year"))
                        if y is None:
                            viol["year_unknown"] += 1
                        elif not c["year_range"][0] <= y <= c["year_range"][1]:
                            viol["year_out_of_range"] += 1
                m["violations"] = viol
                m["violations_total"] = viol["excluded_genre"] + viol["required_genre_missing"] + viol["year_out_of_range"]
                leaks = []
                for r in rows:
                    t = norm_title(r.get("title"))
                    if str(r.get("movie_id")) in resolved_ids or t in ref_titles:
                        leaks.append({"title": r.get("title"), "year": r.get("release_year"),
                                      "reference_status": status_of.get(t, "resolved-homonym-or-id")})
                m["leaks"] = leaks
                return m

            rec = {"id": case["id"], "category": case["category"], "text_id": case["text_id"],
                   "embedded_text": baseline_rec["embedded_text"], "constraints": case["constraints"],
                   "references": [e.trace() for e in entries], "usable_positive": len(pos), "usable_negative": len(neg),
                   "control": not usable, "variants": {}, "no_hard_exclusion_leaks": {}}
            rows_by: dict[str, list[dict]] = {}
            for name, strategy in (("A", None), ("B", "average_vector"), ("C", "best_score")):
                refs = None if strategy is None else new_refs(list(entries), strategy)
                times, rows = [], []
                for _ in range(5):
                    t0 = time.perf_counter()
                    rows = search(exact, text_unit, case, new_refs(list(entries), strategy) if strategy else None, with_hard=True)
                    times.append((time.perf_counter() - t0) * 1000)
                rows_by[name] = rows
                rec["variants"][name] = {**metrics(rows), "latency_ms_median": round(statistics.median(times), 1)}
                # same variant WITHOUT the parser's hard exclusions: what protects against reference leaks
                free = search(exact, text_unit, case, new_refs(list(entries), strategy) if strategy else None, with_hard=False)
                rec["no_hard_exclusion_leaks"][name] = metrics(free)["leaks"]
            for name in ("B", "C"):
                v = rec["variants"][name]
                v["overlap_with_A"] = len(set(v["ids"]) & set(rec["variants"]["A"]["ids"])) / K
                v["identical_to_A"] = v["ids"] == rec["variants"]["A"]["ids"]
                strategy = "average_vector" if name == "B" else "best_score"
                approx = search(hnsw, text_unit, case, new_refs(list(entries), strategy), with_hard=True)
                v["hnsw_ef128_overlap_with_exact"] = len(set(r["id"] for r in approx) & set(v["ids"])) / K
            results.append(rec)

            if usable:
                labels = ["X", "Y", "Z"]
                random.Random(f"{SEED}-{case['id']}").shuffle(labels)
                sheets.append({"case": case["id"], "text": baseline_rec["embedded_text"],
                               "like": [f"{r['title']} ({r['year'] or '?'})" for r in case["like"]],
                               "avoid": [f"{r['title']} ({r['year'] or '?'})" for r in case["avoid"]],
                               "constraints": case["constraints"],
                               "key": dict(zip(["A", "B", "C"], labels)),
                               "lists": {labels[i]: [
                                   {"title": r.get("title") or r.get("source"), "year": r.get("release_year"), "genres": r.get("genres"),
                                    "plot": (r.get("testo") or "")[:220]} for r in rows_by[v][:5]]
                                   for i, v in enumerate(["A", "B", "C"])}})
    finally:
        vectorstore.embed = original_embed
        close_clients()

    # ---------------- aggregation: the criteria of protocol.md
    def delta(case, variant, key):
        a, s = case["variants"]["A"].get(key), case["variants"][variant].get(key)
        return None if a is None or s is None else s - a

    N = [c for c in results if c["usable_negative"]]
    P = [c for c in results if c["usable_positive"]]
    R = [c for c in results if not c["control"]]
    ctrl = [c for c in results if c["control"]]
    verdict: dict = {}
    for v in ("B", "C"):
        dn = [delta(c, v, "neg_mean") for c in N]
        dt = [delta(c, v, "text_sim") for c in R]
        dp = [delta(c, v, "pos_mean") for c in P]
        ref_losses = []
        for c in P:
            for n, (a, s) in enumerate(zip(c["variants"]["A"]["pos_per_ref"], c["variants"][v]["pos_per_ref"])):
                ref_losses.append((c["id"], n, s - a))
        viol = [(c["id"], c["variants"][v]["violations_total"] - c["variants"]["A"]["violations_total"]) for c in results]
        leak_std = sum(len(c["variants"][v]["leaks"]) for c in results)
        leak_free_resolved = sum(1 for c in results for lk in c["no_hard_exclusion_leaks"][v]
                                 if lk["reference_status"] in ("resolved", "resolved-homonym-or-id"))
        leak_free_other = sum(1 for c in results for lk in c["no_hard_exclusion_leaks"][v]
                              if lk["reference_status"] not in ("resolved", "resolved-homonym-or-id"))
        crit = {
            "1_negatives": {"cases": len(N), "mean_delta": round(float(np.mean(dn)), 4),
                            "share_with_drop": round(sum(d < 0 for d in dn) / len(dn), 3),
                            "ok": bool(np.mean(dn) <= -NEG_DROP_MEAN and sum(d < 0 for d in dn) / len(dn) >= NEG_DROP_SHARE)},
            "2_text_relevance": {"cases": len(R), "mean_delta": round(float(np.mean(dt)), 4),
                                 "ok_mean": bool(np.mean(dt) >= -TEXT_MEAN_TOL),
                                 "exceptions_per_case": [(c["id"], round(d, 4)) for c, d in zip(R, dt) if d < -TEXT_CASE_TOL]},
            "3_positives": {"cases": len(P), "mean_delta": round(float(np.mean(dp)), 4),
                            "ok_mean": bool(np.mean(dp) >= -POS_MEAN_TOL),
                            "exceptions_per_reference": [(i, n, round(d, 4)) for i, n, d in ref_losses if d < -POS_REF_TOL]},
            "4_constraints": {"total_A": sum(c["variants"]["A"]["violations_total"] for c in results),
                              f"total_{v}": sum(c["variants"][v]["violations_total"] for c in results),
                              "ok_total": sum(c["variants"][v]["violations_total"] for c in results) <= sum(c["variants"]["A"]["violations_total"] for c in results),
                              "exceptions_per_case": [(i, d) for i, d in viol if d > 0]},
            "5_reference_leaks": {"standard_config_leaks": leak_std,
                                  "without_hard_exclusions_resolved_refs": leak_free_resolved,
                                  "without_hard_exclusions_ambiguous_or_absent_refs": leak_free_other,
                                  "ok": leak_std == 0 and leak_free_resolved == 0},
            "6_controls_identical_to_A": {"controls": len(ctrl), "identical": sum(c["variants"][v]["identical_to_A"] for c in ctrl),
                                          "ok": all(c["variants"][v]["identical_to_A"] for c in ctrl)},
        }
        crit["all_ok"] = bool(crit["1_negatives"]["ok"] and crit["2_text_relevance"]["ok_mean"] and crit["3_positives"]["ok_mean"]
                              and crit["4_constraints"]["ok_total"] and crit["5_reference_leaks"]["ok"]
                              and crit["6_controls_identical_to_A"]["ok"])
        crit["all_ok_including_per_case_checks_without_exceptions"] = bool(
            crit["all_ok"] and not crit["2_text_relevance"]["exceptions_per_case"]
            and not crit["3_positives"]["exceptions_per_reference"] and not crit["4_constraints"]["exceptions_per_case"])
        verdict[v] = crit

    info = {
        "means_by_variant": {v: {k: round(float(np.mean([c["variants"][v][k] for c in results if c["variants"][v].get(k) is not None])), 4)
                                 for k in ("text_sim", "pos_mean", "neg_mean", "max_single_pos_mean")}
                             for v in ("A", "B", "C")},
        "latency_ms_median_of_medians": {v: round(statistics.median(c["variants"][v]["latency_ms_median"] for c in results), 1) for v in ("A", "B", "C")},
        "hnsw_ef128_min_overlap_with_exact": {v: min(c["variants"][v]["hnsw_ef128_overlap_with_exact"] for c in R) for v in ("B", "C")},
        "overlap_with_A_mean": {v: round(float(np.mean([c["variants"][v]["overlap_with_A"] for c in R])), 3) for v in ("B", "C")},
        "case_counts": {"total": len(results), "with_negative": len(N), "with_positive": len(P), "active": len(R), "controls": len(ctrl)},
    }
    report = {"frozen": json.loads((out_dir / "cases.json").read_text())["frozen_on"], "anomalies": anomalies,
              "info": info, "verdict": verdict, "cases": results}
    (out_dir / "ab_results.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---- blind sheets (no scores) + key in a separate file
    lines = ["# Scheda di valutazione qualitativa CIECA - Fase 5", "",
             "Per ogni caso trovi tre elenchi anonimi (X, Y, Z) dei primi 5 risultati. Non e' indicato quale variante li ha prodotti.",
             "Griglia per ogni elenco (0 = no, 1 = in parte, 2 = si): **pertinenza** alla richiesta - **vicinanza** ai film piacevoli - **assenza** del tratto dei film da evitare - **fatti** corretti (titolo/anno/genere coerenti con la trama).",
             "Compila prima di aprire `qualitative_key.json` e prima di leggere `ab_summary.md`.", ""]
    for sh in sheets:
        lines += [f"## Caso {sh['case']}", f"- Richiesta (testo): {sh['text']}",
                  f"- Mi piacciono: {', '.join(sh['like']) or '-'}", f"- Da evitare: {', '.join(sh['avoid']) or '-'}"]
        if sh["constraints"]:
            lines.append(f"- Vincoli: {json.dumps(sh['constraints'], ensure_ascii=False)}")
        for label in ("X", "Y", "Z"):
            lines += ["", f"### Elenco {label}   (pertinenza __ / vicinanza __ / assenza __ / fatti __)"]
            for n, it in enumerate(sh["lists"][label], 1):
                lines.append(f"{n}. **{it['title']}** ({it['year'] or '?'}) - {it['genres'] or '-'} - {it['plot']}...")
        lines.append("")
    (out_dir / "qualitative_sheets.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "qualitative_key.json").write_text(json.dumps(
        {"seed": SEED, "note": "key per case: variant -> label. Do not open before scoring.",
         "keys": {sh["case"]: sh["key"] for sh in sheets}}, indent=1), encoding="utf-8")
    sys.stdout.write(json.dumps({"anomalies": anomalies, "info": info, "verdict": verdict}, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
