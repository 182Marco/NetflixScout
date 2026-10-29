"""Terminal print blocks for Wikidata (same box style as `terminal/box.py`).

The content comes from the shared `presenters/wikidata_view.py`; this module only decides the
terminal format.
"""
from __future__ import annotations

from ...wikidata_view import WikidataCallsView
from ..box import print_box


def print_wikidata_calls(view: WikidataCallsView) -> None:
    text = view.labels
    print_box("🕸️", view.title)
    print(f"  {view.source}")

    print()
    if not view.calls:
        print(f"  {text['no_calls']}")
    for call in view.calls:
        print(f"  {text['called']}: {call.text()}")

    print()
    print(f"  {view.status_label}" + (f" — {view.work.name}" if view.work else ""))
    if view.reason:
        print(f"  ⚠️  {view.reason}")
    if view.work:
        if view.work.summary:
            print(f"  {view.work.summary}")
        if view.work.url:
            print(f"  {text['page']}: {view.work.url}")
    for group in view.groups:
        print(f"\n  {group.label}:")
        for item in group.items:
            print(f"    - {item.text}" + (f" — {item.url}" if item.url else ""))
    if view.unavailable:
        print(f"\n  {text['unavailable']}: {'; '.join(view.unavailable)}")
    if view.candidates:
        print(f"\n  {text['candidates']}:")
        for candidate in view.candidates:
            print(f"    - {candidate.text}" + (f" — {candidate.url}" if candidate.url else ""))
        if view.partial_label:
            print(f"  ⚠️  {view.partial_label}")
    if view.license:
        print(f"\n  {text['license']}: {view.license.name} — {view.license.url}")
