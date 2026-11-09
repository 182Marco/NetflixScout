"""Series battery (36 questions, `battery.json`) through the real retriever: parser (LLM) + embedding + Qdrant, then a blind LLM judge.

    python -m pipelines.wikipedia_series.eval.run_battery run      # PAID (small): parser + embedding per question -> data/s8/battery_run.jsonl
    python -m pipelines.wikipedia_series.eval.run_battery judge    # PAID (small): judge gpt-5.5 over each question's top-5 -> data/s8/battery_judge.jsonl
    python -m pipelines.wikipedia_series.eval.run_battery report   # offline: aggregates -> data/s8/battery_summary.json

The judge sees the question, what must be kept / avoided, and each result as label + level + year + the start of its plot; it does not know the
retriever. valid = score 2 ("yes"); partial = 1; the film-collection baseline only measures how a film index answers a series question."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel
from qdrant_client import QdrantClient

from tool.rag.series import retrieval as R  # the retriever the agent runs: evaluated, not copied
from ..common import DATA_DIR, load_env

HERE = Path(__file__).parent
OUT = DATA_DIR / "s8"
RUN, JUDGE, SUMMARY = OUT / "battery_run.jsonl", OUT / "battery_judge.jsonl", OUT / "battery_summary.json"
CASES = json.loads((HERE / "battery.json").read_text())["cases"]
K = 5
JUDGE_MODEL = "gpt-5.5"      # not the model that parses


class Verdict(BaseModel):
    i: int
    score: int           # 0 no, 1 partly, 2 yes
    violates_avoid: bool
    level_ok: bool       # it is the kind of thing asked for (series / season / episode / TV movie)


class Verdicts(BaseModel):
    items: list[Verdict]


def run(reorder: bool = False) -> int:
    load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    RUN_PATH, run_signals = (OUT / "battery_run_reorder.jsonl", {json.loads(l)["id"]: json.loads(l)["signals"] for l in RUN.open()}) if reorder else (RUN, {})
    rr = R.make_reorder() if reorder else None
    index, embed, parse = R.SeriesIndex(), R.make_embed(), R.make_parse()
    films = QdrantClient(url=R.URL, timeout=60)
    with RUN_PATH.open("w") as f:
        for c in CASES:
            try:
                sg = R.SeriesSignals(**run_signals[c["id"]]) if reorder else parse(c["question"])    # the A/B reuses the SAME signals
                err = None
            except Exception as e:  # noqa: BLE001
                sg, err = R.fallback(c["question"]), type(e).__name__
            out = R.search(index, embed, sg, k=K, reorder=rr, request=c["question"])
            fv = films.query_points("wikipedia_films_it_v3", query=embed([sg.positive_it])[0].tolist(), limit=K, with_payload=["title", "work_format"]).points
            row = {"id": c["id"], "category": c["category"], "question": c["question"], "signals": sg.model_dump(), "parser_error": err, "notes": out.notes,
                   "results": [{"label": i.label(), "level": i.entity_type, "year": i.year, "eligible": i.default_search_eligible, "subtype": i.subtype,
                                "plot": i.text[:600], "url": i.url, "score": round(i.score, 4)} for i in out.items],
                   "film_baseline": [{"title": p.payload.get("title"), "work_format": p.payload.get("work_format")} for p in fv]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
            print(c["id"], c["category"], len(out.items), out.notes)
    return 0


def judge(variant: str = "") -> int:
    load_env()
    RUN_IN, JUDGE_OUT = (OUT / f"battery_run_{variant}.jsonl", OUT / f"battery_judge_{variant}.jsonl") if variant else (RUN, JUDGE)
    client = R._openai(max_retries=3, timeout=120)
    cases = {c["id"]: c for c in CASES}
    with JUDGE_OUT.open("w") as f:
        for line in RUN_IN.open():
            r = json.loads(line)
            if not r["results"]:
                f.write(json.dumps({"id": r["id"], "verdicts": []}) + "\n"); continue
            c = cases[r["id"]]
            body = "\n".join(f"[{i}] ({x['level']}, {x['year']}) {x['label']}\n    {x['plot']}" for i, x in enumerate(r["results"]))
            prompt = (f"Richiesta dell'utente: {c['question']}\nCosa deve mantenere: {c.get('must_keep') or '-'}\nCosa deve evitare: {c.get('must_avoid') or '-'}\n"
                      f"Tipo cercato: {c['level']} (series=intera serie, season=stagione, episode=puntata, tv_movie=film TV)\n\nRisultati:\n{body}\n\n"
                      "Per ogni risultato: score 2 se soddisfa la richiesta, 1 se solo in parte, 0 se no (usa anche la tua conoscenza dell'opera); "
                      "violates_avoid true se mostra ciò che l'utente voleva evitare o è un titolo escluso; level_ok true se è del tipo cercato.")
            resp = client.responses.parse(model=JUDGE_MODEL, instructions="You are a strict, blind judge of TV-series search results.", input=prompt, text_format=Verdicts)
            f.write(json.dumps({"id": r["id"], "verdicts": [v.model_dump() for v in resp.output_parsed.items]}) + "\n"); f.flush()
    return 0


def report() -> int:
    runs = {json.loads(l)["id"]: json.loads(l) for l in RUN.open()}
    js = {json.loads(l)["id"]: json.loads(l)["verdicts"] for l in JUDGE.open()}
    cases = {c["id"]: c for c in CASES}
    cat = defaultdict(lambda: defaultdict(float))
    rows = []
    for i, r in runs.items():
        v, c = js.get(i, []), cases[i]
        n = len(r["results"])
        row = {"id": i, "category": r["category"], "n": n, "valid": sum(x["score"] == 2 for x in v), "partial": sum(x["score"] == 1 for x in v),
               "violations": sum(x["violates_avoid"] for x in v), "level_ok": sum(x["level_ok"] for x in v),
               "ineligible_returned": sum(not x["eligible"] for x in r["results"] if x["level"] in ("series", "tv_movie")),
               "film_baseline_series_like": sum(1 for b in r["film_baseline"] if b["work_format"] in ("series", "tv_related")),
               "empty_expected": bool(c.get("expect_empty")), "empty": n == 0, "contradiction_flagged": bool(r["signals"]["contradictory"]),
               "contradiction_expected": bool(c.get("expect_contradiction")), "notes": r["notes"]}
        rows.append(row)
        g = cat[r["category"]]
        g["questions"] += 1; g["items"] += n; g["valid"] += row["valid"]; g["partial"] += row["partial"]
        g["violations"] += row["violations"]; g["level_ok"] += row["level_ok"]
    scored = [x for x in rows if not x["empty_expected"] and x["n"]]
    tot = {k: sum(x[k] for x in scored) for k in ("n", "valid", "partial", "violations", "level_ok", "ineligible_returned")}
    summary = {"questions": len(rows), "scored_questions": len(scored), "items": tot["n"],
               "valid_share": round(tot["valid"] / tot["n"], 3), "valid_or_partial_share": round((tot["valid"] + tot["partial"]) / tot["n"], 3),
               "violation_share": round(tot["violations"] / tot["n"], 3), "level_ok_share": round(tot["level_ok"] / tot["n"], 3),
               "ineligible_pages_returned": tot["ineligible_returned"],
               "questions_with_no_valid_in_top5": [x["id"] for x in scored if x["valid"] == 0],
               "nonexistent_series_returns_empty": all(x["empty"] for x in rows if x["empty_expected"]),
               "contradiction_flagged_as_expected": all(x["contradiction_flagged"] for x in rows if x["contradiction_expected"]),
               "film_index_series_like_items_in_top5": sum(x["film_baseline_series_like"] for x in rows), "film_index_items": len(rows) * K,
               "by_category": {k: {"questions": int(g["questions"]), "valid_share": round(g["valid"] / max(g["items"], 1), 3),
                                   "violations": int(g["violations"])} for k, g in sorted(cat.items())}, "rows": rows}
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1, ensure_ascii=False))
    return 0


def compare() -> int:
    """Paired comparison base vs reorder over the same questions (same signals, same judge)."""
    def load(run_p, judge_p):
        r = {json.loads(l)["id"]: json.loads(l) for l in run_p.open()}
        j = {json.loads(l)["id"]: json.loads(l)["verdicts"] for l in judge_p.open()}
        return r, j
    cases = {c["id"]: c for c in CASES}
    (_, jb), (_, jr) = load(RUN, JUDGE), load(OUT / "battery_run_reorder.jsonl", OUT / "battery_judge_reorder.jsonl")
    ids = [i for i in jb if jb[i] and jr.get(i) and not cases[i].get("expect_empty")]
    agg = lambda j, f: sum(f(x) for i in ids for x in j[i]) / sum(len(j[i]) for i in ids)
    wins = sum(1 for i in ids if sum(x["score"] for x in jr[i]) > sum(x["score"] for x in jb[i]))
    losses = sum(1 for i in ids if sum(x["score"] for x in jr[i]) < sum(x["score"] for x in jb[i]))
    res = {"questions": len(ids), "base": {"valid": round(agg(jb, lambda x: x["score"] == 2), 3), "valid_or_partial": round(agg(jb, lambda x: x["score"] >= 1), 3), "violations": round(agg(jb, lambda x: x["violates_avoid"]), 3)},
           "reorder": {"valid": round(agg(jr, lambda x: x["score"] == 2), 3), "valid_or_partial": round(agg(jr, lambda x: x["score"] >= 1), 3), "violations": round(agg(jr, lambda x: x["violates_avoid"]), 3)},
           "questions_better": wins, "questions_worse": losses, "questions_equal": len(ids) - wins - losses}
    (OUT / "battery_reorder_compare.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = {"run": run, "judge": judge, "report": report, "compare": compare,
           "run-reorder": lambda: run(True), "judge-reorder": lambda: judge("reorder")}.get(a[0] if a else "")
    sys.exit(cmd() if cmd else (print(__doc__) or 2))
