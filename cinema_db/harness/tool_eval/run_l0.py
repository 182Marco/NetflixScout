"""Phase 8, block L0: the baseline of the current architecture with the new timings (cinema_db ON, nothing optimised).

    python -m cinema_db.harness.tool_eval.run_l0 plan                       # offline, free: the questions, the runs and the token estimate
    python -m cinema_db.harness.tool_eval.run_l0 run --live --label A       # PAID (OpenAI) and external calls: only with the owner's authorisation
    python -m cinema_db.harness.tool_eval.run_l0 report --label A           # offline: where the time went, from the recorded runs

The same file runs on both states. `--label` (A = instrumentation only, B = plus the optimisations) selects the data folder `cinema_db/data/phase8_l0/<label>/`
and the report `docs/cinema_db/PHASE8_L0_<label>.md`; every record carries the git commit, and a folder that holds runs of another commit refuses new ones.

What it records for every turn (all of it from `TurnResult.timings`, measurement only):
planner calls (count, ms and input/output tokens of each), the answer call (ms, time to first text, tokens), every tool (ms, local SQL ms, HTTP requests), the
classifier and compaction times, and the total latency. The classifier tokens are not recorded (gpt-4o-mini, a few hundred tokens per turn).

The 12 questions are chosen BEFORE any result of this block, by the interventions they exercise, from the 55 development questions (the final sample is another set):
B13 (several OMDb titles: step 4b), E05 and X07 (routing of cinema_sql / TMDb), P01, P06, B15, B18 (several steps), E06, E08, P03 (awards and fallback steps), B01, B06 (local only: the
floor). `run` writes ONLY to `cinema_db/data/phase8_l0/<label>/` (the phase-7 data are never touched) and resumes: a (question, rep) already done is not repeated.
The database is enabled for this evaluation only through the in-process override used by `run_live.build('on')`; `CONFIG["cinema_db"]["enabled"]` stays False.
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from cinema_db.harness.tool_eval import run_live as P6
from cinema_db.harness.tool_eval import run_live7 as P7

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "cinema_db/data/phase8_l0"
DATA = BASE  # becomes BASE/<label> in `use_label`: each state (A, B, ...) has its own folder and its own report, never shared
RUNS = DATA / "runs.jsonl"
OUT_MD = ROOT / "docs/cinema_db/PHASE8_L0.md"
MODE = "on"
L0_KEYS = ("B01", "B06", "B13", "B15", "B18", "E05", "E06", "E08", "P01", "P06", "X07", "P03")
PLANNER_PROMPT_TOKENS = 14_700  # measured size of the planner prompt (cinema_db on), resent at every planner call
ANSWER_TOKENS_IN = 3_000        # estimate; the real value is recorded from now on


def use_label(label: str) -> None:
    """Point the harness at the folder of one state of the code. The label is a short name such as A or B (letters, digits, - and _)."""
    global DATA, RUNS, OUT_MD
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", label or ""):
        raise SystemExit("--label is required: a short name for the state of the code being measured (for example A or B)")
    DATA = BASE / label
    RUNS = DATA / "runs.jsonl"
    OUT_MD = ROOT / f"docs/cinema_db/PHASE8_L0_{label}.md"


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - not a repository: the run is recorded without a commit
        return "unknown"


def selected() -> list[P6.Live]:
    by_key = {q.key: q for q in P7.questions()}
    missing = [k for k in L0_KEYS if k not in by_key]
    if missing:
        raise SystemExit(f"unknown development questions: {missing}")
    return [by_key[k] for k in L0_KEYS]


def load() -> list[dict[str, Any]]:
    return [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines()] if RUNS.is_file() else []


def done() -> set[tuple[str, int]]:
    return {(r["key"], r["rep"]) for r in load() if "error" not in r}


def estimate(reps: int) -> dict[str, Any]:
    """Token estimate from the phase-7 ON runs of the same questions (planner calls ~ tool steps + 1 when the turn has more than one step)."""
    history = ROOT / "cinema_db/data/phase7_live/runs.jsonl"  # git-ignored data: without it the estimate uses a default of 2 steps
    runs = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()] if history.is_file() else []
    steps = [r["tool_steps"] for r in runs if r["mode"] == MODE and r["key"] in L0_KEYS and "error" not in r]
    mean_steps = statistics.mean(steps) if steps else 2.0
    planner_calls = mean_steps + (1 if mean_steps > 1.2 else 0)
    per_run_in = planner_calls * PLANNER_PROMPT_TOKENS + ANSWER_TOKENS_IN
    n = len(L0_KEYS) * reps
    return {"runs": n, "mean_tool_steps": round(mean_steps, 2), "tokens_in_per_run": round(per_run_in), "tokens_in_total": round(per_run_in * n), "tokens_out_total": round(n * 2_000)}


def cmd_plan(args: argparse.Namespace) -> None:
    e = estimate(args.reps)
    print(f"state label: {args.label or '(none yet: --label is required by run and report)'}; commit {git_head()}")
    print(f"{len(L0_KEYS)} questions x {args.reps} reps = {e['runs']} runs, mode {MODE} (database on, in-process override), data in {DATA}")
    for q in selected():
        print(f"  {q.key}: {q.turns[0]}")
    print(f"estimate: ~{e['tokens_in_per_run']:,} input tokens per run ({e['mean_tool_steps']} tool steps on average) -> ~{e['tokens_in_total'] / 1e6:.2f}M in, ~{e['tokens_out_total'] / 1e6:.2f}M out. Nothing was called.")
    print(f"already done: {len(done())} (question, rep) pairs")


def cmd_run(args: argparse.Namespace) -> None:
    if not args.live:
        raise SystemExit("run needs --live: it calls the OpenAI API and the external services of the tools (owner's authorisation required)")
    from dotenv import load_dotenv

    load_dotenv()
    DATA.mkdir(parents=True, exist_ok=True)
    head = git_head()
    earlier = {r.get("git_head") for r in load()}
    if earlier and earlier != {head}:
        raise SystemExit(f"{RUNS} already holds runs of commit {sorted(map(str, earlier))}, this tree is {head}: use another --label (data of two states are never mixed)")
    app = P6.build(MODE)
    finished = done()
    todo = [(q, rep) for rep in range(1, args.reps + 1) for q in selected() if (q.key, rep) not in finished]
    print(f"{len(todo)} runs to do", flush=True)

    def _timeout(signum, frame):  # noqa: ARG001
        raise TimeoutError(f"run exceeded {P6.RUN_TIMEOUT_SECONDS} s")

    signal.signal(signal.SIGALRM, _timeout)
    for i, (q, rep) in enumerate(todo, 1):
        record: dict[str, Any] = {"key": q.key, "mode": MODE, "rep": rep, "turns_text": list(q.turns), "git_head": head, "label": args.label}
        signal.alarm(P6.RUN_TIMEOUT_SECONDS)
        try:
            record.update(P6.run_one(app, q))
        except Exception as exc:  # noqa: BLE001 - a failed run is data
            record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            signal.alarm(0)
        with RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(todo)}] {q.key} r{rep}: {record.get('tools') or record.get('error')} {record.get('wall_s')}s", flush=True)
        time.sleep(P6.PAUSE_SECONDS)


def breakdown(record: dict[str, Any]) -> dict[str, float]:
    """Sums over the turns of a run. Every figure is a measure; `other_ms` is what none of them explains (classifier excluded: it is its own figure)."""
    out: dict[str, float] = {k: 0.0 for k in ("wall_s", "classifier_ms", "planner_calls", "planner_ms", "planner_in", "planner_out", "tool_ms", "sql_ms", "http", "answer_ms",
                                              "answer_first_ms", "answer_in", "answer_out")}
    for turn in record.get("turns", []):
        t = turn.get("timings") or {}
        out["wall_s"] += turn.get("wall_s", 0.0)
        out["classifier_ms"] += t.get("classifier_ms") or 0
        out["planner_calls"] += t.get("planner_calls") or 0
        out["planner_ms"] += t.get("planner_ms") or 0
        for call in t.get("planner") or []:
            out["planner_in"] += call.get("input_tokens", 0)
            out["planner_out"] += call.get("output_tokens", 0)
        out["tool_ms"] += t.get("tool_ms") or 0
        out["sql_ms"] += t.get("sql_ms") or 0
        out["http"] += sum(x.get("http_calls", 0) for x in t.get("tools") or [])
        out["answer_ms"] += t.get("answer_ms") or 0
        out["answer_first_ms"] += t.get("answer_first_delta_ms") or 0
        out["answer_in"] += (t.get("answer_tokens") or {}).get("input_tokens", 0)
        out["answer_out"] += (t.get("answer_tokens") or {}).get("output_tokens", 0)
    return out


def report_text() -> str:
    runs = [r for r in load() if "error" not in r]
    if not runs:
        return "# Fase 8 — L0\n\nNessuna esecuzione registrata.\n"
    lines = ["# Fase 8 — L0: baseline con i nuovi tempi (database acceso, nessuna ottimizzazione)", "",
             f"{len(runs)} esecuzioni valide ({len(load()) - len(runs)} con errore). Tutte le cifre sono misure (`TurnResult.timings`); i token del classificatore non sono registrati.", "",
             "| Domanda | Rip. | Tool | Totale s | Classif. s | Planner (chiamate / s) | Token planner in/out | Tool s | di cui SQL ms | HTTP | Risposta s (1° testo s) | Token risposta in/out |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    sums: dict[str, float] = {}
    for r in sorted(runs, key=lambda x: (x["key"], x["rep"])):
        b = breakdown(r)
        for k, v in b.items():
            sums[k] = sums.get(k, 0.0) + v
        lines.append(f"| {r['key']} | {r['rep']} | {'>'.join(r['tools'])} | {b['wall_s']:.1f} | {b['classifier_ms'] / 1000:.1f} | {b['planner_calls']:.0f} / {b['planner_ms'] / 1000:.1f} | "
                     f"{b['planner_in']:.0f}/{b['planner_out']:.0f} | {b['tool_ms'] / 1000:.1f} | {b['sql_ms']:.1f} | {b['http']:.0f} | {b['answer_ms'] / 1000:.1f} ({b['answer_first_ms'] / 1000:.1f}) | "
                     f"{b['answer_in']:.0f}/{b['answer_out']:.0f} |")
    total = sums["wall_s"] or 1.0
    shares = {"classificatore": sums["classifier_ms"] / 1000, "planner": sums["planner_ms"] / 1000, "tool": sums["tool_ms"] / 1000, "risposta": sums["answer_ms"] / 1000}
    lines += ["", "## Dove va il tempo (somma di tutte le esecuzioni)", "", "| Parte | s | % del totale |", "|---|---|---|"]
    for name, seconds in shares.items():
        lines.append(f"| {name} | {seconds:.0f} | {100 * seconds / total:.0f} % |")
    lines += [f"| di cui SQL locale (dentro i tool) | {sums['sql_ms'] / 1000:.2f} | {100 * sums['sql_ms'] / 1000 / total:.1f} % |",
              f"| totale misurato | {total:.0f} | 100 % |", ""]
    planner = [c for r in runs for t in r["turns"] for c in (t.get("timings") or {}).get("planner", []) if c.get("ms") is not None and not c.get("failed")]
    for kind in ("first", "next"):
        ms = [c["ms"] for c in planner if c["kind"] == kind]
        if ms:
            lines.append(f"- Chiamata di planner `{kind}`: n={len(ms)}, mediana {statistics.median(ms) / 1000:.1f} s, min {min(ms) / 1000:.1f} s, max {max(ms) / 1000:.1f} s. **Questo è il peso di una chiamata che l'intervento 3 risparmierebbe.**")
    return "\n".join(lines) + "\n"


def cmd_report(_args: argparse.Namespace) -> None:
    text = report_text()
    OUT_MD.write_text(text, encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("plan", "run", "report"))
    ap.add_argument("--live", action="store_true", help="authorise the paid / external calls")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--label", default=None, help="name of the state of the code (A = instrumentation only, B = plus optimisations): its own data folder")
    args = ap.parse_args(argv)
    if args.command != "plan" or args.label:
        use_label(args.label)
    {"plan": cmd_plan, "run": cmd_run, "report": cmd_report}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
