"""Calibration C of the TMDb catalog: compare the index without (O) and with (E) the added films.

    python docs/qdrant_migration/catalog/calibration/calibrate.py plan
    python docs/qdrant_migration/catalog/calibration/calibrate.py compare --registry FILE --report FILE
    CATALOG_CALIBRATION_AUTHORIZED=yes python .../calibrate.py embed-queries --queries FILE --out FILE   (PAID)
    python .../calibrate.py query --vectors FILE --o-url URL --e-url URL --out FILE                  (free)

`plan` and `compare` and `query` never call a paid service. `embed-queries` calls OpenAI and refuses to
start without the explicit authorization variable. The rules R1-R3 are the ones in protocol.md, fixed
before any measurement; the module only applies them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

AUTH_ENV = "CATALOG_CALIBRATION_AUTHORIZED"
TOP = 10
PLAN = [
    "1. copy the Qdrant storage (server stopped) twice: O = untouched copy, E = clone to enrich",
    "2. insert ~20 films into E through the real path (PAID: ~20 embeddings + 20-40 TMDb calls)",
    "3. embed the query sets (PAID: ~60 embeddings; the 28 baseline vectors are already saved)",
    "4. `query`: top-10 of every query in O and in E (free)",
    "5. `compare`: classes, hub indicator, rules R1-R3 (free); blind pairwise judgment of intrusions by hand",
]


def is_catalog(point_id: str) -> bool:
    return str(point_id).startswith("tmdb:")


def classify_query(top_o: list[str], top_e: list[str], target_id: str | None = None) -> dict:
    """`unchanged` / `target_found` / `intrusion` for one query, with the ids that entered and left."""
    entered = [i for i in top_e if i not in top_o]
    left = [i for i in top_o if i not in top_e]
    result = {"entered": entered, "left": left, "rank_in_o": None, "rank_in_e": None}
    if target_id is not None:
        result["rank_in_o"] = top_o.index(target_id) + 1 if target_id in top_o else None
        result["rank_in_e"] = top_e.index(target_id) + 1 if target_id in top_e else None
    if target_id is not None and target_id in top_e and target_id not in top_o:
        result["class"] = "target_found"
    elif any(is_catalog(i) for i in entered):
        result["class"] = "intrusion"
    else:
        result["class"] = "unchanged"
    return result


def hub_counts(tops: list[list[str]]) -> Counter:
    """In how many top-10 each point appears."""
    counts: Counter = Counter()
    for top in tops:
        counts.update(set(top))
    return counts


def apply_rules(registry: list[dict], judgments: dict[str, str] | None = None) -> dict:
    """R1-R3 of protocol.md. `judgments` maps query id -> tmdb_migliore | pari | cmu_migliore (by hand).

    Returns each rule as `ok` True/False/None (None = cannot be decided with what was given).
    """
    judgments = judgments or {}
    side = [q for q in registry if q["type"] == "side"]
    hubs_e = hub_counts([q["top_e"] for q in side])
    hubs_o = hub_counts([q["top_o"] for q in side])
    worst_tmdb = max((n for i, n in hubs_e.items() if is_catalog(i)), default=0)
    worst_cmu = max((n for i, n in hubs_o.items() if not is_catalog(i)), default=0)
    intrusions = [q for q in registry if q.get("class") == "intrusion"]
    bad = [q["id"] for q in intrusions if judgments.get(q["id"]) == "cmu_migliore" and q.get("tmdb_relevance") == 0]
    unjudged = [q["id"] for q in intrusions if q["id"] not in judgments]
    r1 = None if unjudged else not bad
    r2 = worst_tmdb <= worst_cmu
    targets_new = [q for q in registry if q["type"] == "target" and q.get("kind") == "new"]
    shared = [q for q in registry if q["type"] == "target" and q.get("kind") == "shared"]
    found_new = sum(1 for q in targets_new if q["rank_in_e"] is not None)
    found_shared = sum(1 for q in shared if q["rank_in_o"] is not None)
    r3 = None if not targets_new or not shared else found_new / len(targets_new) >= found_shared / len(shared)
    return {
        "R1": {"ok": r1, "unjudged_intrusions": unjudged, "violations": bad},
        "R2": {"ok": r2, "most_frequent_tmdb": worst_tmdb, "most_frequent_cmu": worst_cmu},
        "R3": {"ok": r3, "new_found": f"{found_new}/{len(targets_new)}", "shared_found_in_o": f"{found_shared}/{len(shared)}"},
        "classes": dict(Counter(q.get("class", "unchanged") for q in registry)),
    }


def cmd_compare(args) -> int:
    data = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    registry = []
    for q in data["queries"]:
        entry = {**q, **classify_query(q["top_o"], q["top_e"], q.get("target_id"))}
        registry.append(entry)
    report = apply_rules(registry, data.get("judgments"))
    report["cmu_better_cases"] = [q["id"] for q in registry if (data.get("judgments") or {}).get(q["id"]) == "cmu_migliore"]
    Path(args.report).write_text(json.dumps({"rules": report, "queries": registry}, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=1) + "\n")
    return 0


def cmd_embed_queries(args) -> int:
    if os.environ.get(AUTH_ENV) != "yes":
        sys.stderr.write(f"Refused: this step calls OpenAI (paid). Set {AUTH_ENV}=yes only with the owner's authorization.\n")
        return 2
    from tool.rag.FromQueryEmbeddingToRes.embeddings import embed

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    vectors = embed([q["text"] for q in queries], "openai", "text-embedding-3-small", timeout=30)
    Path(args.out).write_text(json.dumps([{**q, "vector": [float(x) for x in v]} for q, v in zip(queries, vectors)]), encoding="utf-8")
    return 0


def cmd_query(args) -> int:
    from qdrant_client import QdrantClient

    vectors = json.loads(Path(args.vectors).read_text(encoding="utf-8"))
    clients = {name: QdrantClient(url=url) for name, url in (("o", args.o_url), ("e", args.e_url))}
    out = []
    for q in vectors:
        tops = {}
        for name, client in clients.items():
            points = client.query_points(args.collection, query=q["vector"], limit=TOP, with_payload=["legacy_id"]).points
            tops[f"top_{name}"] = [p.payload.get("legacy_id") for p in points]
        out.append({k: v for k, v in q.items() if k != "vector"} | tops)
    Path(args.out).write_text(json.dumps({"queries": out}, indent=1), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    c = sub.add_parser("compare"); c.add_argument("--registry", required=True); c.add_argument("--report", required=True)
    e = sub.add_parser("embed-queries"); e.add_argument("--queries", required=True); e.add_argument("--out", required=True)
    q = sub.add_parser("query")
    q.add_argument("--vectors", required=True); q.add_argument("--o-url", required=True); q.add_argument("--e-url", required=True)
    q.add_argument("--collection", default="netflix_scout"); q.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "plan":
        sys.stdout.write("\n".join(PLAN) + "\n")
        return 0
    return {"compare": cmd_compare, "embed-queries": cmd_embed_queries, "query": cmd_query}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
