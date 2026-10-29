"""Live check of the Wikidata assumptions that offline tests cannot prove. Never imported at runtime.

    python -m tool.wikidata.harness.live_smoke --live

Runs the tool itself on three questions with the real services (about nine requests: no key, but the
Query Service has its own limits): a homonym title (`Crash`), the relations of a film given by IMDb
id (The Departed, tt0407887) and the relations of a title with a year (The Thing, 1982). It prints
the status, the number of requests, the time and the SHAPE of the answer (counts per group and the
first titles), so the owner can confirm what the offline tests assume: that the composite SPARQL
queries (class flags with a bound item, both directions of each relation) are accepted and fast, and
that the groups are filled as expected. Without `--live` it does nothing.
"""
from __future__ import annotations

import argparse
import time
from typing import Any

from ..config import WikidataConfig
from ..tool import WikidataTool

CASES = (
    ("homonym title", {"operation": "resolve", "title": "Crash"}),
    ("relations by IMDb id", {"operation": "relations", "imdb_id": "tt0407887"}),
    ("relations by title and year", {"operation": "relations", "title": "The Thing", "year": 1982}),
)


def _shape(result: dict[str, Any]) -> None:
    data = result["metadata"]["wikidata"]
    print(f"   outcome={result['outcome']} status={data.get('status')}")
    for key in ("based_on", "based_on_this", "previous_in_series", "next_in_series"):
        rows = data.get(key)
        if rows is not None:
            print(f"   {key}: {len(rows)} {[row['title'] for row in rows[:3]]}")
    for franchise in data.get("franchises") or []:
        print(f"   franchise {franchise['title']!r}: {len(franchise['works'])} works, omitted={franchise['omitted']}")
    if data.get("candidates"):
        print(f"   candidates: {[(c['title'], c['year'], c['imdb_id']) for c in data['candidates']]}")
    if data.get("work"):
        print(f"   work: {data['work']['title']!r} {data['work']['year']} {data['work']['imdb_id']} tmdb={data['work']['tmdb_id']}")
    if data.get("unavailable") or data.get("franchise_list_partial"):
        print(f"   unavailable={data.get('unavailable')} partial={data.get('franchise_list_partial')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="really call Wikidata (about nine requests)")
    if not parser.parse_args(argv).live:
        print("Nothing done: pass --live to send real requests.")
        return 0
    tool = WikidataTool(config=WikidataConfig(max_calls_per_turn=8))
    for label, params in CASES:
        started = time.monotonic()
        result = tool.run(query="live smoke", params=params)
        calls = sum(len(step["data"]["calls"]) for step in result["trace"])
        print(f"\n== {label}: {calls} requests, {time.monotonic() - started:.2f} s")
        _shape(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
