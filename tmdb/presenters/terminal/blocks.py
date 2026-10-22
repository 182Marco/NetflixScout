"""Terminal print blocks for TMDb (same box style as `presenters/terminal/blocks.py`)."""
from __future__ import annotations

from ..view import TMDB_NOTICE, TmdbCallsView


def print_tmdb_calls(view: TmdbCallsView) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    header = f"{view.title} — {len(view.calls)}"
    print(f"║  🎞️  {header.upper():<62}║")
    print("╚" + "═" * 68 + "╝")
    if not view.calls:
        print(f"\n  {view.empty_message}")
    for url in view.calls:
        print(f"  {view.called_label}: {url}")
    for attribution in view.attributions:
        print(f"\n  ℹ️  {attribution.text}")


def print_tmdb_notice() -> None:
    """Startup notice required by the TMDb API Terms of Use, in English as written there."""
    print(f"ℹ️  {TMDB_NOTICE}\n")
