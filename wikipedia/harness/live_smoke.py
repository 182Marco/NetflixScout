"""Optional live check of the assumptions the tool makes about the MediaWiki API (3 requests).

    python -m wikipedia.harness.live_smoke --live

It confirms what the documentation does not state (see `wikipedia/queries.py`):
1. `generator=search` together with `prop=extracts|pageprops|info&exintro` returns, in one
   request, the lead of every result with an `index` to order them;
2. an article opened with `exsectionformat=wiki` carries `== Heading ==` lines that
   `split_sections` can use, and no `exchars` cap applies;
3. a name shared by several pages gives disambiguation pages flagged in `pageprops`.
It prints counts, titles and section sizes only, never extracts (third-party text). No key is
needed; the requests carry the tool's User-Agent and `maxlag`. Not a pytest test.
"""
from __future__ import annotations

import argparse
from typing import Any

from ..budget import TurnState
from ..http import HttpSession, RateLimitPause, TtlCache, get_json, urllib_transport
from ..models import WikipediaToolInput
from ..queries import article_params, lookup_params
from ..sections import split_sections
from ..tool import parse_pages

MAX_TITLES_SHOWN = 6


def _clean(text: object) -> str:
    return "".join(char if char.isprintable() else " " for char in str(text))[:90]


def _requests() -> list[tuple[str, str, dict[str, str]]]:
    """(label, language, parameters) of the three requests."""
    person = WikipediaToolInput(query="x", topic="Park Chan-wook", kind="person")
    homonym = WikipediaToolInput(query="x", topic="Parasite", kind="film")
    return [
        ("lookup of a person", "it", lookup_params(person, max_results=3)),
        ("whole article", "it", article_params("Park Chan-wook")),
        ("lookup of a homonym title", "en", lookup_params(homonym, max_results=5)),
    ]


def _show(label: str, language: str, answer: dict[str, Any]) -> None:
    pages = parse_pages(answer, language)
    print(f"\n{label} ({language}): {len(pages)} pages")
    for page in pages[:MAX_TITLES_SHOWN]:
        flags = ["disambiguation"] if page.disambiguation else []
        print(f"  - [{page.index}] {_clean(page.title)}: {len(page.extract)} chars {' '.join(flags)}".rstrip())
    if label == "whole article" and pages:
        sections = split_sections(pages[0].extract, language)
        print(f"  sections found: {len(sections)}")
        for section in sections[:12]:
            print(f"    {section.level} {_clean(section.title)}: {section.chars} chars")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Live Wikipedia smoke check (3 requests).")
    parser.add_argument("--live", action="store_true", required=True, help="Required: this run calls the real API.")
    parser.parse_args(argv)

    session = HttpSession(
        transport=urllib_transport, state=TurnState(), max_calls=3, cache=TtlCache(0), pause=RateLimitPause()
    )
    for label, language, params in _requests():
        _show(label, language, get_json(session, language, params))
    for call in session.calls:
        print(f"\ncalled: {call}")


if __name__ == "__main__":
    main()
