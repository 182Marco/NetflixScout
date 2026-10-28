"""Live check of the OMDb assumptions that offline tests cannot prove. Never imported at runtime.

    python -m tool.omdb.harness.live_smoke --live

Six real requests of the daily 1,000 (free key): the record of a known IMDb ID, a title search, an
unknown ID, a series search, and then the tool itself on a title (two requests). It prints only the
SHAPE of the answers (field names, rating sources, value forms, the API's own error texts), never the
key or the URL. Without `--live` it does nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..auth import authorize, load_credentials
from ..config import OmdbConfig
from ..errors import OmdbError
from ..http import urllib_transport
from ..settings import BASE_URL, HTTP_TIMEOUT_SECONDS
from ..tool import OmdbTool
from urllib.parse import urlencode


def _get(credentials, params: dict[str, str]) -> tuple[int, Any]:
    query, headers = authorize(credentials, params)
    status, _, body = urllib_transport(f"{BASE_URL}?{urlencode(query)}", headers, HTTP_TIMEOUT_SECONDS)
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _shape(label: str, status: int, payload: Any) -> None:
    print(f"\n== {label}: HTTP {status}")
    if not isinstance(payload, dict):
        print("   (not a JSON object)")
        return
    print(f"   Response={payload.get('Response')!r} Error={payload.get('Error')!r}")
    print(f"   keys: {sorted(payload)}")
    for field in ("imdbRating", "imdbVotes", "Metascore", "Year", "Type"):
        if field in payload:
            print(f"   {field}={payload[field]!r}")
    for row in payload.get("Ratings") or []:
        print(f"   Ratings: {row.get('Source')!r} -> {row.get('Value')!r}")
    search = payload.get("Search")
    if isinstance(search, list):
        for row in search[:5]:
            print(f"   Search: {row.get('Title')!r} {row.get('Year')!r} {row.get('Type')!r} {row.get('imdbID')!r}")
        print(f"   totalResults={payload.get('totalResults')!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="really call OMDb (6 requests)")
    if not parser.parse_args(argv).live:
        print("Nothing done: pass --live to send 6 real requests.")
        return 0
    credentials = load_credentials()
    for label, params in (
        ("record by IMDb ID", {"i": "tt0111161", "r": "json"}),
        ("title search (movie)", {"s": "The Shawshank Redemption", "type": "movie", "r": "json"}),
        ("unknown IMDb ID", {"i": "tt9999999", "r": "json"}),
        ("title search (series)", {"s": "Breaking Bad", "type": "series", "r": "json"}),
    ):
        _shape(label, *_get(credentials, params))

    tool = OmdbTool(config=OmdbConfig(max_calls_per_turn=2), credentials=credentials)
    try:
        result = tool.run(query="live check", params={"title": "The Shawshank Redemption", "type": "movie"})
    except OmdbError as exc:  # pragma: no cover - the tool does not raise
        print(f"\n== tool: raised {exc.code}")
        return 1
    meta = result["metadata"]["omdb"]
    print(f"\n== tool by title: outcome={result['outcome']} status={meta['status']} imdb_id={meta.get('imdb_id')}")
    for row in meta.get("ratings", []):
        print(f"   {row['source']}: {row['status']} {row['value']} ({row['kind']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
