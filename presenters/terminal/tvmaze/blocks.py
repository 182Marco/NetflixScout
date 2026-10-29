"""Terminal print blocks for TVmaze (same box style as `terminal/box.py`).

The content comes from the shared `presenters/tvmaze_view.py`; this module only decides the
terminal format.
"""
from __future__ import annotations

from ...tvmaze_view import TvmazeCallsView
from ..box import print_box


def print_tvmaze_calls(view: TvmazeCallsView) -> None:
    text = view.labels
    print_box("📺", view.title)
    print(f"  {view.source}")

    print()
    if not view.calls:
        print(f"  {text['no_calls']}")
    for call in view.calls:
        print(f"  {text['called']}: {call.text()}")

    print()
    print(f"  {view.status_label}" + (f" — {view.show.name}" if view.show else ""))
    if view.reason:
        print(f"  ⚠️  {view.reason}")
    if view.show:
        if view.show.summary:
            print(f"  {view.show.summary}")
        if view.show.url:
            print(f"  {text['page']}: {view.show.url}")
    if view.read:
        print(f"  {text['read']}: {', '.join(view.read)}")
    if view.candidates:
        print(f"\n  {text['candidates']}:")
        for candidate in view.candidates:
            print(f"    - {candidate.text}")
    if view.license:
        print(f"\n  {text['license']}: {view.license.name} — {view.license.url}")
