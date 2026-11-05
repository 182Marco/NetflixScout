"""Offline computation of WHICH Wikidata items phase 4 needs, from the local sources only (no network).

The sets mirror what the build meets and cannot name: people with only a QID, award items and the ceremonies/nominees of their
statements, currency units, relation targets and franchises/companies without a label, release places, countries and languages
without an ISO code. Nothing here guesses: an item is a target because a local statement points at it.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from cinema_db.harness.build import extract as X
from cinema_db.harness.build import sources as S
from cinema_db.harness.build.build import USD, WORLDWIDE, jsonl
from cinema_db.harness.build.snapshot import Snapshot

CATEGORIES = ("persons", "awards", "currencies", "relation_targets", "companies", "franchises", "places", "countries", "languages", "dual_use")


def compute(film_snapshot: Path = S.FILM_SNAPSHOT, series_snapshot: Path = S.SERIES_SNAPSHOT, film_catalog: Path = S.FILM_CATALOG,
            series_dir: Path = S.SERIES_DIR) -> dict[str, Any]:
    film_snap, series_snap = Snapshot(film_snapshot), Snapshot(series_snapshot)
    labels = {**series_snap.labels(), **film_snap.labels()}
    catalog = list(jsonl(film_catalog))
    catalog_names: dict[str, str] = {}
    for r in catalog:
        for p in (r.get("director") or []) + (r.get("actors") or []):
            if p.get("wikidata_id") and p.get("name"):
                catalog_names.setdefault(p["wikidata_id"], p["name"])

    def named(q: str) -> bool:
        lab = labels.get(q, {})
        return bool(lab.get("it") or lab.get("en") or q in catalog_names)

    series_rows = list(jsonl(series_dir / "series.jsonl"))
    tv_rows = list(jsonl(series_dir / "tv_movies.jsonl"))
    film_qids = {r["wikidata_id"] for r in catalog if r.get("wikidata_id")}
    reliable = {(r.get("ids") or {}).get("qid") for r in series_rows if r.get("default_search_eligible") and r.get("ids_reliable")}
    reliable |= {(r.get("ids") or {}).get("qid") for r in tv_rows if r.get("ids_reliable")}
    reliable.discard(None)
    summaries = [X.summarize(q, e) for q, e in film_snap.entities() if q in film_qids]
    summaries += [X.summarize(q, e) for q, e in series_snap.entities() if q in reliable]
    seen: set[str] = set()
    summaries = [s for s in summaries if not (s["qid"] in seen or seen.add(s["qid"]))]

    t: dict[str, set[str]] = {c: set() for c in CATEGORIES}
    persons_unnamed_by_role: dict[str, set[str]] = defaultdict(set)
    award_items, ceremonies, nominees, relation, units, places = set(), set(), set(), set(), set(), set()
    countries, languages = set(), set()
    company_all: set[str] = set()
    for s in summaries:
        for role, rows in s["roles"].items():
            for row in rows:
                t["persons"].add(row["person"])
                if not named(row["person"]):
                    persons_unnamed_by_role[role].add(row["person"])
        for a in s["awards"]:
            award_items.add(a["award"])
            ceremonies.update(a["ceremony"])
            nominees.update(a["nominee"])
        for targets in s["relations"].values():
            relation.update(x for x in targets if not named(x))
        for kind, qs in s["companies"].items():
            t["companies"].update(q for q in qs if not named(q))
        for qs in s["franchises"].values():
            t["franchises"].update(q for q in qs if not named(q))
        for f in s["financial"]:
            if f["unit"] != USD:
                units.add(f["unit"])
            places.update(p for p in f["places"] if p != WORLDWIDE and not named(p))
        for d in s["dates"]:
            places.update(p for p in d["places"] if not named(p))
        for qs in s["companies"].values():
            company_all.update(qs)
        countries.update(s["countries"])
        languages.update(s["languages"])
    t["persons"].update(nominees)
    t["awards"] = award_items | ceremonies
    t["currencies"] = units
    t["relation_targets"] = relation
    t["places"] = places
    t["countries"] = countries
    t["languages"] = languages
    t["dual_use"] = t["persons"] & company_all  # items that are both a credit holder and a company: person or organisation? their class decides
    return {
        "sets": {k: sorted(v) for k, v in t.items()},
        "unnamed_persons_by_role": {k: len(v) for k, v in sorted(persons_unnamed_by_role.items())},
        "unnamed_persons": sorted(set().union(*persons_unnamed_by_role.values()) if persons_unnamed_by_role else set()),
        "ceremony_items": sorted(ceremonies),
        "nominee_items": sorted(nominees),
        "works_considered": len(summaries),
        "persons_named_already": sum(1 for q in t["persons"] if named(q)),
    }


def main() -> int:
    r = compute()
    print(json.dumps({"works": r["works_considered"], "persons_total": len(r["sets"]["persons"]), "persons_named_already": r["persons_named_already"],
                      "unnamed_persons": len(r["unnamed_persons"]), "by_role": r["unnamed_persons_by_role"],
                      **{k: len(v) for k, v in r["sets"].items() if k != "persons"}, "ceremonies": len(r["ceremony_items"]), "nominees": len(r["nominee_items"])}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
