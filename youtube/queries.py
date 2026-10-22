"""Search queries for each video kind, composed only of constant fragments.

The user's values (title, alternative titles, director) are only quoted phrases: quotes,
`|` and control characters are removed, so they cannot add operators. Operators of the
`q` parameter (developers.google.com/youtube/v3/docs/search/list): `|` is OR, `-` is NOT.
Assumed precedence, to confirm with the live smoke test: OR binds adjacent terms, so
`"A"|"B" x|y` reads (A or B) and (x or y).

Kind terms are alternatives, never all required: a valid interview titled "Villeneuve on
directing Dune" has no "interview" in it. The year is not a search term (it would drop
videos that do not write it); it is checked by the relevance filter. Only two exclusions
are sent; every other one is applied to the video title by the filter, where it cannot
remove a valid video because of its description.
"""
from __future__ import annotations

from .models import MAX_TITLE_CHARS, VideoKind, YoutubeToolInput
from .settings import SEARCH_FETCH_FACTOR, SEARCH_FETCH_MAX

KIND_TERMS: dict[VideoKind, tuple[str, ...]] = {
    VideoKind.trailer: ("trailer", "teaser", '"trailer ufficiale"'),
    VideoKind.director_interview: ("interview", "intervista", "director", "regista"),
    VideoKind.making_of: ('"making of"', '"making-of"', '"come è stato girato"'),
    VideoKind.behind_the_scenes: ('"behind the scenes"', '"dietro le quinte"', "backstage", "featurette", '"on set"'),
    VideoKind.author_commentary: (
        "commentary",
        '"director explains"',
        "explains",
        '"commento del regista"',
        "spiega",
    ),
}

# The only exclusions sent to the API (see the module docstring).
EXCLUDED_TERMS = ("-reaction", "-parody")


def phrase(text: str) -> str | None:
    """A quoted phrase with no characters that could act as operators."""
    kept = "".join(" " if char in '"|' or not char.isprintable() else char for char in text)
    cleaned = " ".join(kept.split())[:MAX_TITLE_CHARS].strip()
    return f'"{cleaned}"' if cleaned else None


def build_q(request: YoutubeToolInput, kind: VideoKind) -> str:
    titles = [phrase(title) for title in (request.title, *request.alternative_titles)]
    title_group = "|".join(dict.fromkeys(title for title in titles if title))
    terms = list(KIND_TERMS[kind])
    if kind is VideoKind.director_interview and request.director and phrase(request.director):
        # The director's name as an alternative: "Denis Villeneuve on Dune" has no kind word.
        terms.append(phrase(request.director))
    return " ".join([title_group, "|".join(terms), *EXCLUDED_TERMS])


def build_search_params(request: YoutubeToolInput, kind: VideoKind, *, max_results: int) -> dict[str, str]:
    """`search.list` parameters for one kind. No `regionCode` and no `relevanceLanguage`:
    international videos in English must not be filtered out or pushed down."""
    return {
        "part": "snippet",
        "type": "video",
        "order": "relevance",
        "safeSearch": "moderate",
        "maxResults": str(min(max_results * SEARCH_FETCH_FACTOR, SEARCH_FETCH_MAX)),
        "q": build_q(request, kind),
    }
