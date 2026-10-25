"""Requests to the MediaWiki Action API, composed only of constant fragments.

The user's values (topic, page title) are only quoted phrases or `titles` values: quotes,
backslashes, wildcards and control characters are removed from phrases, so they cannot add
search operators. Pure functions: no I/O, no state.

Booleans of the Action API are true when the parameter is present, so they are sent as "1".
`generator=search` with `prop=extracts` and the lead-only `exintro` allows several extracts
in one request; without `exintro` the API returns one extract per request (TextExtracts), so
an article is always opened alone with `article_params`.
"""
from __future__ import annotations

from urllib.parse import quote

from .models import MAX_TOPIC_CHARS, Subject, WikipediaToolInput
from .settings import API_PATH, HOST, MAXLAG_SECONDS, PAGE_PATH

_STRIPPED = '"\\~*'


def phrase(text: str) -> str | None:
    """A quoted phrase with no characters that could act as search operators."""
    kept = "".join(" " if char in _STRIPPED or not char.isprintable() else char for char in text)
    cleaned = " ".join(kept.split())[:MAX_TOPIC_CHARS].strip()
    return f'"{cleaned}"' if cleaned else None


def search_term(request: WikipediaToolInput) -> str | None:
    """The topic as a phrase; a film also gets the word `film` and its year as context words."""
    term = phrase(request.topic)
    if term is None:
        return None
    if request.kind is Subject.film:
        term = f"{term} film"
        if request.year is not None:
            term = f"{term} {request.year}"
    return term


def _base() -> dict[str, str]:
    return {"action": "query", "format": "json", "formatversion": "2", "maxlag": str(MAXLAG_SECONDS)}


def lookup_params(request: WikipediaToolInput, *, max_results: int) -> dict[str, str]:
    """Search plus the lead of every result, the disambiguation flag and the edit time."""
    return {
        **_base(),
        "generator": "search",
        "gsrsearch": search_term(request) or "",
        "gsrlimit": str(max_results),
        "gsrnamespace": "0",
        "prop": "extracts|pageprops|info",
        "exintro": "1",
        "explaintext": "1",
        "exlimit": "max",
        "ppprop": "disambiguation",
        "redirects": "1",
    }


def article_params(title: str) -> dict[str, str]:
    """The whole article of one page as plain text, with `== Heading ==` lines between sections."""
    return {
        **_base(),
        "prop": "extracts|pageprops|info",
        "titles": title,
        "explaintext": "1",
        "exsectionformat": "wiki",
        "ppprop": "disambiguation",
        "redirects": "1",
    }


def api_url(language: str) -> str:
    return f"https://{HOST.format(language=language)}{API_PATH}"


def page_url(language: str, title: str) -> str:
    """The public URL of a page, built from the allowed host and the title (never from the API)."""
    return f"https://{HOST.format(language=language)}{PAGE_PATH}{quote(title.replace(' ', '_'), safe='()!,:;@$*-._~')}"
