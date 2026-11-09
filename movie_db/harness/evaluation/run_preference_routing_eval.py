"""Live evaluation of the REAL planner under the three values of `content_type` (film / series / both). docs/cinema_db/PLANNER_PREFERENCE_MATRIX.md.

What is real: the planner model, the orchestrator loop (first step, next steps, replanning after a blocked step), the tool catalogue and schemas the planner sees,
the settings prompt and the deterministic guard `SettingsPolicy`, the integrated routing rules (cinema database schema 4, series RAG on).
What is replaced: the tools themselves run as RECORDING STUBS (they return a small canned result with IMDb ids) and the final answer is not generated, so a case costs only
planner calls. The domain classifier is not called (it does not read the setting). A tool counts as EXECUTED only if the guard let it through.

    python -m movie_db.harness.evaluation.run_preference_routing_eval plan
    PREF_ROUTING_AUTHORIZED=yes python -m movie_db.harness.evaluation.run_preference_routing_eval run --live --label X [--only Q03 ...] [--max-calls 60]
    python -m movie_db.harness.evaluation.run_preference_routing_eval report --label X

Results: cinema_db/data/preference_routing/<label>/run.jsonl (one row per cell, written as it happens, resumable) and summary.json."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from .preference_routing_cases import BOTH, FILM, RAGS, SERIES, PrefCase, cells

ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = ROOT / "cinema_db/data/preference_routing"
AUTH_ENV = "PREF_ROUTING_AUTHORIZED"
from cinema_db.harness.candidate import EXPECTED as _CANDIDATE  # noqa: E402  (the one definition of the schema-4 target)

CINEMA_DB = _CANDIDATE["path"]
DEFAULT_MAX_CALLS = 60


class CallCapReached(RuntimeError):
    """The next planner call would exceed the authorised number of calls."""


class CountingClient:
    """Wraps the OpenAI client: counts calls, tokens and milliseconds, and refuses a call beyond the cap (raised BEFORE sending)."""

    def __init__(self, inner: Any, cap: int) -> None:
        self.inner, self.cap, self.total, self.refused = inner, cap, 0, False
        self.events: list[dict[str, Any]] = []
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        if self.total >= self.cap:
            self.refused = True  # the orchestrator swallows planner errors, so the runner checks this flag after the cell
            raise CallCapReached(f"{self.total} calls made, cap {self.cap}")
        self.total += 1
        t0 = time.perf_counter()
        ok = True
        try:
            response = self.inner.responses.create(**kwargs)
            usage = getattr(response, "usage", None)
            self.events.append({"model": kwargs.get("model"), "input": int(getattr(usage, "input_tokens", 0) or 0), "output": int(getattr(usage, "output_tokens", 0) or 0),
                                "text": str(getattr(response, "output_text", "") or "")[:700]})
            return response
        except Exception:
            ok = False
            raise
        finally:
            if not ok:
                self.events.append({"model": kwargs.get("model"), "error": True})
            self.events[-1]["ms"] = round((time.perf_counter() - t0) * 1000)


class RecordingPolicy:
    """The real `SettingsPolicy`, plus a log of every step the planner proposed and what the guard said."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.log = inner, []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def check_step(self, tool: str, arguments: dict[str, Any]) -> Any:
        verdict = self.inner.check_step(tool, arguments)
        self.log.append({"tool": tool, "operation": arguments.get("operation") if isinstance(arguments, dict) else None,
                         "blocked": verdict.arguments is None, "changed": bool(getattr(verdict, "changed", False))})
        return verdict


def canned_result(name: str, query: str) -> dict[str, Any]:
    """A small plausible result per tool, with IMDb ids where the real tool gives them, so the planner can plan a next step."""
    base: dict[str, Any] = {"query": query, "chunks": [], "trace": [], "outcome": {"status": "ok"}}
    if name == "rag_search":
        return {**base, "metadata": {"films": [{"n": 1, "imdb_id": "tt0118929", "title": "Dark City", "year": 1998}, {"n": 2, "imdb_id": "tt0120907", "title": "eXistenZ", "year": 1999}]}}
    if name == "series_rag_search":
        return {**base, "metadata": {"series_rag": {"status": "ok", "level": "series", "count": 2, "items": [
            {"n": 1, "imdb_id": "tt5753856", "level": "series", "title": "Dark", "year": 2017}, {"n": 2, "imdb_id": "tt4574334", "level": "series", "title": "Stranger Things", "year": 2016}]}}}
    return {**base, "metadata": {"stub": f"{name} would run here; no data is returned by this evaluation"}}


class StubTool:
    """Same name, description and schema as the real tool (the planner sees the real catalogue); `run` only records the call."""

    def __init__(self, real: Any, executed: list[dict[str, Any]]) -> None:
        self.name, self.description, self.input_schema = real.name, real.description, real.input_schema
        self._executed = executed

    def run(self, *, query: str, params: dict[str, Any] | None = None, conversation_history: Any = None) -> dict[str, Any]:
        args = {k: v for k, v in (params or {}).items() if not k.startswith("turn_")}
        self._executed.append({"tool": self.name, "operation": args.get("operation"), "arguments": args})
        return canned_result(self.name, query)


def grade(expect: Any, executed: list[dict[str, Any]], conflicts: list[dict[str, Any]], blocked: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure. `executed`: calls that really ran; `blocked`: steps the guard refused (the planner proposed them); `conflicts`: settings conflicts declared."""
    names = [e["tool"] for e in executed]
    problems: list[str] = []
    if expect.conflict:
        if not conflicts:
            problems.append("no conflict declared")
        if names:
            problems.append(f"tools executed under a conflict: {names}")
    else:
        for tool in expect.require:
            if tool not in names:
                problems.append(f"required tool not executed: {tool}")
        for tool in expect.forbid:
            if tool in names:
                problems.append(f"forbidden tool executed: {tool}")
        if expect.one_rag:
            used = [r for r in RAGS if r in names]
            if len(used) != 1:
                problems.append(f"expected exactly one RAG, got {used}")
        if expect.cinema_op and not any(e["tool"] == "cinema_sql" and e.get("operation") == expect.cinema_op for e in executed):
            problems.append(f"cinema_sql operation {expect.cinema_op} not executed")
        elif expect.cinema_args:
            calls = [e for e in executed if e["tool"] == "cinema_sql" and e.get("operation") == expect.cinema_op]
            def matches(call: dict[str, Any]) -> bool:
                got = call.get("arguments") or {}
                return all((got.get(k) is None) if v == "absent" else got.get(k) == v for k, v in expect.cinema_args)
            if calls and not any(matches(c) for c in calls):
                problems.append(f"cinema_sql {expect.cinema_op} arguments {[{k: (c.get('arguments') or {}).get(k) for k, _ in expect.cinema_args} for c in calls]} != {dict(expect.cinema_args)}")
        if conflicts and not names:
            problems.append("conflict declared and nothing executed for a compatible request")
    if blocked:
        problems.append(f"planner proposed {len(blocked)} step(s) the guard had to block: {[b['tool'] for b in blocked]}")
    redundant = len(names) - len(set(names))
    return {"correct": not problems, "problems": problems, "guard_rescued": bool(blocked) and not [p for p in problems if not p.startswith("planner proposed")],
            "redundant_calls": redundant}


def build_runtime(client: Any) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """The integrated configuration (schema-4 database, series RAG on), the real tool catalogue and an orchestrator whose tools are recording stubs."""
    import app as app_module
    from orchestrator import LLMOrchestrator
    built = app_module.build_app(app_module._deep_merge({"cinema_db": {"enabled": True, "db_path": CINEMA_DB}}, {"series_rag": {"enabled": True}}))
    executed: list[dict[str, Any]] = []
    stubs = [StubTool(tool, executed) for tool in built["orchestrator"].tools.values()]
    orch = LLMOrchestrator(config=built["config"], tools=stubs, client=client)
    orch._generate_final_answer = lambda **kw: "[answer not generated in this evaluation]"  # type: ignore[method-assign]
    return orch, executed, built["config"]


def run_cell(orch: Any, executed: list[dict[str, Any]], client: Any, case: PrefCase, value: str, expect: Any) -> dict[str, Any]:
    from preferences import SettingsPolicy, build_prompt_parts, resolve_preferences
    prefs = resolve_preferences({"content_type": value}).preferences
    policy = RecordingPolicy(SettingsPolicy(prefs))
    executed.clear()
    calls_before, events_before = client.total, len(client.events)
    t0 = time.perf_counter()
    error = None
    decision: dict[str, Any] = {}
    try:
        decision = orch.run(query=case.question, conversation_history=list(case.history), prompt_parts=build_prompt_parts(prefs), settings_policy=policy, answer_language="it")
    except CallCapReached:
        raise
    except Exception as exc:  # noqa: BLE001  (recorded: a failing planner call is a result, not a crash of the run)
        error = type(exc).__name__
    if client.refused:
        raise CallCapReached(f"{client.total} calls made, cap {client.cap}")
    blocked = [e for e in policy.log if e["blocked"]]
    conflicts = list(decision.get("settings_conflicts") or [])
    ran = [dict(e) for e in executed]
    row = {"id": case.id, "value": value, "question": case.question, "critical": case.critical, "executed": ran, "guard_log": policy.log, "blocked_attempts": blocked,
           "conflicts": conflicts, "stop_reason": (decision.get("planning") or {}).get("stop_reason"), "fallbacks": (decision.get("planning") or {}).get("fallbacks"),
           "planner_calls": client.total - calls_before, "tokens": {"input": sum(e.get("input", 0) for e in client.events[events_before:]),
                                                                    "output": sum(e.get("output", 0) for e in client.events[events_before:])},
           "ms": round((time.perf_counter() - t0) * 1000), "error": error,
           "planner_texts": [e.get("text") for e in client.events[events_before:]], "planner_output": (decision.get("planning") or {}).get("planner_output")}
    row["grade"] = grade(expect, ran, conflicts, blocked) if not error else {"correct": False, "problems": [f"error {error}"], "guard_rescued": False, "redundant_calls": 0}
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def stat(sel: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(sel)
        return {"cells": n, "correct": sum(r["grade"]["correct"] for r in sel), "pct": round(100 * sum(r["grade"]["correct"] for r in sel) / n, 1) if n else None,
                "guard_blocks": sum(len(r["blocked_attempts"]) for r in sel), "guard_rescued": sum(r["grade"]["guard_rescued"] for r in sel),
                "redundant_calls": sum(r["grade"]["redundant_calls"] for r in sel), "planner_calls": sum(r["planner_calls"] for r in sel)}
    crit = [r for r in rows if r["critical"]]
    return {"overall": stat(rows), "by_value": {v: stat([r for r in rows if r["value"] == v]) for v in (FILM, SERIES, BOTH)}, "critical": stat(crit),
            "critical_failures": [f"{r['id']}/{r['value']}" for r in crit if not r["grade"]["correct"]],
            "failures": [{"cell": f"{r['id']}/{r['value']}", "problems": r["grade"]["problems"]} for r in rows if not r["grade"]["correct"]],
            "tokens": {"input": sum(r["tokens"]["input"] for r in rows), "output": sum(r["tokens"]["output"] for r in rows)},
            "median_ms": sorted(r["ms"] for r in rows)[len(rows) // 2] if rows else None,
            "passed": bool(rows) and all(r["grade"]["correct"] for r in crit) and all(not r["blocked_attempts"] for r in rows)}


def cmd_plan(args: argparse.Namespace) -> int:
    flat = cells()
    only = set(args.only or [])
    sel = [c for c in flat if not only or c[0].id in only]
    for case, value, expect in sel:
        kind = "CONFLICT" if expect.conflict else f"require={list(expect.require)} forbid={list(expect.forbid)}" + (" one_rag" if expect.one_rag else "")
        print(f"  {case.id} {value:6} {'*' if case.critical else ' '} {case.question[:62]:62} {kind}")
    print(f"\n{len(sel)} cells; one planner call each plus extra calls for multi-step plans and replanning after a blocked step "
          f"(estimate {len(sel)}–{round(len(sel) * 1.4)}; hard cap --max-calls, default {DEFAULT_MAX_CALLS}). No classifier, no tool, no answer call. Nothing was called.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.live or os.environ.get(AUTH_ENV) != "yes":
        print(f"Refusing to run: this calls the planner model. Pass --live and set {AUTH_ENV}=yes. `plan` shows what it would do.")
        return 2
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv()
    out = OUT_ROOT / args.label
    out.mkdir(parents=True, exist_ok=True)
    path = out / "run.jsonl"
    if args.force and path.exists():
        path.unlink()
    done = {(r["id"], r["value"]) for r in map(json.loads, path.open())} if path.exists() else set()
    client = CountingClient(OpenAI(max_retries=0, timeout=90), args.max_calls)
    orch, executed, _config = build_runtime(client)
    only = set(args.only or [])
    with path.open("a") as f:
        for case, value, expect in cells():
            if (only and case.id not in only) or (args.values and value not in args.values) or (case.id, value) in done:
                continue
            try:
                row = run_cell(orch, executed, client, case, value, expect)
            except CallCapReached as exc:
                print(f"Stopped before exceeding the cap: {exc}. Rows so far are kept; ask before raising it.")
                break
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  {case.id} {value:6} {'OK ' if row['grade']['correct'] else 'BAD'} calls={row['planner_calls']} {row['ms']:6} ms executed={[e['tool'] + (':' + e['operation'] if e.get('operation') else '') for e in row['executed']]}"
                  f"{' conflicts=' + str([c['setting'] for c in row['conflicts']]) if row['conflicts'] else ''}{' BLOCKED=' + str([b['tool'] for b in row['blocked_attempts']]) if row['blocked_attempts'] else ''}")
    print(f"planner calls this run: {client.total}")
    return cmd_report(argparse.Namespace(label=args.label))


def cmd_report(args: argparse.Namespace) -> int:
    path = OUT_ROOT / args.label / "run.jsonl"
    if not path.exists():
        print(f"No results at {path}")
        return 1
    rows = [json.loads(line) for line in path.open()]
    summary = summarize(rows)
    (path.parent / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: summary[k] for k in ("overall", "by_value", "critical", "critical_failures", "tokens", "median_ms", "passed")}, indent=1, ensure_ascii=False))
    for fail in summary["failures"]:
        print("  FAIL", fail["cell"], "-", "; ".join(fail["problems"]))
    return 0


def reconcile(labels: list[str]) -> dict[str, Any]:
    """Pure over the stored rows: per cell, the first result and every later re-run (the historical files are only read, never rewritten), plus the real call total."""
    cellmap: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for label in labels:
        path = OUT_ROOT / label / "run.jsonl"
        if not path.exists():
            continue
        for r in map(json.loads, path.open()):
            total += r["planner_calls"]
            cellmap.setdefault(f"{r['id']}/{r['value']}", []).append({"run": label, "correct": r["grade"]["correct"], "problems": r["grade"]["problems"],
                                                                      "executed": [e["tool"] for e in r["executed"]], "conflicts": [c["setting"] for c in r["conflicts"]],
                                                                      "planner_calls": r["planner_calls"]})
    first = {c: h[0]["correct"] for c, h in cellmap.items() if h[0]["run"] == labels[0]}
    latest = {c: h[-1]["correct"] for c, h in cellmap.items()}
    rerun = {c: h for c, h in cellmap.items() if len(h) > 1}
    return {"labels": labels, "planner_calls_total": total, "cells": len(cellmap), "first_run_correct": sum(first.values()), "first_run_cells": len(first),
            "latest_correct": sum(latest.values()), "failed_in_first_run": sorted(c for c, ok in first.items() if not ok),
            "still_failing_after_reruns": sorted(c for c, ok in latest.items() if not ok), "reruns": rerun}


def cmd_reconcile(args: argparse.Namespace) -> int:
    out = reconcile(args.labels)
    (OUT_ROOT / "RECONCILIATION.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k != "reruns"}, indent=1, ensure_ascii=False))
    for cell, hist in out["reruns"].items():
        print(f"  {cell}: " + " -> ".join(f"{h['run']}={'OK' if h['correct'] else 'BAD'}" for h in hist))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--only", nargs="*")
    p = sub.add_parser("run")
    p.add_argument("--live", action="store_true"); p.add_argument("--label", required=True); p.add_argument("--only", nargs="*")
    p.add_argument("--values", nargs="*", choices=(FILM, SERIES, BOTH)); p.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS); p.add_argument("--force", action="store_true")
    p = sub.add_parser("report"); p.add_argument("--label", required=True)
    p = sub.add_parser("reconcile"); p.add_argument("--labels", nargs="+", default=["first", "q08", "fix", "fix_series"])
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "run": cmd_run, "report": cmd_report, "reconcile": cmd_reconcile}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
