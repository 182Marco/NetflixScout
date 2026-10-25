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
_PREFIX_MIN_CHARS = 4
_TERM_REPEAT_CAP = 3
_TITLE_WEIGHT = 3
_STOPWORDS = frozenset(
    "che chi come con cosa del della delle dei degli dello nel nella nelle per tra fra una uno questo "
    "questa sono stato stata anni film quale quali parla parlami dimmi dammi vorrei sapere info "
    "the and was for with that this what about who how did his her their from movie tell give some "
    "more all have has are were into over after before when where which".split()
)


def clean_extract(text: str) -> str:
    """The extract without control characters (newlines and tabs stay): it is third-party text
    that goes into the prompt, so nothing that could drive a terminal or hide text is kept."""
    return "".join(
        char for char in text.replace("\r\n", "\n").replace("\r", "\n")
        if char in "\n\t" or (char.isprintable() or char == " ")
    )


# Words that say what kind of thing is asked, not which thing: found (or not) in almost any article,
# so their absence proves nothing. They still rank sections; they are not evidence in `keyword_report`.
GENERIC_KEYWORDS = frozenset(
    (
        "episode episodes segment segments short shorts actor actors actress actresses cast film films movie movies "
        "story stories plot character characters director directors order release released change changes difference "
        "differences narrative narratives role roles part parts title titles year years information detail details "
        "list main principal major one two three four five six seven eight nine ten first second third "
        "protagonist protagonists continuation continuations sequel sequels prequel prequels connected connection "
        "connections related relation relations relationship relationships link links linked original source "
        "sources literary adaptation adaptations work works summary background history context theme themes "
        "structure structures order ordering total number members "
        "episodio episodi segmento segmenti cortometraggio cortometraggi attore attori attrice attrici storia storie "
        "trama personaggio personaggi regista registi ordine uscita cambiamento cambiamenti differenza differenze "
        "ruolo ruoli parte parti titolo titoli anno anni informazioni dettagli elenco principale principali "
        "uno due tre quattro cinque sei sette otto nove dieci primo secondo terzo "
        "protagonista protagonisti continuazione continuazioni sequel prequel collegato collegati collegamento "
        "collegamenti correlato correlati relazione relazioni rapporto rapporti originale originali fonte fonti "
        "letteraria letterarie letterario adattamento adattamenti opera opere riassunto contesto storia tema temi "
        "struttura strutture numero totale membri"
    ).split()
)


def is_distinctive(keyword: str) -> bool:
    """A keyword names something specific (a name, a title, a rare term): at least one of its words is
    neither generic nor a function word."""
    return any(
        (len(word) >= _TERM_MIN_CHARS or any(char.isdigit() for char in word))
        and word not in GENERIC_KEYWORDS
        and word not in _STOPWORDS
        for word in normalize_text(keyword).split()
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


def question_terms(query: str, topic: str) -> list[str]:
    """The distinctive words of the question without those of the topic: the topic names the page,
    it does not tell which of its sections the question is about."""
    subject = set(query_terms(topic))
    return [term for term in query_terms(query) if term not in subject]


def _stem(word: str) -> str:
    """A crude root so that "episodes"/"episode", "directed"/"directs"/"direct" meet. Only for matching."""
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 4 and word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _stem_text(text: str) -> str:
    return " ".join(_stem(word) for word in text.split())


def count_term(text: str, term: str) -> int:
    """Occurrences of `term` in `text` (both normalized). A word matches itself, its inflections
    ("episode" finds "episodes", "direct" finds "directed") and, from four letters, longer words that
    start with it; a phrase matches its words in order, inflected or not."""
    if not term:
        return 0
    if " " in term:
        return f" {_stem_text(text)} ".count(f" {_stem_text(term)} ")
    root = _stem(term)
    prefix = len(term) >= _PREFIX_MIN_CHARS
    return sum(
        1
        for word in text.split()
        if word == term or _stem(word) == root or (prefix and word.startswith(term))
    )


def scoring_terms(keywords: list[str], query: str, topic: str) -> list[str]:
    """What the sections are ranked on: the planner's keywords (in the language of the edition), then
    the distinctive words of the question itself, normalized and without repeats."""
    own = [normalize_text(keyword) for keyword in keywords]
    return list(dict.fromkeys(term for term in [*own, *question_terms(query, topic)] if term))


# A question about differences, an adaptation or the story needs the plot of the page, whose title shares
# no word with the question and would otherwise rank after sections that merely repeat the film's name.
PLOT_TRIGGERS = frozenset(
    {"adaptation", "adaptations", "adapted", "novel", "book", "differences", "difference", "compare",
     "comparison", "plot", "story", "romanzo", "libro", "adattamento", "differenze", "trama", "confronta"}
)
PLOT_TITLES = frozenset({"plot", "plot summary", "synopsis", "summary", "story", "trama", "sinossi"})
_PLOT_BONUS = 100


def wants_plot(terms: list[str]) -> bool:
    return any(term in PLOT_TRIGGERS for term in terms)


def score(section: Section, terms: list[str]) -> int:
    """How well a section matches the terms: title hits weigh more than text hits."""
    title = normalize_text(section.title)
    body = normalize_text(section.text)
    total = 0
    for term in terms:
        total += _TITLE_WEIGHT * (count_term(title, term) > 0) + min(count_term(body, term), _TERM_REPEAT_CAP)
    return total


def keyword_report(
    keywords: list[str], sections: list[Section], delivered: set[str], *, whole_article: bool
) -> list[dict[str, object]]:
    """Where each distinctive keyword stands (generic ones prove nothing and are left out), so a later
    step knows what to read and what the edition lacks.

    `read`: in a section already handed out; `unread`: only in other sections (listed, at most
    three); `absent`: the words are in no section of the article (the idea may still be there in
    other words); with only the lead known (`whole_article` false) the last two are `not_in_lead`,
    since the rest of the page was not seen.
    """
    rows: list[dict[str, object]] = []
    for keyword in (k for k in keywords if is_distinctive(k)):
        term = normalize_text(keyword)
        found = [s for s in sections if count_term(normalize_text(f"{s.title} {s.text}"), term)]
        if any(normalize_text(s.title) in delivered for s in found):
            rows.append({"keyword": keyword, "status": "read", "sections": []})
        elif not whole_article:
            rows.append({"keyword": keyword, "status": "not_in_lead", "sections": []})
        elif found:
            rows.append({"keyword": keyword, "status": "unread", "sections": [s.title for s in found[:3]]})
        else:
            rows.append({"keyword": keyword, "status": "absent", "sections": []})
    return rows


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
        bonus = wants_plot(terms)

        def points(section: Section) -> int:
            plot = bonus and section.level > 1 and normalize_text(section.title) in PLOT_TITLES
            return score(section, terms) + (_PLOT_BONUS if plot else 0)

        ranked = sorted(((points(s), i, s) for i, s in prose), key=lambda row: (-row[0], row[1]))
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
