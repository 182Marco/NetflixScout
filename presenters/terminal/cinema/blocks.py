"""Terminal print block for the local cinema database (same box style as `terminal/box.py`).

The content comes from the shared `presenters/cinema_view.py`; this module only decides the terminal format.
"""
from __future__ import annotations

import textwrap

from ...cinema_view import CinemaCallsView
from ..box import print_box

_SQL_WIDTH = 64


def print_cinema_calls(view: CinemaCallsView) -> None:
    text = view.labels
    print_box("🗄️", view.title)
    print(f"  {view.source}")
    print(f"  {view.no_network} · {view.local}")
    print()
    head = view.status_label + (f" — {view.subject.name}" if view.subject else "")
    print(f"  {view.operation_label + ': ' if view.operation_label else ''}{head}")
    if view.reason:
        print(f"  ⚠️  {view.reason}")
    if view.subject:
        if view.subject.summary:
            print(f"  {view.subject.summary}")
        for link in view.subject.links:
            print(f"  {link.label}: {link.url}")
    if view.counts:
        print(f"  {view.counts}")
    if view.candidates:
        print(f"\n  {text['candidates']}:")
        for candidate in view.candidates:
            print(f"    - {candidate}")
    if view.notes:
        print(f"\n  {text['notes']}:")
        for note in view.notes:
            print(f"    - {note}")
    if view.queries:
        print(f"\n  {text['sql_executed']}:")
        for index, query in enumerate(view.queries, start=1):
            lines = textwrap.wrap(query.display_sql, width=_SQL_WIDTH) or [query.display_sql]
            print(f"  🧾 #{index} {lines[0]}")
            for line in lines[1:]:
                print(f"       {line}")
            if query.detail:
                print(f"       ({query.detail})")
    print(f"\n  {text['license']}: " + "; ".join(f"{lic.name} — {lic.url}" for lic in view.licenses))
