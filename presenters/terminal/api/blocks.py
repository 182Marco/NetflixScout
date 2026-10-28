"""Terminal print blocks for TMDb (same box style as `terminal/box.py`)."""
from __future__ import annotations

from ...api_view import TmdbCallsView
from ..box import print_box


def print_tmdb_calls(view: TmdbCallsView) -> None:
    print_box("🎞️", f"{view.title} — {len(view.calls)}")
    if not view.calls:
        print(f"\n  {view.empty_message}")
    for call in view.calls:
        print(f"  {view.called_label}: {call.text()}")
    for attribution in view.attributions:
        print(f"\n  ℹ️  {attribution.text}")

