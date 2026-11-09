"""A0 audit command line. Offline, read-only on every archive; writes only to `cinema_db/data/audit_a0/` (and the report).

    python -m cinema_db.harness.audit.run_audit targets      # MovieLens films missing from cinema -> targets.json (seconds)
    python -m cinema_db.harness.audit.run_audit scan         # ONE streaming pass over the local Italian dump (~15 min)
    python -m cinema_db.harness.audit.run_audit run          # all sections -> results.json, candidates_*.jsonl, ml_missing.jsonl
    python -m cinema_db.harness.audit.run_audit report       # results.json -> docs/cinema_db/PHASE9_A0_AUDIT.md (deterministic)

Same inputs, same outputs: sections are pure functions of the archives (timings are the only varying value and are kept
out of the result files).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import dump_scan, sections, util


def cmd_targets(ctx: sections.Context) -> None:
    missing = sections.ml_missing_targets(ctx)
    keys = sections.target_keys(missing)
    util.write_json(ctx.out_dir / "targets.json", {"movielens_missing": len(missing), "keys": keys})
    print(f"targets: {len(missing)} MovieLens films missing from cinema, {len(keys)} normalised title keys")


def cmd_scan(ctx: sections.Context, dump: Path | None = None) -> None:
    targets = frozenset(json.loads((ctx.out_dir / "targets.json").read_text(encoding="utf-8"))["keys"])
    stats = dump_scan.run_scan(targets, ctx.out_dir / "dump_scan.jsonl", dump=dump or util.DUMP)
    util.write_json(ctx.out_dir / "dump_scan.stats.json", {k: v for k, v in stats.items() if k != "seconds"})
    print("scan:", stats)


def cmd_run(ctx: sections.Context) -> dict:
    results: dict = {}
    t0 = time.time()

    def step(name: str, fn):
        started = time.time()
        value = fn()
        print(f"[{name}] {time.time() - started:.1f}s", file=sys.stderr, flush=True)
        return value

    results["inventory"] = step("inventory", lambda: sections.inventory(ctx))
    results["overlap"] = step("overlap", lambda: sections.overlap(ctx))
    results["ml_relevance_curve"] = step("ml_curve", lambda: sections.ml_relevance_curve(ctx))
    summary, rows = step("ml_missing", lambda: sections.ml_missing_analysis(ctx))
    results["ml_missing"] = summary
    util.write_jsonl(ctx.out_dir / "ml_missing.jsonl", rows)
    results["identifiers"] = step("identifiers", lambda: sections.identifiers(ctx))
    dup_summary, candidates = step("duplicates", lambda: sections.duplicates(ctx))
    results["duplicates"] = dup_summary
    for name, rows_ in candidates.items():
        util.write_jsonl(ctx.out_dir / f"candidates_{name}.jsonl", rows_)
    results["coverage"] = step("coverage", lambda: sections.coverage(ctx))
    results["added_value"] = step("added_value", lambda: sections.added_value(ctx))
    results["dump"] = step("dump", lambda: sections.dump_summary(ctx))
    util.write_json(ctx.out_dir / "results.json", results)
    print(f"run complete in {time.time() - t0:.0f}s -> {ctx.out_dir / 'results.json'}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["targets", "scan", "run", "report"])
    parser.add_argument("--out", type=Path, default=util.OUT_DIR)
    args = parser.parse_args(argv)
    ctx = sections.Context(args.out)
    if args.command == "targets":
        cmd_targets(ctx)
    elif args.command == "scan":
        cmd_scan(ctx)
    elif args.command == "run":
        cmd_run(ctx)
    else:
        from . import report
        report.write_report((args.out / "results.json"), util.REPORT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
