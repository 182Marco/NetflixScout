"""Quantitative before/after comparison of two cinema databases (read-only): what phase 4 added, conflicts, provenance, duplicates.

    python -m cinema_db.harness.enrich.compare BEFORE.sqlite3 AFTER.sqlite3 [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

METRICS: dict[str, str] = {
    "persons": "SELECT count(*) FROM person",
    "persons_with_birth_date": "SELECT count(*) FROM person WHERE birth_date IS NOT NULL",
    "persons_with_death_date": "SELECT count(*) FROM person WHERE death_date IS NOT NULL",
    "credits": "SELECT count(*) FROM credit",
    "credits_writer": "SELECT count(*) FROM credit WHERE role='writer'",
    "credits_composer": "SELECT count(*) FROM credit WHERE role='composer'",
    "credits_cinematographer": "SELECT count(*) FROM credit WHERE role='cinematographer'",
    "credits_editor": "SELECT count(*) FROM credit WHERE role='editor'",
    "credits_producer": "SELECT count(*) FROM credit WHERE role='producer'",
    "credits_cast": "SELECT count(*) FROM credit WHERE role='cast'",
    "credits_director": "SELECT count(*) FROM credit WHERE role='director'",
    "films_with_writer": "SELECT count(DISTINCT c.work_id) FROM credit c JOIN work w ON w.work_id=c.work_id WHERE c.role='writer' AND w.kind='film'",
    "films_with_composer": "SELECT count(DISTINCT c.work_id) FROM credit c JOIN work w ON w.work_id=c.work_id WHERE c.role='composer' AND w.kind='film'",
    "films": "SELECT count(*) FROM work WHERE kind='film'",
    "awards": "SELECT count(*) FROM award",
    "award_categories": "SELECT count(*) FROM award_category",
    "ceremonies": "SELECT count(*) FROM ceremony",
    "award_results": "SELECT count(*) FROM award_result",
    "award_results_won": "SELECT count(*) FROM award_result WHERE outcome='won'",
    "works_with_an_award_result": "SELECT count(DISTINCT work_id) FROM award_result",
    "countries": "SELECT count(*) FROM country",
    "countries_with_iso2": "SELECT count(*) FROM country WHERE iso2 IS NOT NULL",
    "languages": "SELECT count(*) FROM language",
    "languages_with_iso639_1": "SELECT count(*) FROM language WHERE iso639_1 IS NOT NULL",
    "financial_rows": "SELECT count(*) FROM work_financial",
    "financial_rows_not_usd": "SELECT count(*) FROM work_financial WHERE currency <> 'USD'",
    "currencies": "SELECT count(DISTINCT currency) FROM work_financial",
    "companies": "SELECT count(*) FROM company",
    "companies_with_country": "SELECT count(*) FROM company WHERE country_id IS NOT NULL",
    "work_company": "SELECT count(*) FROM work_company",
    "franchises": "SELECT count(*) FROM franchise",
    "work_franchise": "SELECT count(*) FROM work_franchise",
    "work_relation": "SELECT count(*) FROM work_relation",
    "work_relation_based_on": "SELECT count(*) FROM work_relation WHERE relation='based_on'",
    "work_relation_follows": "SELECT count(*) FROM work_relation WHERE relation='follows'",
    "works": "SELECT count(*) FROM work",
    "work_release": "SELECT count(*) FROM work_release",
    "names": "SELECT count(*) FROM entity_name",
    "field_provenance": "SELECT count(*) FROM field_provenance",
}

CHECKS: dict[str, str] = {
    "foreign_key_violations": "SELECT count(*) FROM pragma_foreign_key_check",
    "entities_without_exactly_one_primary_name": "SELECT count(*) FROM entity e WHERE (SELECT count(*) FROM entity_name n WHERE n.entity_id=e.entity_id AND n.is_primary=1) <> 1",
    "persons_with_a_death_before_the_birth": "SELECT count(*) FROM person WHERE death_year < birth_year",
    "duplicate_credits": "SELECT count(*) FROM (SELECT 1 FROM credit GROUP BY work_id, person_id, role, COALESCE(character_name,'') HAVING count(*)>1)",
    "duplicate_wikidata_ids": "SELECT count(*) FROM (SELECT 1 FROM external_id WHERE scheme='wikidata' GROUP BY value HAVING count(*)>1)",
    "awards_without_a_category": "SELECT count(*) FROM award a WHERE NOT EXISTS (SELECT 1 FROM award_category c WHERE c.award_id=a.award_id)",
    "categories_without_a_result": "SELECT count(*) FROM award_category c WHERE NOT EXISTS (SELECT 1 FROM award_result r WHERE r.category_id=c.category_id)",
    "ceremonies_without_a_result": "SELECT count(*) FROM ceremony c WHERE NOT EXISTS (SELECT 1 FROM award_result r WHERE r.ceremony_id=c.ceremony_id)",
    "rows_without_a_source": "SELECT (SELECT count(*) FROM credit WHERE source_id IS NULL)+(SELECT count(*) FROM award_result WHERE source_id IS NULL)",
}

PROVENANCE = {
    "names_by_source": "SELECT s.name, count(*) FROM entity_name n JOIN source s ON s.source_id=n.source_id GROUP BY s.name ORDER BY 1",
    "credits_by_source": "SELECT s.name, count(*) FROM credit c JOIN source s ON s.source_id=c.source_id GROUP BY s.name ORDER BY 1",
    "award_results_by_source": "SELECT s.name, count(*) FROM award_result c JOIN source s ON s.source_id=c.source_id GROUP BY s.name ORDER BY 1",
    "field_provenance_by_field": "SELECT field, count(*) FROM field_provenance GROUP BY field ORDER BY 1",
}


def measure(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {
            "metrics": {k: conn.execute(sql).fetchone()[0] for k, sql in METRICS.items()},
            "checks": {k: conn.execute(sql).fetchone()[0] for k, sql in CHECKS.items()},
            "provenance": {k: conn.execute(sql).fetchall() for k, sql in PROVENANCE.items()},
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "content_sha256": dict(conn.execute("SELECT key, value FROM build_info").fetchall()).get("content_sha256"),
        }
    finally:
        conn.close()


def compare(before: Path, after: Path) -> dict[str, Any]:
    b, a = measure(before), measure(after)
    return {"before": b, "after": a, "delta": {k: a["metrics"][k] - b["metrics"][k] for k in METRICS}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    r = compare(args.before, args.after)
    print(f"{'metric':42} {'before':>10} {'after':>10} {'delta':>10}")
    for k in METRICS:
        print(f"{k:42} {r['before']['metrics'][k]:>10,} {r['after']['metrics'][k]:>10,} {r['delta'][k]:>+10,}")
    print("\nchecks (before -> after):")
    for k in CHECKS:
        print(f"  {k:48} {r['before']['checks'][k]} -> {r['after']['checks'][k]}")
    print("integrity:", r["before"]["integrity"], "->", r["after"]["integrity"])
    for k, rows in r["after"]["provenance"].items():
        print(f"\n{k}:", rows)
    if args.json:
        args.json.write_text(json.dumps(r, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
