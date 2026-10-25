"""Optional live check of TMDb behaviours the docs do not spell out (3 real HTTP calls).

    python -m tool.tmdb.harness.live_smoke --live

Checks, on Interstellar (157336):
1. `watch/providers` is accepted as an `append_to_response` value;
2. `include_video_language` works for movie videos;
3. appended reviews with `language=it-IT` (empty → the tool falls back to English).
Not a pytest test; it needs `VUE_APP_TMDB_API_KEY` in `.env`. Only masked URLs are printed.
"""
from __future__ import annotations

import argparse

from ..auth import load_credentials
from ..budget import CallBudget
from ..cache import TtlCache
from ..config import TmdbConfig
from ..context import TmdbContext
from ..cooldown import Cooldown
from ..endpoints import details
from ..http import get_json, urllib_transport

MOVIE_ID = 157336


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Live TMDb smoke check (3 HTTP calls).")
    parser.add_argument("--live", action="store_true", required=True, help="Required: this run calls the real API.")
    parser.parse_args(argv)

    ctx = TmdbContext(
        config=TmdbConfig(max_results=5, max_calls_per_turn=3, cache_ttl=0),
        credentials=load_credentials(),
        cache=TtlCache(0),
        cooldown=Cooldown(),
        budget=CallBudget(3),
        transport=urllib_transport,
        api_language="it-IT",
    )
    providers = get_json(ctx, details("movie", MOVIE_ID, language="it-IT", appends=("watch/providers",)))
    videos = get_json(
        ctx,
        details("movie", MOVIE_ID, language="it-IT", appends=("videos",), extra={"include_video_language": "it,en"}),
    )
    reviews = get_json(ctx, details("movie", MOVIE_ID, language="it-IT", appends=("reviews",)))

    languages = sorted({v.get("iso_639_1") for v in (videos.get("videos") or {}).get("results") or []})
    print(f"1. watch/providers appended: {'watch/providers' in providers}")
    print(f"2. video languages with include_video_language=it,en: {languages}")
    print(f"3. it-IT appended reviews: {len((reviews.get('reviews') or {}).get('results') or [])}")
    for url in ctx.recorder.calls:
        print(f"   Called: {url}")


if __name__ == "__main__":
    main()
