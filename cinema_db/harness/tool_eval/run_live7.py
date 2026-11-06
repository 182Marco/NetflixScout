"""Phase 7: the repeated live comparison of the application with `cinema_sql` OFF (as before phase 6) and ON (DB-first routing and field reliability).

Same questions and conditions as the phase-6 evaluation (`run_live.py`: its 47 questions, its builder, its measurements) plus the questions that phase 7 is about, each run
`--reps` times per mode because the planner is stochastic. The planner, classifier, tools and answering model are the real ones (OpenAI, TMDb, OMDb, YouTube, Wikipedia,
TVmaze, Wikidata): the command needs `--live`. No embedding: `rag_search` is not allowed, as in phase 6.

  python -m cinema_db.harness.tool_eval.run_live7 plan
  python -m cinema_db.harness.tool_eval.run_live7 run --live [--reps 3] [--only KEY ...]
  python -m cinema_db.harness.tool_eval.run_live7 judge --live          # pairwise blind judge, rep by rep
  python -m cinema_db.harness.tool_eval.run_live7 report                # writes docs/cinema_db/PHASE7_LIVE.json and .md

Measured (tools, real HTTP requests, SQL queries, seconds), mechanically checked (expected words in the answer), judged by a second model, and read by hand: four different
things, kept apart. The phase-6 ON runs are read from `cinema_db/data/phase6_live/runs.jsonl` as a reference column (one run per question, the earlier routing).
"""
from __future__ import annotations

import argparse
import json
import random
import signal
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cinema_db.harness.tool_eval import run_live as P6
from cinema_db.harness.tool_eval.run_live import JUDGE_INSTRUCTIONS, Live, has_facts

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "cinema_db/data/phase7_live"
RUNS = DATA / "runs.jsonl"
JUDGMENTS = DATA / "judgments.jsonl"
OUT_JSON = ROOT / "docs/cinema_db/PHASE7_LIVE.json"
OUT_MD = ROOT / "docs/cinema_db/PHASE7_LIVE.md"
PHASE6_RUNS = ROOT / "cinema_db/data/phase6_live/runs.jsonl"
PHASE6_JUDGMENTS = ROOT / "cinema_db/data/phase6_live/judgments.jsonl"
MODES = ("off", "on")
WORST_IN_PHASE6 = ("B04", "B17", "B20", "E05", "E08", "B11", "B18", "E06", "X05", "X08")  # judged worse with the database on in the phase-6 evaluation

# Questions that phase 7 is about. `must` groups are alternatives; `local_ok` says the answer needs no external step beyond what is named in `note`.
EXTRA7 = (
    Live("P01", ("Chi sono gli attori protagonisti di Inception, chi lo ha diretto e quali premi ha vinto?",), "partial", must=(("DiCaprio",), ("Nolan",), ("Oscar",)), expect_local=True,
         note="the example of the phase: director and awards from the database, the lead actors from TMDb (the database cast has no order)"),
    Live("P02", ("Chi ha recitato in Heat di Michael Mann?",), "local", must=(("Pacino",), ("De Niro",)), expect_local=True, note="the whole cast, no lead order asked: the database alone"),
    Live("P03", ("Quanti Oscar ha vinto Christopher Nolan e per quali film?",), "partial", must=(("Oppenheimer",),), expect_local=True, note="person awards: winners named by the source"),
    Live("P04", ("Quali candidature all'Oscar ha avuto Denis Villeneuve?",), "partial", must=(("Arrival",),), expect_local=True, note="person nominations are only partly recorded"),
    Live("P05", ("Quanti episodi ha la prima stagione di Friends?",), "partial", must=(("24",),), expect_local=None, note="episode counts are uncertain locally: TVmaze verifies"),
    Live("P06", ("Chi ha diretto Oppenheimer e dove posso vederlo in streaming in Italia?",), "partial", must=(("Nolan",),), expect_local=True, note="director local, streaming external"),
    Live("P07", ("Chi ha scritto Pulp Fiction e chi ha composto la colonna sonora?",), "local", must=(("Tarantino",),), expect_local=True),
    Live("P08", ("Dimmi il regista e l'anno di Il Padrino e dammi il punteggio Metascore",), "partial", must=(("Coppola",), ("1972",)), expect_local=True, note="structured facts local, score external"),
)


def questions() -> list[Live]:
    return P6.live_questions() + list(EXTRA7)


def done() -> set[tuple[str, str, int]]:
    if not RUNS.is_file():
        return set()
    return {(r["key"], r["mode"], r["rep"]) for r in map(json.loads, RUNS.read_text(encoding="utf-8").splitlines()) if "error" not in r}


def cmd_run(args: argparse.Namespace) -> None:
    if not args.live:
        raise SystemExit("run needs --live: it calls the OpenAI API and the external services of the tools")
    from dotenv import load_dotenv

    load_dotenv()
    DATA.mkdir(parents=True, exist_ok=True)
    apps = {mode: P6.build(mode) for mode in MODES}
    finished = done()
    todo = [(q, m, rep) for rep in range(1, args.reps + 1) for q in questions() for m in MODES
            if (q.key, m, rep) not in finished and (not args.only or q.key in args.only)]
    print(f"{len(todo)} runs to do", flush=True)

    def _timeout(signum, frame):  # noqa: ARG001
        raise TimeoutError(f"run exceeded {P6.RUN_TIMEOUT_SECONDS} s")

    signal.signal(signal.SIGALRM, _timeout)
    for i, (q, mode, rep) in enumerate(todo, 1):
        record: dict[str, Any] = {"key": q.key, "mode": mode, "rep": rep, "kind": q.kind, "turns_text": list(q.turns), "preferences": q.preferences}
        signal.alarm(P6.RUN_TIMEOUT_SECONDS)
        try:
            record.update(P6.run_one(apps[mode], q))
        except Exception as exc:  # noqa: BLE001 - a failed run is data, not a reason to stop the evaluation
            record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            signal.alarm(0)
        with RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(todo)}] {q.key} r{rep} {mode}: {record.get('tools') or record.get('error')} http={record.get('http')} sql={record.get('sql_queries')} {record.get('wall_s')}s", flush=True)
        time.sleep(P6.PAUSE_SECONDS)


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def latest() -> dict[tuple[str, str, int], dict[str, Any]]:
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    for r in load(RUNS):
        if "error" not in r:
            out[(r["key"], r["mode"], r["rep"])] = r
    return out


def cmd_judge(args: argparse.Namespace) -> None:
    if not args.live:
        raise SystemExit("judge needs --live: it calls the OpenAI API")
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    client = OpenAI()
    runs = latest()
    existing = {(j["key"], j["rep"]) for j in load(JUDGMENTS)}
    for key, rep in sorted({(k, r) for k, _, r in runs}):
        off, on = runs.get((key, "off", rep)), runs.get((key, "on", rep))
        if not off or not on or (key, rep) in existing:
            continue
        swap = random.Random(f"{key}-{rep}-20261106").random() < 0.5
        a, b = (on, off) if swap else (off, on)
        prompt = f"Request: {' / '.join(off['turns_text'])}\n\n=== ANSWER A ===\n{a['answer']}\n\n=== ANSWER B ===\n{b['answer']}"
        try:
            reply = client.responses.create(model=P6.JUDGE_MODEL, instructions=JUDGE_INSTRUCTIONS, input=prompt)
            text = reply.output_text.strip()
            verdict = json.loads(text[text.index("{"): text.rindex("}") + 1])
            winner = str(verdict.get("winner", "tie")).strip().upper()
            real = "tie" if winner not in ("A", "B") else ("on" if (winner == "A") == swap else "off")
            row = {"key": key, "rep": rep, "winner": real, "on_errors": verdict.get("a_errors" if swap else "b_errors", []), "off_errors": verdict.get("b_errors" if swap else "a_errors", []),
                   "reason": verdict.get("reason", "")}
        except Exception as exc:  # noqa: BLE001
            row = {"key": key, "rep": rep, "winner": "error", "reason": f"{type(exc).__name__}: {str(exc)[:200]}", "on_errors": [], "off_errors": []}
        with JUDGMENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(key, rep, row["winner"], row["reason"][:90], flush=True)


# ---- report ---------------------------------------------------------------------------------------------------------------------------
def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def report() -> dict[str, Any]:
    runs, judged = latest(), load(JUDGMENTS)
    p6_on = {r["key"]: r for r in load(PHASE6_RUNS) if r.get("mode") == "on" and "error" not in r}
    p6_judge = {j["key"]: j["winner"] for j in load(PHASE6_JUDGMENTS)}
    rows, per_mode = [], {m: defaultdict(float) for m in MODES}
    for q in questions():
        reps = sorted({rep for (k, m, rep) in runs if k == q.key and m == "on" and (q.key, "off", rep) in runs})
        if not reps:
            continue
        row: dict[str, Any] = {"key": q.key, "question": " / ".join(q.turns), "kind": q.kind, "note": q.note, "reps": len(reps), "expect_local": q.expect_local}
        for m in MODES:
            rs = [runs[(q.key, m, rep)] for rep in reps]
            facts = [has_facts(r["answer"], q.must) for r in rs] if q.must else []
            row[m] = {"http": _mean([r["http"] for r in rs]), "sql": _mean([r["sql_queries"] for r in rs]), "tool_steps": _mean([r["tool_steps"] for r in rs]),
                      "wall_s": _mean([r["wall_s"] for r in rs]), "tools": [" → ".join(t.replace("_search", "") for t in r["tools"]) or "—" for r in rs],
                      "facts": f"{sum(facts)}/{len(facts)}" if facts else "—", "answers": [r["answer"] for r in rs]}
            for key, val in (("http", sum(r["http"] for r in rs)), ("sql", sum(r["sql_queries"] for r in rs)), ("steps", sum(r["tool_steps"] for r in rs)), ("wall", sum(r["wall_s"] for r in rs)),
                             ("runs", len(rs)), ("facts_ok", sum(facts)), ("facts_n", len(facts))):
                per_mode[m][key] += val
        row["cinema_used"] = sum("cinema_sql" in runs[(q.key, "on", rep)]["tools"] for rep in reps)
        votes = Counter(j["winner"] for j in judged if j["key"] == q.key and j["rep"] in reps)
        row["judge"] = dict(votes)
        row["phase6"] = {"judge": p6_judge.get(q.key), "http": p6_on[q.key]["http"], "tools": [t.replace("_search", "") for t in p6_on[q.key]["tools"]]} if q.key in p6_on else None
        rows.append(row)
    totals = {m: {k: round(v, 1) for k, v in per_mode[m].items()} for m in MODES}
    judge_all = Counter(j["winner"] for j in judged)
    worst = [r for r in rows if r["key"] in WORST_IN_PHASE6]
    summary = {"questions": len(rows), "runs_per_mode": int(totals["on"].get("runs", 0)), "totals": totals, "judge": dict(judge_all),
               "judge_worst_ten": dict(Counter(w for r in worst for w, n in r["judge"].items() for _ in range(n))),
               "cinema_used_runs": sum(r["cinema_used"] for r in rows)}
    return {"summary": summary, "rows": rows}


MANUAL_LIVE7: dict[str, str] = {}  # filled in after reading the answers (keys: question)


def markdown(data: dict[str, Any]) -> str:
    s, rows = data["summary"], data["rows"]
    off, on = s["totals"]["off"], s["totals"]["on"]
    n = max(1, int(on.get("runs", 1)))
    L = ["# Valutazione live della Fase 7: DB-first con affidabilità per campo, confronto ripetuto", "",
         "Generata da `python -m cinema_db.harness.tool_eval.run_live7` con il planner, il classificatore, i tool e il modello di risposta reali. Stesse domande e condizioni della fase 6 "
         "(47 domande, `rag_search` escluso) più 8 domande della fase 7; ogni domanda è eseguita più volte per modalità (il planner è stocastico). **Spento** = `cinema_db` disattivato, come prima della fase 6. "
         "**Acceso** = routing DB-first della fase 7. Colonna «Fase 6»: l'esecuzione unica della fase 6 con il routing precedente (riferimento, non ripetuta).", "",
         "Quattro cose separate: **misurato** (tool, richieste HTTP davvero inviate, query SQL, secondi), **controllo meccanico** (parole attese nella risposta), **giudice** (`gpt-5.5` a ciechi, diverso dal modello "
         "che risponde) e **lettura manuale** (la mia). Le richieste interne del controllo del tipo di opera di MovieLens non sono nelle `calls`.", "",
         "## 1. Totali (somma su tutte le esecuzioni, misurati)", "", f"Domande: {s['questions']}; esecuzioni per modalità: {int(on.get('runs', 0))}.", "",
         "| | Spento | Acceso | Differenza |", "|---|---|---|---|",
         f"| Richieste HTTP | {off['http']:.0f} | {on['http']:.0f} | {on['http'] - off['http']:+.0f} ({(on['http'] - off['http']) / max(1, off['http']) * 100:+.0f} %) |",
         f"| Richieste HTTP per esecuzione | {off['http'] / n:.2f} | {on['http'] / n:.2f} | |",
         f"| Passi di tool | {off['steps']:.0f} | {on['steps']:.0f} | {on['steps'] - off['steps']:+.0f} |",
         f"| Query SQL | {off['sql']:.0f} | {on['sql']:.0f} | {on['sql'] - off['sql']:+.0f} |",
         f"| Tempo totale (s) | {off['wall']:.0f} | {on['wall']:.0f} | {on['wall'] - off['wall']:+.0f} ({(on['wall'] - off['wall']) / max(1, off['wall']) * 100:+.0f} %) |",
         f"| Fatti attesi presenti | {off['facts_ok']:.0f}/{off['facts_n']:.0f} | {on['facts_ok']:.0f}/{on['facts_n']:.0f} | |", "",
         f"`cinema_sql` scelto in {s['cinema_used_runs']} esecuzioni accese. Giudice, tutte le coppie: {s['judge']}; sulle 10 domande peggiori della fase 6: {s['judge_worst_ten']}.", "",
         "## 2. Per domanda (media sulle ripetizioni)", "",
         "| Chiave | Domanda | Tool spento | Tool acceso | HTTP s/a | SQL | s s/a | Fatti s/a | Giudice (a/p/s) | Fase 6 | Nota |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        j = r["judge"]
        p6 = r["phase6"]
        L.append(f"| {r['key']} | {r['question'][:80].replace('|', '/')} | {Counter(r['off']['tools']).most_common(1)[0][0]} | {'; '.join(f'{t} ×{c}' for t, c in Counter(r['on']['tools']).most_common(2))} | "
                 f"{r['off']['http']}/{r['on']['http']} | {r['on']['sql']} | {r['off']['wall_s']:.0f}/{r['on']['wall_s']:.0f} | {r['off']['facts']}/{r['on']['facts']} | "
                 f"{j.get('on', 0)}/{j.get('tie', 0)}/{j.get('off', 0)} | {(p6 or {}).get('judge', '—')} | {MANUAL_LIVE7.get(r['key'], r['note']).replace('|', '/')} |")
    return "\n".join(L) + "\n"


def cmd_report(args: argparse.Namespace) -> None:
    data = report()
    OUT_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(markdown(data), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("plan", "run", "judge", "report"))
    ap.add_argument("--live", action="store_true", help="authorise the paid / external calls")
    ap.add_argument("--reps", type=int, default=3, help="repetitions per question and mode")
    ap.add_argument("--only", nargs="*", help="keys to run")
    args = ap.parse_args(argv)
    if args.command == "plan":
        for q in questions():
            print(q.key, q.kind, q.preferences or "", "|", " / ".join(q.turns))
        print(f"{len(questions())} questions x {len(MODES)} modes x {args.reps} reps")
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "judge":
        cmd_judge(args)
    else:
        cmd_report(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
