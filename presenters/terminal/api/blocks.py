"""Terminal print blocks for TMDb (same box style as `terminal/box.py`)."""
from __future__ import annotations

from ...api_view import TMDB_NOTICE, TmdbCallsView
from ..box import print_box


def print_tmdb_calls(view: TmdbCallsView) -> None:
    print_box("🎞️", f"{view.title} — {len(view.calls)}")
    if not view.calls:
        print(f"\n  {view.empty_message}")
    for url in view.calls:
        print(f"  {view.called_label}: {url}")
    for attribution in view.attributions:
        print(f"\n  ℹ️  {attribution.text}")


def print_tmdb_notice() -> None:
    """Startup notice required by the TMDb API Terms of Use, in English as written there."""
    print(f"ℹ️  {TMDB_NOTICE}\n")
