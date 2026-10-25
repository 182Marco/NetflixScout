"""Splitting an article into sections and choosing which ones to hand out.

The whole article is downloaded once; what enters the prompt is decided here, by the section
titles the model asked for or by how well each section matches the question, until the turn's
context budget is used. Everything left out is reported (title and size), so a later step can
ask for it. Pure functions: no I/O, no state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Section, normalize_text
from .settings import MAX_OUTLINE_SECTIONS, NON_PROSE_SECTIONS

LEAD_TITLES = {"it": "Introduzione", "en": "Introduction"}
_HEADING = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.MULTILINE)
_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*(?:\s|$)")
# A section that does not fit is cut at a sentence only if at least this much room is left.
MIN_CUT_CHARS = 500
_TERM_MIN_CHARS = 3
_TERM_REPEAT_CAP = 3
_TITLE_WEIGHT = 3
_STOPWORDS = frozenset(
    "che chi come con cosa del della delle dei degli dello nel nella nelle per tra fra una uno questo "
    "questa sono stato stata anni film quale quali parla parlami dimmi dammi vorrei sapere info "
    "the and was for with that this what about who how did his her their from movie tell give some "
    "more all have has are were into over after before when where which".split()
)


def lead_title(language: str) -> str:
    return LEAD_TITLES.get(language, LEAD_TITLES["en"])


def split_sections(text: str, language: str) -> list[Section]:
    """The lead, then one section per `== Heading ==` line (any level), empty ones dropped.

    Headings are kept flat: a section holds the text up to the next heading of any level, with
    its level recorded. Repeated titles get a number so each stays selectable by name.
    """
    matches = list(_HEADING.finditer(text))
    pieces = [(lead_title(language), 1, text[: matches[0].start()] if matches else text)]
    for number, match in enumerate(matches):
        end = matches[number + 1].start() if number + 1 < len(matches) else len(text)
        pieces.append((match.group(2).strip(), len(match.group(1)), text[match.end() : end]))
    seen: dict[str, int] = {}
    sections = []
    for title, level, body in pieces:
        body = body.strip()
        if not body:
            continue
        key = normalize_text(title)
        seen[key] = seen.get(key, 0) + 1
        sections.append(Section(title=title if seen[key] == 1 else f"{title} ({seen[key]})", level=level, text=body))
    return sections


def is_prose(section: Section, language: str) -> bool:
    """The lead and any section that is not a list of links, notes or references."""
    return section.level == 1 or normalize_text(section.title) not in NON_PROSE_SECTIONS


def query_terms(*texts: str) -> list[str]:
    """Distinctive words of the question, in order, without repeats."""
    words = [w for text in texts for w in normalize_text(text).split()]
    return list(dict.fromkeys(w for w in words if len(w) >= _TERM_MIN_CHARS and w not in _STOPWORDS))


def score(section: Section, terms: list[str]) -> int:
    """How well a section matches the terms: title hits weigh more than text hits."""
    title = f" {normalize_text(section.title)} "
    body = f" {normalize_text(section.text)} "
    total = 0
    for term in terms:
        total += _TITLE_WEIGHT * (f" {term} " in title) + min(body.count(f" {term} "), _TERM_REPEAT_CAP)
    return total


def cut_at_sentence(text: str, limit: int) -> str:
    """`text` shortened to at most `limit` characters, at the last full sentence if there is one."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    return (head[: ends[-1]] if ends else head).rstrip()


@dataclass(frozen=True)
class Delivered:
    section: Section
    text: str
    truncated: bool = False


@dataclass(frozen=True)
class Selection:
    delivered: tuple[Delivered, ...]
    # Sections with prose that were not delivered, in article order.
    omitted: tuple[Section, ...]
    # Requested titles that do not exist in the article.
    unknown: tuple[str, ...]
    # True when something chosen did not fit in the budget.
    budget_hit: bool


def select_sections(
    sections: list[Section],
    *,
    depth: str,
    wanted: list[str],
    terms: list[str],
    already: set[str],
    budget: int,
    language: str,
) -> Selection:
    """Which sections to hand out now.

    - `wanted` (titles from an earlier outline): exactly those, whatever they are.
    - `intro`: the lead. `sections`: the sections that match `terms` (the lead if none does).
      `full`: every prose section, the best matching first.
    Sections already delivered in the turn are skipped. Delivery goes in rank order until the
    budget ends; a section that does not fit stops the delivery, except when nothing has been
    delivered yet: then it is cut at a sentence (if enough room is left) so the step is not empty.
    """
    todo = [(i, s) for i, s in enumerate(sections) if normalize_text(s.title) not in already]
    prose = [(i, s) for i, s in todo if is_prose(s, language)]
    wanted_keys = {normalize_text(name) for name in wanted}
    unknown: tuple[str, ...] = ()
    if wanted_keys:
        known = {normalize_text(s.title) for s in sections}
        unknown = tuple(name for name in wanted if normalize_text(name) not in known)
        chosen = [(i, s) for i, s in todo if normalize_text(s.title) in wanted_keys]
    elif depth == "intro":
        chosen = [(i, s) for i, s in prose if s.level == 1][:1]
    else:
        ranked = sorted(((score(s, terms), i, s) for i, s in prose), key=lambda row: (-row[0], row[1]))
        if depth == "sections":
            matching = [(i, s) for points, i, s in ranked if points > 0]
            chosen = matching or [(i, s) for _, i, s in ranked[:1]]
        else:
            chosen = [(i, s) for _, i, s in ranked]

    delivered: list[tuple[int, Delivered]] = []
    left = budget
    budget_hit = False
    for i, section in chosen:
        if section.chars <= left:
            delivered.append((i, Delivered(section, section.text)))
            left -= section.chars
            continue
        budget_hit = True
        if not delivered and left >= MIN_CUT_CHARS:
            delivered.append((i, Delivered(section, cut_at_sentence(section.text, left), truncated=True)))
        break
    # A section delivered cut short still has text to give: it stays among the omitted ones.
    taken = {i for i, d in delivered if not d.truncated}
    omitted = tuple(s for i, s in prose if i not in taken)
    return Selection(tuple(d for _, d in sorted(delivered, key=lambda row: row[0])), omitted, unknown, budget_hit)


def outline(sections: list[Section], delivered: set[str], language: str) -> list[dict[str, object]]:
    """Title, level, size and `delivered` of every prose section (the model's table of contents)."""
    rows = [
        {"title": s.title, "level": s.level, "chars": s.chars, "delivered": normalize_text(s.title) in delivered}
        for s in sections
        if is_prose(s, language)
    ]
    return rows[:MAX_OUTLINE_SECTIONS]
