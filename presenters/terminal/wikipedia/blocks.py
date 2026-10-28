"""Terminal print blocks for Wikipedia (same box style as `terminal/box.py`).

The content comes from the shared `presenters/wikipedia_view.py`; this module only decides the
terminal format. Every text in the view went through `printable`, so a page title cannot drive
the terminal; the trace, the metadata and the LLM prompt keep the API values unchanged.
"""
from __future__ import annotations

from ...wikipedia_view import PageView, WikipediaCallsView
from ..box import print_box


def print_wikipedia_calls(view: WikipediaCallsView) -> None:
    text = view.labels
    print_box("📖", view.title)
    print(f"  {view.source}")

    print()
    if not view.calls:
        print(f"  {text['none']}")
    for call in view.calls:
        print(f"  {text['called']}: {call.text()}")

    for search in view.searches:
        print(f"\n  🔎 {text['search']} [{search.language}]: {search.q}")
        print(f"     {search.summary}")
        if search.error:
            print(f"     ⚠️  {text['error']}: {search.error}")
    for opened in view.opens:
        print(f"\n  📄 {text['open']} [{opened.language}]: {opened.title} — {opened.result}")
        if opened.error:
            print(f"     ⚠️  {text['error']}: {opened.error}")

    print()
    if not view.pages:
        print(f"  {text['no_pages']}")
    confirmed = [page for page in view.pages if page.verification != "to_verify"]
    to_verify = [page for page in view.pages if page.verification == "to_verify"]
    for page in confirmed:
        _print_page(page, text)
    if to_verify:
        print(f"  ❔ {text['to_verify']}")
    for page in to_verify:
        _print_page(page, text)

    if view.license:
        print(f"\n  {text['license']}: {view.license.name} — {view.license.url}")
    for hint in view.hints:
        print(f"\n  💡 {hint}")


def _print_page(page: PageView, text: dict[str, str]) -> None:
    suffix = f" ({page.chars})" if page.chars else ""
    print(f"  📖 [{page.language}] {page.title}{suffix}")
    print(f"     {page.url}")
    if page.sections:
        print(f"     {text['sections']}: {', '.join(page.sections)}")
    if page.omitted:
        print(f"     {page.omitted} {text['omitted']}")
    if page.notes:
        print(f"     {text['notes']}: {', '.join(page.notes)}")
