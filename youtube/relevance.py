"""Deterministic relevance filter of YouTube search results for one film.
Permissive by design: a result is dropped only on strong evidence, with one reason:

- `no_anchor`: neither the film title (or an alternative title) nor the name of the director
  or of a requested cast member appears in the video title or description;
- `negative_pattern`: the video *title* says reaction, parody, fan made or concept trailer
  (the description is ignored: an interview may mention a "reaction");
- `other_format`: the video *title* declares another format (review, full movie, trailer
  for a non-trailer request; `queries.TITLE_FORMATS`) and has no word of the requested kind
  and does not name the requested person;
- `year_conflict`: a year in parentheses in the video title differs from the film's by more
  than one, and no year in parentheses matches;
- `homonym_risk`: the title anchor is weak (a one-word title such as "Arrival", or only the
  main title before a subtitle) and none of the known year, director, cast or release period
  (trailers, making-of and behind the scenes only) confirms it; with no year and no person
  to check, the result is kept and noted (`homonym_unchecked`);
- `short_video`: the video declares itself a Short (#shorts) and is not longer than a Short
  can be. Never for trailers, never by duration alone (see `settings.MIN_DURATION_SECONDS`).

Every other result is kept, with notes on what could not be confirmed (`kind_unconfirmed`
when no kind word appears: the API also matches metadata we do not see). Results keep the
API order; nothing is scored or reordered. Texts are compared in normalized form only: the
values shown to the user are never changed here.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace

from .models import MIN_SURNAME_CHARS, VideoKind, YoutubeToolInput, is_one_word_title, normalize_text
from .queries import FORMAT_KINDS, KIND_TERMS, TITLE_FORMATS
from .settings import MIN_DURATION_SECONDS, SHORTS_MAX_SECONDS

NEGATIVE_TITLE_PATTERNS = ("reaction", "reactions", "parody", "fan made", "fanmade", "concept trailer")
# Release period that confirms a weak anchor: from one year before to three years after.
RELEASE_WINDOW = (-1, 3)
# Only promotional videos are tied to the release date; interviews and commentaries can
# come out at any time (retrospectives, anniversaries).
RELEASE_PERIOD_KINDS = frozenset({VideoKind.trailer, VideoKind.making_of, VideoKind.behind_the_scenes})

_PAREN_YEAR = re.compile(r"\((\d{4})\)")
_SHORTS_TAG = re.compile(r"#shorts?\b", re.IGNORECASE)
_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_SUBTITLE = re.compile(r"\s*(?::|\s-\s|\s–\s|\s—\s)\s*")


@dataclass(frozen=True)
class Screening:
    kept: bool
    reason: str | None = None
    matched_on: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def _norm(text: str | None) -> str:
    # The search snippet may carry HTML entities ("&#39;"): decoded for comparison only.
    return normalize_text(html.unescape(text or ""))


def _has(haystack: str, needle: str) -> bool:
    return bool(needle) and f" {needle} " in f" {haystack} "


def _main_title(title: str) -> str | None:
    """"Dune: Part Two" -> "Dune"; None when there is no subtitle."""
    parts = _SUBTITLE.split(title, maxsplit=1)
    return parts[0] if len(parts) == 2 and normalize_text(parts[0]) else None


def _director_names(director: str | None) -> list[str]:
    full = normalize_text(director)
    if not full:
        return []
    surname = full.split()[-1]
    return [full, surname] if surname != full and len(surname) >= MIN_SURNAME_CHARS else [full]


def _kind_words(kind: VideoKind) -> list[str]:
    return [normalize_text(term) for term in KIND_TERMS[kind]]


def _other_format(request: YoutubeToolInput, kind: VideoKind, video_title: str) -> bool:
    """The title declares a format incompatible with `kind`, with no word of `kind` and
    without naming the requested person: e.g. "Recensione Dune" for an interview, "Full
    Movie" for a trailer. "Villeneuve reviews the Dune trailer" names the director: kept."""
    declared = [
        name
        for name, words in TITLE_FORMATS.items()
        if FORMAT_KINDS.get(name) is not kind and any(_has(video_title, normalize_text(word)) for word in words)
    ]
    if not declared:
        return False
    if any(_has(video_title, word) for word in _kind_words(kind)):
        return False
    return not any(_has(video_title, name) for person in request.people for name in _director_names(person))


def prescreen(request: YoutubeToolInput, *, title: str | None) -> Screening | None:
    """Early drop on the search snippet, from the video title only: the checks that need no
    description (`negative_pattern`, `year_conflict`). None when the video goes on to `screen`.

    Anchors, homonyms and kind are never decided here: the snippet description is truncated
    by the API (about 160 characters) and often misses the director named further down.
    """
    if any(_has(_norm(title), normalize_text(pattern)) for pattern in NEGATIVE_TITLE_PATTERNS):
        return Screening(kept=False, reason="negative_pattern")
    if request.year is not None:
        years = [int(y) for y in _PAREN_YEAR.findall(html.unescape(title or ""))]
        if years and all(abs(y - request.year) > 1 for y in years):
            return Screening(kept=False, reason="year_conflict")
    return None


def screen(
    request: YoutubeToolInput,
    kind: VideoKind,
    *,
    title: str | None,
    description: str | None,
    published_at: str | None,
) -> Screening:
    """Full check on the most complete texts available: the `/videos` title and full
    description, or the search snippet when `/videos` could not be read."""
    video_title, video_text = _norm(title), _norm(description)
    both = f"{video_title} {video_text}"

    if any(_has(video_title, normalize_text(pattern)) for pattern in NEGATIVE_TITLE_PATTERNS):
        return Screening(kept=False, reason="negative_pattern")
    if _other_format(request, kind, video_title):
        return Screening(kept=False, reason="other_format")

    matched: list[str] = []
    notes: list[str] = []
    film_titles = [request.title, *request.alternative_titles]
    strong = [t for t in film_titles if _has(both, normalize_text(t)) and not is_one_word_title(t)]
    generic = [t for t in film_titles if _has(both, normalize_text(t)) and is_one_word_title(t)]
    mains = [m for t in film_titles if (m := _main_title(t)) and _has(both, normalize_text(m))]
    if strong or generic:
        matched.append("title")
        if not any(_has(video_title, normalize_text(t)) for t in strong + generic):
            notes.append("title_in_description_only")
    elif mains:
        matched.append("main_title")
    if any(_has(both, name) for name in _director_names(request.director)):
        matched.append("director")
    if any(_has(both, name) for person in request.cast for name in _director_names(person)):
        matched.append("cast")
    if not matched:
        return Screening(kept=False, reason="no_anchor")
    if set(matched) <= {"director", "cast"}:
        notes.append("film_title_absent")

    if request.year is not None:
        years = [int(y) for y in _PAREN_YEAR.findall(html.unescape(title or ""))]
        if years and all(abs(y - request.year) > 1 for y in years):
            return Screening(kept=False, reason="year_conflict")
        if any(_has(both, str(request.year + delta)) for delta in (-1, 0, 1)):
            matched.append("year")
        published = _published_year(published_at)
        low, high = RELEASE_WINDOW
        in_window = published is not None and request.year + low <= published <= request.year + high
        if in_window and kind in RELEASE_PERIOD_KINDS:
            matched.append("release_period")

    weak = not strong and (generic or "main_title" in matched)
    if weak:
        confirmations = {"director", "cast", "year", "release_period"} & set(matched)
        if not confirmations:
            if request.year is None and not request.people:
                notes.append("homonym_unchecked")
            else:
                return Screening(kept=False, reason="homonym_risk")

    if not any(_has(both, word) for word in _kind_words(kind)):
        notes.append("kind_unconfirmed")
    return Screening(kept=True, matched_on=tuple(matched), notes=tuple(notes))


def _published_year(published_at: str | None) -> int | None:
    match = re.match(r"^(\d{4})-", published_at or "")
    return int(match.group(1)) if match else None


def parse_duration(value: str | None) -> int | None:
    """ISO 8601 duration of `contentDetails.duration` ("PT1H2M3S") in seconds; None if unknown.

    "P0D" (live streams, premieres not yet aired) is unknown, not zero seconds.
    """
    match = _ISO_DURATION.match(value or "")
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    total = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
    return total or None


def screen_details(
    screening: Screening,
    kind: VideoKind,
    *,
    title: str | None,
    description: str | None,
    duration_seconds: int | None,
) -> Screening:
    """Second pass, after `/videos`: only a self-declared Short is dropped."""
    if not screening.kept:
        return screening
    declared_short = bool(_SHORTS_TAG.search(f"{title or ''} {description or ''}"))
    can_be_short = duration_seconds is None or duration_seconds <= SHORTS_MAX_SECONDS
    if kind is not VideoKind.trailer and declared_short and can_be_short:
        return Screening(kept=False, reason="short_video", matched_on=screening.matched_on)
    notes = list(screening.notes)
    if duration_seconds is None:
        notes.append("duration_unknown")
    elif duration_seconds < MIN_DURATION_SECONDS:
        notes.append("very_short")
    return replace(screening, notes=tuple(notes))


def count_reasons(screenings: list[Screening]) -> dict[str, int]:
    """Dropped results per reason, for the trace (to spot false negatives)."""
    counts: dict[str, int] = {}
    for item in screenings:
        if not item.kept and item.reason:
            counts[item.reason] = counts.get(item.reason, 0) + 1
    return counts
