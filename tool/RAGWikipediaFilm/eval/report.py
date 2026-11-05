"""Aggregates the raw results of `eval/ab.py` into eval/results/REPORT.md and summary.json. Quantitative metrics first; the LLM judge's
winners are reported next to them, never instead of them."""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from statistics import mean

from ..retrieval.corpus import norm
from .ab import BATTERY, CASES, PREFIX, RES, jl_read

CATS = BATTERY["categories"]
NL_CATS = set("ACDF")          # exclusions expressed as traits in natural language
TITLE_CATS = set("BE")         # exclusions expressed as titles / franchises
SYSTEMS = [("new", "S0"), ("old", "S0")] if False else [("new", s) for s in ("S0", "S1", "S2n", "S2f", "S3", "S3b", "S4", "S5", "S6")] + [("old", s) for s in ("S0", "S1", "S2n", "S3", "S3b", "S4", "S5", "S6", "NATIVE")] + [(c, s) for c in ("new", "old") for s in ("S5f", "S6f", "S6w")]


def sys_name(c, s):
    return f"{'NEW' if c == 'new' else 'OLD'}-{s}"


def det_hit(case: dict, film: dict) -> bool:
    """Deterministic exclusion check from the battery itself (independent of the parser and of the judge)."""
    titles = {norm(film.get("title")), norm(film.get("original_title"))} - {""}
    for t in case["exclude_titles"]:
        if norm(t) in titles:
            return True
    for name in case["avoid_franchise"]:
        words = norm(name).split()
        pat = r"\b" + r"\s+".join(w + ("s?" if i == len(words) - 1 else "") for i, w in enumerate(words)) + r"\b"
        if any(re.search(pat, t) for t in titles):
            return True
    return False


def sign_p(w: int, l: int) -> float:
    n = w + l
    if n == 0:
        return 1.0
    k = max(w, l)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n)


def main() -> int:
    ret = jl_read("retrieval.jsonl")
    judg = {(j["id"], j["corpus"], j["point_id"]): j for j in jl_read("film_judgments.jsonl")}
    answers = {(a["id"], a["corpus"], a["strategy"]): a for a in jl_read("answers.jsonl")}
    pair = jl_read("pairwise.jsonl")
    parsed = {p["id"]: p["signals"] for p in jl_read("parsed_signals.jsonl")}
    by_key = {(r["id"], r["corpus"], r["strategy"]): r for r in ret}

    def flags(qid, corpus, f):
        j = judg.get((qid, corpus, f["point_id"]))
        case = CASES[qid]
        det = det_hit(case, f)
        if j is None:
            return None
        viol = bool(j["shows_avoid"] or j["is_excluded"] or det)
        return {"viol": viol, "det": det, "avoid": bool(j["shows_avoid"]), "excl": bool(j["is_excluded"]), "pos": bool(j["matches_positive"]),
                "genre": bool(j["genre_ok"]), "valid": bool(j["matches_positive"] and not viol)}

    # ---------------- retrieval metrics per system
    metrics = {}
    systems = sorted({(r["corpus"], r["strategy"]) for r in ret}, key=lambda t: ([x[1] for x in SYSTEMS].index(t[1]) if t[1] in [x[1] for x in SYSTEMS] else 99, t))
    for (c, s) in systems:
        rows = [r for r in ret if r["corpus"] == c and r["strategy"] == s and not r.get("error")]
        if not rows:
            continue
        per_cat = defaultdict(list)
        allf = []
        for r in rows:
            fl = [flags(r["id"], c, f) for f in r["films"]]
            fl = [x for x in fl if x]
            cat = CASES[r["id"]]["category"]
            per_cat[cat].append((r, fl))
            allf.append((r, fl))
        def agg(items, rows_only=lambda cat: True):
            fl = [x for r, l in items for x in l]
            n = len(fl)
            return {"lists": len(items), "films": n, "violation": sum(x["viol"] for x in fl) / n if n else None,
                    "pertinent": sum(x["pos"] for x in fl) / n if n else None, "valid": sum(x["valid"] for x in fl) / n if n else None,
                    "genre_kept": sum(x["genre"] for x in fl) / n if n else None, "empty_lists": sum(1 for r, l in items if not l),
                    "lists_with_violation": sum(1 for r, l in items if any(x["viol"] for x in l)),
                    "title_or_franchise_violations": sum(1 for x in fl if x["excl"] or x["det"]),
                    "trait_violations": sum(1 for x in fl if x["avoid"] and not (x["excl"] or x["det"]))}
        scored = [(r, l) for r, l in allf if CASES[r["id"]]["category"] != "H"]
        m = agg(scored)
        m["seconds_mean"] = round(mean(r["seconds"] for r in rows), 2)
        m["by_category"] = {cat: agg(v) for cat, v in sorted(per_cat.items())}
        m["nl_exclusions"] = agg([(r, l) for r, l in scored if CASES[r["id"]]["category"] in NL_CATS])
        m["title_exclusions"] = agg([(r, l) for r, l in scored if CASES[r["id"]]["category"] in TITLE_CATS])
        m["reference_coverage"] = None
        cov = [r["trace"].get("coverage") for r in rows if r["trace"].get("coverage")]
        if cov:
            tot, inn = sum(x["refs"] for x in cov), sum(x["refs_in_index"] for x in cov)
            m["reference_coverage"] = {"refs": tot, "in_index": inn, "share": round(inn / tot, 3) if tot else None}
        # collateral loss against S0 of the same corpus: valid films of S0 that this strategy no longer shows
        base = {r["id"]: r for r in ret if r["corpus"] == c and r["strategy"] == "S0"}
        lost = kept = 0
        for r in rows:
            b = base.get(r["id"])
            if not b or CASES[r["id"]]["category"] == "H":
                continue
            now = {f["point_id"] for f in r["films"]}
            for f in b["films"]:
                fl = flags(r["id"], c, f)
                if fl and fl["valid"]:
                    kept += 1 if f["point_id"] in now else 0
                    lost += 0 if f["point_id"] in now else 1
        m["valid_s0_films_dropped"] = {"dropped": lost, "of": lost + kept}
        metrics[sys_name(c, s)] = m

    # ---------------- answers
    ans_metrics = {}
    for (c, s) in sorted({(k[1], k[2]) for k in answers}):
        recs = [(k, a) for k, a in answers.items() if k[1] == c and k[2] == s and CASES[k[0]]["category"] != "H"]
        viol = tot = lists = 0
        for (q, _, _), a in recs:
            r = by_key[(q, c, s)]
            by = {f["point_id"]: f for f in r["films"]}
            fl = [flags(q, c, by[p]) for p in a["recommended_point_ids"] if p in by]
            fl = [x for x in fl if x]
            tot += len(fl)
            viol += sum(x["viol"] for x in fl)
            lists += 1 if any(x["viol"] for x in fl) else 0
        ans_metrics[sys_name(c, s)] = {"answers": len(recs), "recommended_films": tot, "recommended_violations": viol,
                                       "answers_with_a_violation": lists}

    # ---------------- pairwise
    pw = {}
    for p in pair:
        key = " vs ".join(sys_name(*x.split("/")) for x in p["pair"])
        d = pw.setdefault(key, {"results": [], "by_cat": defaultdict(lambda: defaultdict(int)), "scores": defaultdict(list)})
        a, b = p["pair"]
        w = p["winner"]
        res = "tie" if w == "tie" else ("first" if w == a else "second")
        d["results"].append((p["id"], res))
        d["by_cat"][CASES[p["id"]]["category"]][res] += 1
        for sysk, sc in p["scores"].items():
            for k2, v in sc.items():
                d["scores"][(sysk, k2)].append(v)
    pw_out = {}
    for key, d in pw.items():
        first, second = key.split(" vs ")
        w = sum(1 for _, r in d["results"] if r == "first")
        l = sum(1 for _, r in d["results"] if r == "second")
        t = sum(1 for _, r in d["results"] if r == "tie")
        pw_out[key] = {"first": first, "second": second, "first_wins": w, "second_wins": l, "ties": t, "sign_test_p": round(sign_p(w, l), 4),
                       "by_category": {c: dict(v) for c, v in sorted(d["by_cat"].items())},
                       "mean_scores": {f"{sys_name(*k[0].split('/'))}.{k[1]}": round(mean(v), 2) for k, v in d["scores"].items()}}

    summary = {"retrieval": metrics, "answers": ans_metrics, "pairwise": pw_out}
    (RES / (PREFIX + "summary.json")).write_text(json.dumps(summary, indent=1, ensure_ascii=False))

    # ---------------- markdown
    pct = lambda x: "-" if x is None else f"{100 * x:.0f}%"
    L = ["# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`)", "",
         "Metriche calcolate sulle liste di 5 film. *Violazione* = il film mostra un tratto da evitare, è un titolo/franchise escluso (giudice cieco O controllo "
         "deterministico della batteria). *Pertinente* = ha il genere e le caratteristiche volute. *Valido* = pertinente e senza violazioni. Le domande H "
         "(contraddittorie) sono escluse dalle percentuali e valutate nella parte sulle risposte.", "",
         "## 1. Strategie di recupero (stesso algoritmo su entrambi i corpus dove possibile)", "",
         "| Sistema | Violazioni | di cui titolo/franchise | di cui tratti | Pertinenti | Validi | Genere ok | Liste con violazione | Validi di S0 persi | s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in metrics.items():
        d = m["valid_s0_films_dropped"]
        L.append(f"| {name} | {pct(m['violation'])} | {m['title_or_franchise_violations']} | {m['trait_violations']} | {pct(m['pertinent'])} | {pct(m['valid'])} | "
                 f"{pct(m['genre_kept'])} | {m['lists_with_violation']}/{m['lists']} | {d['dropped']}/{d['of']} | {m['seconds_mean']} |")
    L += ["", "## 2. Per categoria (violazioni / validi)", "", "| Sistema | " + " | ".join(f"{c}" for c in sorted(CATS)) + " |", "|---|" + "---|" * len(CATS)]
    for name, m in metrics.items():
        L.append(f"| {name} | " + " | ".join(f"{pct(m['by_category'].get(c, {}).get('violation'))} / {pct(m['by_category'].get(c, {}).get('valid'))}" for c in sorted(CATS)) + " |")
    L += ["", "Categorie: " + "; ".join(f"**{k}** {v}" for k, v in CATS.items()), "",
          "## 3. Esclusioni espresse in linguaggio naturale (A, C, D, F) e come titoli/franchise (B, E)", "",
          "| Sistema | Violazioni NL | Validi NL | Violazioni titoli | Validi titoli |", "|---|---|---|---|---|"]
    for name, m in metrics.items():
        L.append(f"| {name} | {pct(m['nl_exclusions']['violation'])} | {pct(m['nl_exclusions']['valid'])} | {pct(m['title_exclusions']['violation'])} | {pct(m['title_exclusions']['valid'])} |")
    L += ["", "## 4. Copertura dei film di riferimento nell'indice", ""]
    for name, m in metrics.items():
        if m["reference_coverage"] and name.endswith("S0"):
            L.append(f"- {name}: {m['reference_coverage']['in_index']}/{m['reference_coverage']['refs']} riferimenti presenti nell'indice ({pct(m['reference_coverage']['share'])})")
    L += ["", "## 5. Risposte finali: film consigliati che violano i vincoli", "", "| Configurazione | Risposte | Film consigliati | Violazioni | Risposte con violazione |", "|---|---|---|---|---|"]
    for name, m in ans_metrics.items():
        L.append(f"| {name} | {m['answers']} | {m['recommended_films']} | {m['recommended_violations']} | {m['answers_with_a_violation']} |")
    L += ["", "## 6. Confronto A/B cieco delle risposte (ordine casuale; giudice LLM)", "", "| Confronto | Vittorie primo | Vittorie secondo | Pareggi | p (segno) |", "|---|---|---|---|---|"]
    for key, d in pw_out.items():
        L.append(f"| {key} | {d['first_wins']} | {d['second_wins']} | {d['ties']} | {d['sign_test_p']} |")
    for key, d in pw_out.items():
        L += ["", f"### {key}", "", "| Categoria | primo | secondo | pareggi |", "|---|---|---|---|"]
        for c, v in d["by_category"].items():
            L.append(f"| {c} | {v.get('first', 0)} | {v.get('second', 0)} | {v.get('tie', 0)} |")
        L.append("")
        L.append("Punteggi medi (1-5): " + ", ".join(f"{k} {v}" for k, v in d["mean_scores"].items()))
    (RES / (PREFIX + "REPORT.md")).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:60]))
    return 0
