"""Terminal print blocks for OMDb (same box style as `terminal/box.py`).

The content comes from the shared `presenters/omdb_view.py`; this module only decides the
terminal format.
"""
from __future__ import annotations

from ...omdb_view import OmdbCallsView
from ..box import print_box


def print_omdb_calls(view: OmdbCallsView) -> None:
    text = view.labels
    print_box("⭐", view.title)
    print(f"  {view.source}")

    print()
    if not view.calls:
        print(f"  {text['no_calls']}")
    for call in view.calls:
        print(f"  {text['called']}: {call.text()}")

    print()
    work = f" — {view.work}" if view.work else ""
    print(f"  {view.status_label}{work}" + (f" ({view.imdb_id})" if view.imdb_id else ""))
    if view.reason:
        print(f"  ⚠️  {view.reason}")
    for rating in view.ratings:
        kind = f" [{rating.kind_label}]" if rating.kind_label else ""
        votes = f" ({rating.votes})" if rating.votes else ""
        print(f"  ★ {rating.source_label}{kind}: {rating.value}{votes}")
    if view.candidates:
        print(f"\n  {text['candidates']}:")
        for candidate in view.candidates:
            print(f"    - {candidate.text}")
