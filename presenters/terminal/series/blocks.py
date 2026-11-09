"""Terminal print block for the TV-series search (box style of `terminal/box.py`); content from the shared `presenters/series_view.py`."""
from __future__ import annotations

from ...series_view import SeriesView
from ..box import print_box


def print_series(view: SeriesView) -> None:
    print_box("📺", view.title)
    print(f"  {view.source}")
    head = f"{view.search_label} — {view.status_label}" + (f" ({view.elapsed})" if view.elapsed else "")
    print(f"  {head}")
    if view.engine_label:
        print(f"  {view.engine_label}")
    if view.reason:
        print(f"  ⚠️  {view.reason}")
    for r in view.results:
        extra = f" — {r.note}" if r.note else ""
        print(f"  {r.n}. {r.label}{extra}")
        if r.url:
            print(f"     {r.url}")
    if view.notes:
        print(f"\n  {view.notes_title}:")
        for note in view.notes:
            print(f"    - {note}")
    print(f"\n  {view.license_label}: {view.license_name} — {view.license_url}")
