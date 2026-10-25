"""Decisions about search results: which pages are kept and how sure the match is.

Permissive, like the YouTube filter: a page is dropped only with strong proof (disambiguation
page, no text); everything else is kept and labelled `confirmed` or `to_verify`. Pure functions.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .models import PageHit, PageResult, Subject, WikipediaToolInput, normalize_text
from .settings import MIN_FOLLOW_UP_CHARS

_QUALIFIER = re.compile(r"\s*\(([^()]*)\)\s*$")
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_ARTICLES = ("the ", "a ", "an ", "il ", "lo ", "la ", "i ", "gli ", "le ", "l ", "un ", "uno ", "una ")

# Notes that make a page `to_verify`.
TO_VERIFY_NOTES = frozenset({"title_partial", "title_differs", "year_conflict"})


class Screened(BaseModel):
    page: PageHit
    verification: str
    notes: list[str] = Field(default_factory=list)


def _without_article(text: str) -> str:
    return next((text[len(a):] for a in _ARTICLES if text.startswith(a) and text[len(a):]), text)


def strip_qualifier(title: str) -> tuple[str, str | None]:
    """`("Parasite", "film 2019")` for "Parasite (film 2019)"; the qualifier is None without one."""
    match = _QUALIFIER.search(title)
    return (title[: match.start()], match.group(1)) if match else (title, None)


def match_title(topic: str, title: str) -> str:
    """`exact`, `qualified` (same name, a parenthetical on one side only), `partial` or `differs`.

    The whole titles are compared first, punctuation and qualifiers included ("Kwaidan (film)" is
    "Kwaidan (film)"); then the names without qualifier. Two different qualifiers ("Solaris (novel)"
    and "Solaris (1972 film)") are the same name for different works: `partial`.
    """
    whole_topic, whole_title = _without_article(normalize_text(topic)), _without_article(normalize_text(title))
    if whole_topic and whole_topic == whole_title:
        return "exact"
    topic_base, topic_qualifier = strip_qualifier(topic)
    title_base, title_qualifier = strip_qualifier(title)
    wanted, name = _without_article(normalize_text(topic_base)), _without_article(normalize_text(title_base))
    if not wanted or not name:
        return "differs"
    if name == wanted:
        return "partial" if topic_qualifier and title_qualifier else "qualified"
    wanted_words, name_words = set(wanted.split()), set(name.split())
    return "partial" if wanted_words <= name_words or name_words <= wanted_words else "differs"


def verification(notes: list[str]) -> str:
    return "to_verify" if any(note in TO_VERIFY_NOTES for note in notes) else "confirmed"


def _notes(request: WikipediaToolInput, page: PageHit) -> list[str]:
    match = match_title(request.topic, page.title)
    notes = {"partial": ["title_partial"], "differs": ["title_differs"]}.get(match, [])
    if request.kind is Subject.film and request.year is not None and match in ("exact", "qualified"):
        _, qualifier = strip_qualifier(page.title)
        years = [int(year) for year in _YEAR.findall(qualifier or "")]
        if years and request.year not in years:
            notes = [*notes, "year_conflict"]
    return notes


def _lead_has_phrase(page: PageHit, topic: str) -> bool:
    phrase = _without_article(normalize_text(strip_qualifier(topic)[0]))
    return bool(phrase) and f" {phrase} " in f" {normalize_text(page.extract)} "


def plausible(request: WikipediaToolInput, page: PageHit) -> bool:
    """Whether a page whose title is not the one asked can still be about the subject, judging by its
    lead (already fetched, free): the lead names the subject and, for a film with a given year, the year.
    A page failing this is another thing that happens to share a word (a "Tokyo Anime Award" for "Tokyo!")."""
    if not _lead_has_phrase(page, request.topic):
        return False
    if request.kind is Subject.film and request.year is not None:
        return str(request.year) in page.extract
    return True


def screen_pages(request: WikipediaToolInput, pages: list[PageHit]) -> tuple[list[Screened], dict[str, int]]:
    """Kept pages (confirmed first, search order inside each group) and the count of dropped ones.

    Dropped, with the reason counted: `disambiguation`, `empty_extract`, `not_relevant` (title not the
    one asked and a lead that does not support it, see `plausible`). Kept: `confirmed` (the title is
    the one asked) or `to_verify` (plausible, not certain).
    """
    kept: list[Screened] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for page in sorted(pages, key=lambda hit: hit.index):
        if page.disambiguation:
            drop("disambiguation")
            continue
        if not page.extract.strip():
            drop("empty_extract")
            continue
        if match_title(request.topic, page.title) in ("partial", "differs") and not plausible(request, page):
            drop("not_relevant")
            continue
        notes = _notes(request, page)
        kept.append(Screened(page=page, verification=verification(notes), notes=notes))
    kept.sort(key=lambda row: row.verification != "confirmed")
    return kept, dropped


def lookup_hints(request: WikipediaToolInput, kept: list[Screened], dropped: dict[str, int]) -> list[str]:
    """What the user could add to get surer results; never a value the tool made up."""
    hints = []
    unsure = len(kept) > 1 or any(row.verification == "to_verify" for row in kept) or "disambiguation" in dropped
    if request.kind is Subject.film and request.year is None and unsure:
        hints.append("specify_year")
    if not kept and "disambiguation" in dropped:
        hints.append("add_context")
    return hints


def keywords_mostly_absent(rows: list[dict[str, object]] | None) -> bool:
    """Enough evidence that the edition lacks the detail: at least one distinctive keyword, and at
    least half of them found in no section of the whole article. One missing word among several that
    were found is more likely a different wording than a missing fact."""
    if not rows:
        return False
    absent = sum(row["status"] == "absent" for row in rows)
    return absent > 0 and absent * 2 >= len(rows)


def follow_up_reasons(
    *,
    pages: list[PageResult],
    searched: bool,
    dropped: dict[str, int],
    budget_hit: bool,
    http_left: int,
    context_left: int,
    other_language_untried: bool = False,
    keywords_absent: bool = False,
    unopened_candidates: bool = False,
) -> list[str]:
    """Why another step could add something, only for what a step can still do.

    - `empty`, `ambiguous`, `unverified`: a new search (or another page) needs a free HTTP call
      (`unverified`: candidates were found but none is certain enough to be opened automatically);
    - `more_in_page`: the page has sections not handed out; after a lead it needs the article
      (an HTTP call), once the article is read the sections come from the cache;
    - `omitted_by_budget`: something chosen did not fit the context budget;
    - `keywords_absent`: at least half of the distinctive keywords are in no section of the article read
      (`keywords_mostly_absent`) and the other edition has not been asked yet (a detail that may be
      local); needs a free HTTP call.
    No reason is given when the room (calls or context) to act on it is gone.
    """
    room = context_left >= MIN_FOLLOW_UP_CHARS
    reasons: list[str] = []
    if not pages:
        if searched and http_left > 0:
            # Pages found but none is certain enough to be opened: `unverified`, else nothing usable.
            if unopened_candidates:
                reasons.append("unverified")
            else:
                reasons.append("ambiguous" if dropped.get("disambiguation") else "empty")
        return reasons
    if all(page.verification == "to_verify" for page in pages) and http_left > 0:
        reasons.append("unverified")
    for page in pages:
        if page.outline is None:
            more = http_left > 0 and room
        else:
            more = bool(page.omitted) and room
        if more:
            reasons.append("more_in_page")
            break
    if budget_hit and room:
        reasons.append("omitted_by_budget")
    if keywords_absent and other_language_untried and http_left > 0:
        reasons.append("keywords_absent")
    return reasons
