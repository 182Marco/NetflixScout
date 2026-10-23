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

from .models import (
    MAX_TITLE_CHARS,
    MIN_SURNAME_CHARS,
    VideoKind,
    YoutubeToolInput,
    is_one_word_title,
    normalize_text,
)
from .settings import SEARCH_FETCH_FACTOR, SEARCH_FETCH_MAX

KIND_TERMS: dict[VideoKind, tuple[str, ...]] = {
    VideoKind.trailer: ("trailer", "teaser", '"trailer ufficiale"'),
    VideoKind.director_interview: ("interview", "intervista", "director", "regista"),
    VideoKind.cast_interview: ("interview", "intervista", "cast", '"red carpet"', "junket", '"press conference"'),
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

# Formats a video title can declare, as a closed set (not a blacklist): a title declaring
# one of them is a different kind of video only when it also has no word of the requested
# kind and does not name the requested person (`relevance.screen`, reason `other_format`).
# Trailers are a format and a kind: a trailer title is compatible with a trailer request.
TITLE_FORMATS: dict[str, tuple[str, ...]] = {
    "review": ("review", "reviews", "recensione", "recensioni", "reseña", "critique"),
    "full_movie": ("full movie", "full film", "film completo", "película completa", "film complet"),
    "trailer": ("trailer", "trailers", "teaser"),
}
FORMAT_KINDS: dict[str, VideoKind] = {"trailer": VideoKind.trailer}

# The only exclusions sent to the API (see the module docstring).
EXCLUDED_TERMS = ("-reaction", "-parody")


def phrase(text: str) -> str | None:
    """A quoted phrase with no characters that could act as operators."""
    kept = "".join(" " if char in '"|' or not char.isprintable() else char for char in text)
    cleaned = " ".join(kept.split())[:MAX_TITLE_CHARS].strip()
    return f'"{cleaned}"' if cleaned else None


def person_group(name: str | None) -> str | None:
    """`"Spike Jonze"|"Jonze"`: the full name or the surname (when long enough to be
    distinctive, as in the relevance filter); None when no name is given."""
    full = phrase(name or "")
    if full is None:
        return None
    words = full.strip('"').split()
    # Same rule as the relevance filter, on the normalized surname ("Joon-ho" -> "ho": too short).
    normalized = normalize_text(words[-1]).split()
    distinctive = len(words) > 1 and bool(normalized) and len(normalized[-1]) >= MIN_SURNAME_CHARS
    surname = phrase(words[-1]) if distinctive else None
    return "|".join([full, surname] if surname else [full])


def people_group(names: list[str]) -> str | None:
    """Several people in one OR group (each as in `person_group`); None when nobody is known."""
    groups = [group for name in names if (group := person_group(name))]
    return "|".join(dict.fromkeys(part for group in groups for part in group.split("|"))) or None


# The people an interview kind is about: their names are alternatives to the kind words
# ("Denis Villeneuve on Dune", "Cillian Murphy talks Oppenheimer" have no kind word).
_INTERVIEWED = {
    VideoKind.director_interview: lambda request: [request.director] if request.director else [],
    VideoKind.cast_interview: lambda request: list(request.cast),
}


def build_q(request: YoutubeToolInput, kind: VideoKind) -> str:
    """Titles in OR, then kind terms in OR, then the exclusions.

    A one-word title ("Her", "Barbie") matches unrelated videos, so when every title is a
    single word and a person of the film is known (director or cast), the people become a
    required (AND) group: `"Her" "Spike Jonze"|"Jonze" "making of"|...`. Without a known
    person nothing is added.
    """
    all_titles = (request.title, *request.alternative_titles)
    titles = [phrase(title) for title in all_titles]
    title_group = "|".join(dict.fromkeys(title for title in titles if title))
    terms = list(KIND_TERMS[kind])
    people = people_group(request.people)
    required_people = people is not None and all(is_one_word_title(title) for title in all_titles)
    interviewed = _INTERVIEWED.get(kind, lambda request: [])(request)
    if interviewed and not required_people:
        terms.extend(dict.fromkeys(group for name in interviewed if (group := phrase(name))))
    groups = [title_group, people] if required_people else [title_group]
    return " ".join([*groups, "|".join(terms), *EXCLUDED_TERMS])


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
