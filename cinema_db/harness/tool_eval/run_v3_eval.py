"""Evaluation of the REAL planner on `cinema_sql` with the runtime file (v2) and the reconciled candidate (v3). Prepared in phase 9-G; NOT run.

    python -m cinema_db.harness.tool_eval.run_v3_eval plan                          # offline, free: cases, expectations, call counts, token estimate
    python -m cinema_db.harness.tool_eval.run_v3_eval routing --live                # PAID, stage 1: the first planner decision only (no tool, no answer)
    python -m cinema_db.harness.tool_eval.run_v3_eval full --live [--only V03 V07]  # PAID + external services, stage 2: the whole turn (planner, tools, answer)
    python -m cinema_db.harness.tool_eval.run_v3_eval report                        # offline: the comparison v2 / v3 from the recorded runs

Both states run in-process through overrides (`CONFIG["cinema_db"]["enabled"]` stays False, nothing is activated): `v2` = `cinema_db/data/cinema.sqlite3`, `v3` = the candidate
`cinema_db/data/cinema.v3.candidate2.sqlite3`. Everything else is identical, the film index is excluded (no embedding), the database files are opened read-only. Data are written
ONLY to `cinema_db/data/v3_eval/` (git-ignored); a (case, state, stage, rep) already recorded is not repeated; each record carries the git commit and the database digest.
Authorisation: `--live` AND the environment variable `CINEMA_V3_EVAL_AUTHORIZED=yes` (set by the owner for the session, never in `.env`, code or tests).

What is judged (all deterministic from the record, no LLM judge): the first tool and its operation against the expectation, the tools of the turn against the allowed set and the
maximum of external steps, the declared reliability level in the answer (words), and the facts that must appear. Accuracy and completeness of the prose are read by a person on the
`full` records (the report lists the answers).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "cinema_db/data/v3_eval"
RUNS = DATA / "runs.jsonl"
OUT_MD = ROOT / "docs/cinema_db/PHASE9_G_EVAL.md"
PATHS = {"v2": "cinema_db/data/cinema.sqlite3", "v3": "cinema_db/data/cinema.v3.candidate2.sqlite3"}
EXTERNAL = {"tmdb_search", "omdb_search", "wikipedia_search", "wikidata_search", "tvmaze_search", "youtube_search", "movie_db_search"}
RUN_TIMEOUT_SECONDS = 300
PAUSE_SECONDS = 2.0
PLANNER_PROMPT_TOKENS = {"v2": 14_700, "v3": 15_100}  # measured for v2 (phase 8); v3 adds the ~0.4k-token addendum. Estimates, replaced by the recorded usage.
ANSWER_TOKENS_IN = 3_000


@dataclass(frozen=True)
class Case:
    key: str
    scenario: str
    turns: tuple[str, ...]
    first: tuple[str, ...]                    # accepted first tools
    ops: tuple[str, ...] = ()                 # accepted cinema_sql operations of the first step, when the first tool is cinema_sql (v3 expectation)
    v2_ops: tuple[str, ...] = ()              # the same on the v2 file (ratings do not exist there); empty = same as `ops`
    max_external: int = 0                     # external tools allowed after/besides cinema_sql in the whole turn
    forbidden: tuple[str, ...] = ()
    preferences: dict[str, Any] | None = None
    must: tuple[tuple[str, ...], ...] = ()    # groups of alternatives, at least one word each in the answer (case-insensitive)
    level_words: tuple[str, ...] = ()         # v3 only: the answer must say how sure the identification is
    note: str = ""


CASES: tuple[Case, ...] = (
    Case("V01", "verified film", ("Chi ha diretto Dune del 2021 e chi ha scritto la sceneggiatura?",), ("cinema_sql",), ("crew", "work_card", "find_work"), must=(("Villeneuve",),), note="verified: no external step"),
    Case("V02", "uncertain identity", ("Dimmi regia e anno di uscita di «Mute Witnesses»",), ("cinema_sql", "tmdb_search"), ("find_work", "work_card"), max_external=1, level_words=("incert", "uncertain", "buona probabilità", "probabil", "non verific"),
         note="one of the 21 weak MovieLens titles; the real expectation is to say the level, then at most one confirmation"),
    Case("V03", "by director", ("Quali film ha diretto Christopher Nolan?",), ("cinema_sql",), ("filmography",), must=(("Inception",), ("Memento", "Dunkirk")), note="local filmography, no external step"),
    Case("V04", "main cast", ("Chi sono gli attori principali di Heat - La sfida?",), ("cinema_sql", "tmdb_search"), ("cast",), v2_ops=("cast",), max_external=1, must=(("Pacino",), ("De Niro",)),
         note="v3: billing_order answers; v2: the rule sends the lead cast to tmdb_search (facet credits)"),
    Case("V05", "audience ratings of a title", ("Che voto ha Il padrino e quanti voti ha?",), ("cinema_sql",), ("ratings",), v2_ops=(), max_external=1, forbidden=("movie_db_search",),
         must=(("voti", "votes", "/10", "su 10"),), note="v3: ratings first; v2: no ratings operation, tmdb_search or movie_db_search are the legitimate routes"),
    Case("V06", "Metascore and Rotten Tomatoes", ("Che Metascore e che percentuale su Rotten Tomatoes ha Parasite?",), ("omdb_search",), forbidden=("cinema_sql",), must=(("Rotten", "%"),),
         note="critics' scores stay with OMDb in both states; ratings must NOT be chosen"),
    Case("V07", "ranking by genre", ("Quali sono i film horror meglio votati dagli utenti?",), ("movie_db_search",), forbidden=("cinema_sql",), note="MovieLens ranking by genre, not ratings without a title"),
    Case("V08", "information absent from the database", ("Quali premi ha vinto Ladri di biciclette?",), ("cinema_sql",), ("awards",), max_external=1, note="empty or partial awards: ONE wikipedia_search at most"),
    Case("V09", "namesake titles", ("Parlami di Crash",), ("tmdb_search", "cinema_sql", "wikidata_search"), ("find_work",), max_external=1, note="the generic request stays on rule 1; if cinema_sql is chosen the ambiguity goes to the user"),
    Case("V10", "person with a canonical identity", ("Quali film ha fatto Brad Pitt? Sono tanti?",), ("cinema_sql",), ("filmography",), note="a person merged into a canonical entity appears once; the count is partial"),
    Case("V11", "dynamic data", ("Quali film con Timothée Chalamet escono quest'anno?",), ("tmdb_search",), forbidden=("cinema_sql",), note="releases are dynamic: never the static archive"),
    Case("V12", "provenance on request", ("Da dove viene il dato sull'anno di uscita di Alien e ci sono ID alternativi?",), ("cinema_sql",), ("provenance",), v2_ops=(), max_external=1, note="v3 only; on v2 the operation does not exist"),
    Case("V13", "ratings with the user-ratings preference", ("Com'è valutato Interstellar dal pubblico?",), ("cinema_sql",), ("ratings",), v2_ops=(), max_external=1, preferences={"preferred_sources": "user ratings"},
         must=(("pubblico", "spettator", "voti"),), note="the preference must route a single title's ratings to the archive and keep Metascore with OMDb"),
    Case("V14", "reviews preference with critics' scores", ("Cosa ne dice la critica di Oppenheimer?",), ("omdb_search",), forbidden=("cinema_sql",), preferences={"preferred_sources": "reviews"}, note="the reviews preference: OMDb first, never the audience ratings"),
)


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def digest(path: str) -> str:
    conn = sqlite3.connect(f"{(ROOT / path).resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        row = conn.execute("SELECT value FROM build_info WHERE key='content_sha256'").fetchone()
    finally:
        conn.close()
    return (row[0] if row else hashlib.sha256(path.encode()).hexdigest())[:16]


def build(state: str):
    from app import build_app, ensure_cinema_db_ready

    overrides: dict[str, Any] = {"orchestrator": {"fallback_tool": "tmdb_search", "allowed_tools": ["movie_db_search", "tmdb_search", "youtube_search", "wikipedia_search", "omdb_search", "tvmaze_search", "wikidata_search", "cinema_sql"]},
                                 "cinema_db": {"enabled": True, "db_path": PATHS[state]}}
    app = build_app(overrides)  # not build_ready_app: it needs the Qdrant server for the film index, which this evaluation never uses
    ensure_cinema_db_ready(app["config"]["cinema_db"])
    assert "cinema_sql" in app["orchestrator"].tools and "rag_search" not in app["orchestrator"]._allowed_tool_names(), "cinema_sql must be on and no embedding may be made"
    assert (app["orchestrator"].tools["cinema_sql"].schema == 3) == (state == "v3")
    return app


def load() -> list[dict[str, Any]]:
    return [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines()] if RUNS.is_file() else []


def done() -> set[tuple[str, str, str, int]]:
    return {(r["key"], r["state"], r["stage"], r["rep"]) for r in load() if "error" not in r}


def expected_ops(case: Case, state: str) -> tuple[str, ...]:
    return case.ops if state == "v3" else (case.v2_ops or case.ops)


def judge_routing(case: Case, state: str, tool: str | None, operation: str | None) -> dict[str, Any]:
    ok_tool = tool in case.first
    ok_op = True
    if tool == "cinema_sql" and expected_ops(case, state):
        ok_op = operation in expected_ops(case, state)
    elif state == "v2" and case.v2_ops == () and case.ops and case.key in {"V05", "V12", "V13"}:
        ok_tool = tool is not None and tool not in case.forbidden  # v2 has no such operation: any non-forbidden route is acceptable, the report lists it
    return {"first_ok": bool(ok_tool and ok_op and tool not in case.forbidden)}


def judge_full(case: Case, state: str, record: dict[str, Any]) -> dict[str, Any]:
    tools = record.get("tools") or []
    externals = [t for t in tools if t in EXTERNAL or t in {"omdb_search"}]
    answer = (record.get("answer") or "").casefold()
    must_ok = all(any(w.casefold() in answer for w in group) for group in case.must)
    level_ok = True if state != "v3" or not case.level_words else any(w.casefold() in answer for w in case.level_words)
    return {"external_steps": len(externals), "within_external_budget": len(externals) <= case.max_external, "forbidden_used": [t for t in tools if t in case.forbidden],
            "must_ok": must_ok, "level_ok": level_ok}


def estimate(reps: int) -> dict[str, Any]:
    n = len(CASES) * 2 * reps
    routing_in = sum(PLANNER_PROMPT_TOKENS[s] for s in ("v2", "v3")) * len(CASES) * reps
    full_in = sum((2.2 * PLANNER_PROMPT_TOKENS[s] + ANSWER_TOKENS_IN) for s in ("v2", "v3")) * len(CASES) * reps
    return {"records_per_stage": n, "routing_tokens_in": round(routing_in), "full_tokens_in": round(full_in), "routing_calls": n, "full_llm_calls_estimate": round(n * 3.2)}


def cmd_plan(args: argparse.Namespace) -> None:
    e = estimate(args.reps)
    print(f"commit {git_head()}; data in {DATA}; states: " + ", ".join(f"{s}={PATHS[s]} (digest {digest(PATHS[s])})" for s in PATHS))
    print(f"{len(CASES)} cases x 2 states x {args.reps} reps = {e['records_per_stage']} records per stage")
    for c in CASES:
        print(f"  {c.key} [{c.scenario}] first={'/'.join(c.first)} ops={'/'.join(c.ops) or '-'} max_external={c.max_external} prefs={c.preferences or '-'}")
    print(f"stage 1 routing: {e['routing_calls']} planner calls, ~{e['routing_tokens_in'] / 1e6:.2f}M input tokens (no tool, no answer, no external service)")
    print(f"stage 2 full: ~{e['full_llm_calls_estimate']} LLM calls (classifier + planner steps + answer), ~{e['full_tokens_in'] / 1e6:.2f}M input tokens, external calls only as chosen by the planner "
          f"(the budgets per turn apply). Nothing was called.")


def _guard(args: argparse.Namespace) -> None:
    if not args.live:
        raise SystemExit("this stage needs --live: it calls the OpenAI API (owner's authorisation required)")
    if os.environ.get("CINEMA_V3_EVAL_AUTHORIZED", "").strip().lower() != "yes":
        raise SystemExit("CINEMA_V3_EVAL_AUTHORIZED=yes is required in the environment of this session (never in .env, code or tests)")
    from dotenv import load_dotenv

    load_dotenv()
    DATA.mkdir(parents=True, exist_ok=True)


def _append(record: dict[str, Any]) -> None:
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _selected(args: argparse.Namespace) -> list[Case]:
    return [c for c in CASES if not args.only or c.key in args.only]


def _timeout(signum, frame):  # noqa: ARG001
    raise TimeoutError(f"run exceeded {RUN_TIMEOUT_SECONDS} s")


def cmd_routing(args: argparse.Namespace) -> None:
    _guard(args)
    from preferences import build_prompt_parts, resolve_preferences

    head, finished = git_head(), done()
    apps = {s: build(s) for s in PATHS}
    todo = [(c, s, rep) for rep in range(1, args.reps + 1) for c in _selected(args) for s in PATHS if (c.key, s, "routing", rep) not in finished]
    print(f"{len(todo)} planner calls to do", flush=True)
    signal.signal(signal.SIGALRM, _timeout)
    for i, (case, state, rep) in enumerate(todo, 1):
        record: dict[str, Any] = {"key": case.key, "state": state, "stage": "routing", "rep": rep, "git_head": head, "db": digest(PATHS[state]), "query": case.turns[0]}
        parts = build_prompt_parts(resolve_preferences(case.preferences).preferences) if case.preferences else {}
        signal.alarm(RUN_TIMEOUT_SECONDS)
        try:
            from orchestrator import _Limits

            limits = _Limits(apps[state]["config"]["orchestrator"])
            started = time.perf_counter()
            plan = apps[state]["orchestrator"]._plan_first(query=case.turns[0], conversation_history=[], limits=limits, planner_preferences=parts.get("planner", ""))
            record.update(planner_calls=limits.calls, ms=round((time.perf_counter() - started) * 1000), tool=plan.tool, operation=(plan.arguments or {}).get("operation"), arguments=plan.arguments, more_steps=plan.more_steps,
                          parts=plan.parts, fallback=plan.fallback, conflicts=plan.conflicts)
            record.update(judge_routing(case, state, plan.tool, record["operation"]))
        except Exception as exc:  # noqa: BLE001 - a failed call is data
            record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            signal.alarm(0)
        _append(record)
        print(f"[{i}/{len(todo)}] {case.key} {state}: {record.get('tool')}/{record.get('operation')} ok={record.get('first_ok')} {record.get('ms')} ms {record.get('error', '')}", flush=True)
        time.sleep(PAUSE_SECONDS)


def cmd_full(args: argparse.Namespace) -> None:
    _guard(args)
    from cinema_db.harness.tool_eval import run_live as P6

    head, finished = git_head(), done()
    apps = {s: build(s) for s in PATHS}
    todo = [(c, s, rep) for rep in range(1, args.reps + 1) for c in _selected(args) for s in PATHS if (c.key, s, "full", rep) not in finished]
    print(f"{len(todo)} full turns to do", flush=True)
    signal.signal(signal.SIGALRM, _timeout)
    for i, (case, state, rep) in enumerate(todo, 1):
        live = P6.Live(case.key, case.turns, "v3eval", case.preferences)
        record: dict[str, Any] = {"key": case.key, "state": state, "stage": "full", "rep": rep, "git_head": head, "db": digest(PATHS[state]), "query": case.turns[0]}
        signal.alarm(RUN_TIMEOUT_SECONDS)
        try:
            record.update(P6.run_one(apps[state], live))
            record.update(judge_full(case, state, record))
        except Exception as exc:  # noqa: BLE001
            record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            signal.alarm(0)
        _append(record)
        print(f"[{i}/{len(todo)}] {case.key} {state}: {record.get('tools') or record.get('error')} http={record.get('http')} {record.get('wall_s')} s", flush=True)
        time.sleep(PAUSE_SECONDS)


def report_text() -> str:
    runs = [r for r in load() if "error" not in r]
    cases = {c.key: c for c in CASES}
    if not runs:
        return "# Fase 9-G — valutazione del planner v2 / v3\n\nNessuna esecuzione registrata (preparata, non eseguita).\n"
    lines = ["# Fase 9-G — valutazione del planner v2 / v3", "", f"{len(runs)} record validi ({len(load()) - len(runs)} con errore). Giudizio deterministico; le risposte vanno lette da una persona.", ""]
    lines += ["## Stadio 1 — prima decisione del planner", "", "| Caso | Scenario | Stato | Tool / operazione | Atteso | OK | ms |", "|---|---|---|---|---|---|---|"]
    for r in sorted((x for x in runs if x["stage"] == "routing"), key=lambda x: (x["key"], x["state"], x["rep"])):
        c = cases[r["key"]]
        lines.append(f"| {r['key']} | {c.scenario} | {r['state']} | {r.get('tool')}/{r.get('operation') or '-'} | {'/'.join(c.first)} {'/'.join(expected_ops(c, r['state']))} | {'sì' if r.get('first_ok') else '**NO**'} | {r.get('ms')} |")
    lines += ["", "## Stadio 2 — turno completo", "", "| Caso | Stato | Tool | Passi esterni | Entro il tetto | Vietati | Fatti | Livello detto | HTTP | s | Passi tool |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted((x for x in runs if x["stage"] == "full"), key=lambda x: (x["key"], x["state"], x["rep"])):
        lines.append(f"| {r['key']} | {r['state']} | {'>'.join(r['tools'])} | {r['external_steps']} | {'sì' if r['within_external_budget'] else '**NO**'} | {','.join(r['forbidden_used']) or '-'} | "
                     f"{'sì' if r['must_ok'] else '**NO**'} | {'sì' if r['level_ok'] else '**NO**'} | {r['http']} | {r['wall_s']} | {r['tool_steps']} |")
    lines += ["", "## Confronto", ""]
    for stage, key in (("routing", "first_ok"), ("full", "within_external_budget")):
        for state in PATHS:
            rs = [r for r in runs if r["stage"] == stage and r["state"] == state]
            if rs:
                good = sum(1 for r in rs if r.get(key))
                extra = f", mediana {statistics.median(r['wall_s'] for r in rs):.1f} s, passi esterni medi {statistics.mean(r['external_steps'] for r in rs):.2f}" if stage == "full" else f", mediana {statistics.median(r['ms'] for r in rs) / 1000:.1f} s"
                lines.append(f"- {stage} {state}: {good}/{len(rs)} {key}{extra}")
    return "\n".join(lines) + "\n"


def cmd_report(_args: argparse.Namespace) -> None:
    text = report_text()
    OUT_MD.write_text(text, encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("plan", "routing", "full", "report"))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args(argv)
    {"plan": cmd_plan, "routing": cmd_routing, "full": cmd_full, "report": cmd_report}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
