"""REPORT ONLY: which "new IMDb person <-> existing person" pairs (the persons created for weak candidates) have independent evidence that they
might be the same human. Nothing is merged and no database is modified.

    python -m cinema_db.harness.build.person_merge_report --db cinema_db/data/cinema.v3.reconciled.sqlite3

A pair comes from the claim `imdb_person_possibly_existing_person` (new person -> existing person) and the candidate row on the existing person. Evidence:
 - the dates do not contradict (a conflicting birth year is the strongest reason to keep two persons apart);
 - the name is UNIQUE on both sides: exactly one existing person and exactly one IMDb person carry it (compared in their own script) - a homonym
   cannot be excluded for a common name, so a shared name alone is never evidence;
 - how many titles matched (the weak tier has exactly one: more would have been a strong match, already attached).
Classes: `contradicted` (keep apart), `homonym_risk` (the name is shared by several persons on at least one side), `plausible_single_candidate`
(unique name both sides, one matching title, dates compatible: the only class that could ever be proposed for a future, explicitly authorised merge).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path

from cinema_db.harness.build.title_keys import person_key

ROOT = Path(__file__).resolve().parents[3]


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "cinema_db/data/cinema.v3.reconciled.sqlite3")
    ap.add_argument("--staging", type=Path, default=ROOT / "cinema_db/data/audit_a1/imdb_staging.sqlite3")
    args = ap.parse_args(argv)
    db, st = _ro(args.db), sqlite3.connect(f"file:{args.staging}?mode=ro", uri=True)
    cinema_names: collections.Counter = collections.Counter()
    for (n,) in db.execute("SELECT n.name FROM entity_name n JOIN person p ON p.person_id = n.entity_id WHERE n.is_primary = 1 AND p.person_id NOT IN (SELECT entity_id FROM external_id WHERE scheme='imdb_name' AND source_ref='layer:new_person')"):
        cinema_names[person_key(n)] += 1
    imdb_names: collections.Counter = collections.Counter(person_key(n) for (n,) in st.execute("SELECT name FROM name"))
    out, summary = [], collections.Counter()
    rows = db.execute("SELECT k.entity_id, CAST(k.value AS INTEGER), k.source_ref FROM entity_claim k WHERE k.field = 'imdb_person_possibly_existing_person' ORDER BY 1, 2").fetchall()
    for new_id, old_id, ref in rows:
        nconst, tier = ref.split(":", 1)
        q = db.execute("SELECT p.birth_year, p.death_year, n.name FROM person p JOIN entity_name n ON n.entity_id = p.person_id AND n.is_primary = 1 WHERE p.person_id = ?", (new_id,)).fetchone()
        p = db.execute("SELECT p.birth_year, p.death_year, n.name FROM person p JOIN entity_name n ON n.entity_id = p.person_id AND n.is_primary = 1 WHERE p.person_id = ?", (old_id,)).fetchone()
        ev = db.execute("SELECT evidence FROM external_id_candidate WHERE entity_id = ? AND scheme = 'imdb_name' AND value = ?", (old_id, nconst)).fetchone()
        titles = re.search(r"title matches: (\d+)", ev[0] or "") if ev else None
        contradiction = (p[0] and q[0] and p[0] != q[0]) or (p[1] and q[1] and p[1] != q[1]) or tier == "conflict_birth_year"
        key = person_key(p[2])
        cn, inn = cinema_names[key], imdb_names[person_key(q[2])]
        if contradiction:
            cls = "contradicted"
        elif tier == "weak_single_title" and cn == 1 and inn == 1:
            cls = "plausible_single_candidate"
        else:
            cls = "homonym_risk"
        summary[(tier, cls)] += 1
        out.append({"new_person": new_id, "existing_person": old_id, "nconst": nconst, "tier": tier, "class": cls, "name": p[2],
                    "existing_persons_with_this_name": cn, "imdb_persons_with_this_name": inn, "matched_titles": int(titles.group(1)) if titles else None,
                    "birth_existing": p[0], "birth_new": q[0], "death_existing": p[1], "death_new": q[1]})
    target = args.db.with_name(args.db.stem + ".person_merge_candidates.jsonl")
    target.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    result = {f"{t}|{c}": n for (t, c), n in sorted(summary.items())}
    args.db.with_name(args.db.stem + ".person_merge_candidates.summary.json").write_text(json.dumps({"pairs": len(out), "by_tier_and_class": result}, indent=1), encoding="utf-8")
    print(json.dumps({"pairs": len(out), "by_tier_and_class": result}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
