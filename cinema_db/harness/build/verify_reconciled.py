"""Independent verification of a reconciled v3 file against the v2 runtime file and the previous v3 prototype (read-only, offline).

    python -m cinema_db.harness.build.verify_reconciled --new cinema_db/data/cinema.v3.reconciled.sqlite3

It does not trust the builder's own checks: it recomputes them from the file and runs 100 sample queries through the public views, comparing the
answers with v2 (what must be identical, what may legitimately differ). Output: a JSON report next to the file and a short text on stdout.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "cinema_db/data"


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def structural(c: sqlite3.Connection) -> dict:
    one = lambda sql: c.execute(sql).fetchone()[0]
    out = {
        "integrity_check": one("PRAGMA integrity_check"),
        "foreign_key_violations": len(c.execute("PRAGMA foreign_key_check").fetchall()),
        "works_without_exactly_one_primary_imdb_id": one("SELECT COUNT(*) FROM (SELECT entity_id FROM external_id WHERE scheme='imdb_title' GROUP BY entity_id HAVING SUM(is_primary) <> 1)"),
        "duplicated_external_ids": one("SELECT COUNT(*) FROM (SELECT scheme, value FROM external_id GROUP BY 1,2 HAVING COUNT(*) > 1)"),
        "canonical_rows": one("SELECT COUNT(*) FROM entity_canonical"),
        "canonical_chains": one("SELECT COUNT(*) FROM entity_canonical a JOIN entity_canonical b ON b.entity_id = a.canonical_entity_id"),
        "canonical_not_person_to_person": one("SELECT COUNT(*) FROM entity_canonical m LEFT JOIN person p ON p.person_id=m.entity_id LEFT JOIN person q ON q.person_id=m.canonical_entity_id WHERE p.person_id IS NULL OR q.person_id IS NULL"),
        "works_without_status": one("SELECT COUNT(*) FROM work w LEFT JOIN work_status s USING(work_id) WHERE s.work_id IS NULL"),
        "episodes_without_valid_parent": one("SELECT COUNT(*) FROM work e LEFT JOIN work p ON p.work_id=e.parent_work_id WHERE e.kind='episode' AND (p.work_id IS NULL OR p.kind NOT IN ('season','series','miniseries'))"),
        "episode_position_collisions": one("SELECT COUNT(*) FROM (SELECT COALESCE(p.parent_work_id, p.work_id) s, e.season_number, e.episode_number FROM work e JOIN work p ON p.work_id=e.parent_work_id WHERE e.kind='episode' AND e.season_number IS NOT NULL AND e.episode_number IS NOT NULL GROUP BY 1,2,3 HAVING COUNT(*) > 1)"),
        "imdb_ratings_not_from_the_primary_id": one("SELECT COUNT(*) FROM work_rating r JOIN source s USING(source_id) WHERE s.name='imdb-datasets' AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity_id=r.work_id AND x.scheme='imdb_title' AND x.is_primary=1 AND x.value=r.source_ref)"),
        "secondary_imdb_ids": one("SELECT COUNT(*) FROM external_id WHERE scheme='imdb_title' AND is_primary=0"),
        "secondary_ids_without_claim_or_unknown_marker": one(
            "SELECT COUNT(*) FROM external_id x WHERE x.scheme='imdb_title' AND x.is_primary=0 AND NOT EXISTS (SELECT 1 FROM entity_claim k WHERE k.entity_id=x.entity_id AND k.source_ref=x.value AND k.field LIKE 'imdb_alt_%')"),
        "view_rows_hiding_a_merged_person": one("SELECT COUNT(*) FROM v_person WHERE person_id IN (SELECT entity_id FROM entity_canonical)"),
        "v_credit_rows_of_merged_persons": one("SELECT COUNT(*) FROM v_credit WHERE person_id IN (SELECT entity_id FROM entity_canonical)"),
        "persons_with_two_imdb_name_ids": one("SELECT COUNT(*) FROM (SELECT entity_id FROM external_id WHERE scheme='imdb_name' GROUP BY 1 HAVING COUNT(*) > 1)"),
        "work_status_by_identification": dict(c.execute("SELECT identification, COUNT(*) FROM work_status GROUP BY 1").fetchall()),
        "work_status_by_identity_level": dict(c.execute("SELECT identity_level, COUNT(*) FROM v_work_status GROUP BY 1").fetchall()),
        "work_status_by_route": dict(c.execute("SELECT entry_route, COUNT(*) FROM work_status GROUP BY 1").fetchall()),
    }
    return out


def counts(c: sqlite3.Connection) -> dict:
    one = lambda sql: c.execute(sql).fetchone()[0]
    has = lambda t: c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone() is not None
    return {
        "works": one("SELECT COUNT(*) FROM work"), "persons": one("SELECT COUNT(*) FROM person"), "credits": one("SELECT COUNT(*) FROM credit"),
        "episodes": one("SELECT COUNT(*) FROM work WHERE kind='episode'"),
        "ratings": one("SELECT COUNT(*) FROM work_rating") if has("work_rating") else 0,
        "works_with_imdb_id": one("SELECT COUNT(DISTINCT entity_id) FROM external_id WHERE scheme='imdb_title'"),
        "persons_with_imdb_id": one("SELECT COUNT(DISTINCT entity_id) FROM external_id WHERE scheme='imdb_name'"),
    }


def samples(v2: sqlite3.Connection, new: sqlite3.Connection, seed: int = 20261108) -> dict:
    """100 queries through the public views. Expected: names unchanged, no credit lost (a merged duplicate is hidden, not lost)."""
    rnd = random.Random(seed)
    works = [w for (w,) in v2.execute("SELECT work_id FROM work WHERE kind IN ('film','short','tv_film') ORDER BY work_id")]
    persons = [p for (p,) in v2.execute("SELECT person_id FROM person ORDER BY person_id")]
    merged = {m: c for m, c in new.execute("SELECT entity_id, canonical_entity_id FROM entity_canonical")}
    failures: list[dict] = []
    ran = 0
    for w in rnd.sample(works, 50):  # 50 work queries: title and the cast/crew people (as names) must still be reachable
        ran += 1
        t2 = v2.execute("SELECT title FROM v_work WHERE work_id=?", (w,)).fetchone()
        t3 = new.execute("SELECT title FROM v_work WHERE work_id=?", (w,)).fetchone()
        if t2 != t3:
            failures.append({"query": "title", "work": w, "v2": t2, "new": t3})
        n2 = {r[0] for r in v2.execute("SELECT person_name FROM v_credit WHERE work_id=?", (w,))}
        n3 = {r[0] for r in new.execute("SELECT person_name FROM v_credit WHERE work_id=?", (w,))}
        if not n2 <= n3:
            failures.append({"query": "credit names", "work": w, "lost": sorted(n2 - n3)[:5]})
    for p in rnd.sample(persons, 50):  # 50 person queries: name unchanged, filmography (works) not smaller
        ran += 1
        canon = merged.get(p, p)
        a = v2.execute("SELECT name FROM v_person WHERE person_id=?", (p,)).fetchone()
        b = new.execute("SELECT name FROM v_person WHERE person_id=?", (canon,)).fetchone()
        if p not in merged and a != b:
            failures.append({"query": "person name", "person": p, "v2": a, "new": b})
        w2 = {r[0] for r in v2.execute("SELECT work_id FROM v_credit WHERE person_id=?", (p,))}
        w3 = {r[0] for r in new.execute("SELECT work_id FROM v_credit WHERE person_id=?", (canon,))}
        if not w2 <= w3:
            failures.append({"query": "filmography", "person": p, "lost": sorted(w2 - w3)[:5]})
    return {"queries": ran, "failures": failures}


def compare_previous(new: sqlite3.Connection, old: sqlite3.Connection, v2: sqlite3.Connection) -> dict:
    """Works of v2 only (their ids are the same in every file): which differ in kind/year/runtime from the previous v3, and how many of those
    are works with several IMDb ids, where the correction deliberately changes the values."""
    v2_ids = {w for (w,) in v2.execute("SELECT work_id FROM work")}
    doubles = {w for (w,) in new.execute("SELECT entity_id FROM external_id WHERE scheme='imdb_title' GROUP BY 1 HAVING COUNT(*) > 1")}
    new_w = {r[0]: r[1:] for r in new.execute("SELECT work_id, kind, release_year, runtime_min FROM work")}
    changed = {}
    for w, *rest in old.execute("SELECT work_id, kind, release_year, runtime_min FROM work"):
        if w in v2_ids and w in new_w and tuple(rest) != tuple(new_w[w]):
            changed[w] = (tuple(rest), tuple(new_w[w]))
    unexplained = [w for w in changed if w not in doubles]
    return {"v2_works_compared": len(v2_ids), "works_whose_kind_year_runtime_changed": len(changed), "of_which_works_with_several_imdb_ids": len(changed) - len(unexplained),
            "unexplained_changes": [(w, changed[w]) for w in unexplained[:10]], "unexplained_count": len(unexplained)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", type=Path, default=DATA / "cinema.v3.reconciled.sqlite3")
    ap.add_argument("--v2", type=Path, default=DATA / "cinema.sqlite3")
    ap.add_argument("--previous", type=Path, default=DATA / "cinema.v3.sqlite3")
    args = ap.parse_args(argv)
    new, v2, old = _ro(args.new), _ro(args.v2), _ro(args.previous)
    report = {"file": str(args.new), "structural": structural(new), "counts": {"v2": counts(v2), "previous_v3": counts(old), "new": counts(new)},
              "samples": samples(v2, new), "against_previous_v3": compare_previous(new, old, v2)}
    out = args.new.with_name(args.new.stem + ".verify.json")
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=1, ensure_ascii=False, default=str))
    print("sample queries:", report["samples"]["queries"], "failures:", len(report["samples"]["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
