"""Phase 4 driver.

    python -m cinema_db.harness.enrich.fetch plan                          # offline: writes <store>/plan.json with the exact ids and request counts
    python -m cinema_db.harness.enrich.fetch status                        # offline: requests done / pending per category
    python -m cinema_db.harness.enrich.fetch run --category awards         # NETWORK (authorised): all pending batches of a category
    python -m cinema_db.harness.enrich.fetch run --category persons --limit 5

`run` never repeats a stored request, never requests anything outside the plan, and can be interrupted and resumed at any time.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cinema_db.harness.enrich import builders
from cinema_db.harness.enrich.client import Client, CircuitOpen
from cinema_db.harness.enrich.store import DEFAULT_ROOT, PhaseStore, request_key

ORDER = ("awards", "award_parents", "currencies", "persons", "countries", "languages", "relation_targets", "franchises", "companies", "places", "dual_use")


def load_plan(root: Path) -> dict:
    path = Path(root) / "plan.json"
    if not path.is_file():
        raise SystemExit(f"{path} missing: run `plan` first")
    return json.loads(path.read_text(encoding="utf-8"))


def plan_ids(plan: dict, category: str, root: Path = DEFAULT_ROOT) -> list[str]:
    """Persons are requested unnamed first (they unlock the credits that are discarded today), then everyone else."""
    if category == "award_parents":
        return derived_award_parents(plan, root)
    if category == "persons":
        first = plan["unnamed_persons"]
        rest = sorted(set(plan["sets"]["persons"]) - set(first))
        return first, rest  # type: ignore[return-value]
    return plan["sets"][category]


def derived_award_parents(plan: dict, root: Path) -> list[str]:
    """Parent awards that the already stored award and ceremony items point at (category -> P361, ceremony -> P179) and the plan lacks."""
    from cinema_db.harness.build import extract as X
    from cinema_db.harness.build.snapshot import Snapshot

    path = Path(root)
    if not (path / "requests.jsonl").is_file():
        return []
    have = set(plan["sets"]["awards"])
    wanted: set[str] = set()
    snap = Snapshot(path)
    for r in snap.requests:
        if r.params.get("action") == "wbgetentities" and r.status == 200 and r.params.get("props") == "labels|claims":
            for q, e in snap.body(r).get("entities", {}).items():
                if q in have:
                    for prop in ("P361", "P179"):
                        wanted.update(X.items(e, prop))
    return sorted(wanted - have)


def all_batches(plan: dict, category: str, root: Path = DEFAULT_ROOT):
    if category == "persons":
        first, rest = plan_ids(plan, "persons")
        yield from builders.batches("persons", first)
        yield from ((e, p, {**m, "category": "persons", "group": "rest"}) for e, p, m in builders.batches("persons", rest))
    else:
        yield from builders.batches(category, plan_ids(plan, category, root))


def status(root: Path) -> dict:
    plan, store = load_plan(root), PhaseStore(root)
    out = {}
    for c in ORDER:
        total = done = 0
        for endpoint, params, _ in all_batches(plan, c, root):
            total += 1
            done += store.has(request_key(endpoint, params))
        out[c] = {"requests": total, "done": done}
    return out


def run(root: Path, category: str, limit: int | None, client: Client | None = None) -> dict:
    plan = load_plan(root)
    store = PhaseStore(root)
    client = client or Client(store)
    n = 0
    try:
        for endpoint, params, meta in all_batches(plan, category, root):
            if store.has(request_key(endpoint, params)):
                continue
            if limit is not None and n >= limit:
                break
            n += 1
            key = client.fetch(endpoint, params, meta)
            if n % 10 == 0 or limit is not None:
                print(f"  {category}: {n} requests this run, stored {client.stats['stored']}, failed {client.stats['failed']}", flush=True)
    except CircuitOpen as e:
        print(f"STOPPED: {e}", file=sys.stderr)
    return client.stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("plan", "status", "run"))
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--category", choices=ORDER)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    if a.command == "plan":
        from cinema_db.harness.enrich import targets

        a.root.mkdir(parents=True, exist_ok=True)
        plan = targets.compute()
        (a.root / "plan.json").write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(status(a.root), indent=1))
    elif a.command == "status":
        print(json.dumps(status(a.root), indent=1))
    else:
        if not a.category:
            ap.error("--category is required for run")
        print(json.dumps(run(a.root, a.category, a.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
