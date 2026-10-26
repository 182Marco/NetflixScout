"""What the final RAG chunks are known to satisfy, so the answer never overstates it.

Each constraint the query parser extracted gets one status per final chunk:

- `verified`: structured metadata confirms it (genres list, release year);
- `probable`: every key term of a required plot element appears in the plot summary;
- `not_verifiable`: the data says nothing reliable (endings, tone, emotions, absent terms);
- `contradicted`: metadata or an explicit phrase in the plot says the opposite.

Nationality ("Japanese") is where a film was made, not something its plot shows: a Japanese
character does not make a Japanese film. Chunks carry no country, but the catalog genres
sometimes name it ("Japanese Movies"): that is `verified`; otherwise `not_verifiable`. Hard exclusions name films, people or franchises: they are
checked on title and cast, not on the plot.

Nothing here filters chunks: a weak signal never removes a film. Absence of a word never
proves a requirement, and a negated requirement ("non-tragic ending") is never `probable`.
"""
from __future__ import annotations

import re
from typing import Any

from .models import QuerySignals
from .vectorstore import has_excluded_genre

VERIFIED = "verified"
PROBABLE = "probable"
NOT_VERIFIABLE = "not_verifiable"
CONTRADICTED = "contradicted"

_DECADE = re.compile(r"\b(1[89]\d0|20[0-2]0)s\b")
_NEGATIONS = frozenset({"no", "not", "non", "without", "never"})
# Endings, tone and feelings are not stated reliably by plot summaries.
_SUBJECTIVE = frozenset({
    "ending", "endings", "finale", "tone", "mood", "atmosphere", "emotional", "emotionally",
    "moving", "delicate", "touching", "feel", "feeling", "uplifting", "happy", "sad", "dark",
})
# Production origin: the chunks have no country metadata.
_NATIONALITIES = frozenset({
    "american", "british", "english", "french", "italian", "german", "spanish", "japanese",
    "chinese", "korean", "indian", "russian", "soviet", "mexican", "brazilian", "swedish",
    "danish", "norwegian", "polish", "iranian", "turkish", "greek", "canadian", "australian",
    "argentine", "hungarian", "czech", "dutch", "belgian", "hollywood", "bollywood",
})
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "with", "and", "or", "in", "on", "at", "to", "for", "by", "from",
    "about", "film", "films", "movie", "movies", "story", "plot", "setting", "set",
})


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _content_terms(signal: str) -> list[str]:
    return [word for word in _words(signal) if len(word) >= 4 and word not in _STOPWORDS]


def _term_found(term: str, tokens: set[str]) -> bool:
    # Light stemming for long words only: "shipwreck" ~ "shipwrecked", "japanese" ~ "japan".
    if term in tokens:
        return True
    return len(term) >= 7 and any(token.startswith(term[:-3]) for token in tokens)


def _label(chunk: dict[str, Any]) -> str:
    return f"{chunk.get('title')} ({chunk.get('release_year') or '?'})"


def _genres(chunk: dict[str, Any]) -> str:
    return str(chunk.get("genres") or "").strip()


def _excluded_genre(genre: str, chunk: dict[str, Any]) -> dict[str, Any]:
    if not _genres(chunk):
        return {"status": NOT_VERIFIABLE, "evidence": "nessun genere nel catalogo"}
    if has_excluded_genre(chunk, [genre]):
        return {"status": CONTRADICTED, "evidence": f"generi: {_genres(chunk)}"}
    return {"status": VERIFIED, "evidence": f"generi: {_genres(chunk)}"}


def _requested_genre(genre: str, chunk: dict[str, Any]) -> dict[str, Any]:
    if not _genres(chunk):
        return {"status": NOT_VERIFIABLE, "evidence": "nessun genere nel catalogo"}
    if has_excluded_genre(chunk, [genre]):  # same whole-word match, used positively
        return {"status": VERIFIED, "evidence": f"generi: {_genres(chunk)}"}
    return {"status": CONTRADICTED, "evidence": f"generi del catalogo: {_genres(chunk)}"}


def _decade(start: int, chunk: dict[str, Any]) -> dict[str, Any]:
    year = str(chunk.get("release_year") or "")
    if not year.isdigit():
        return {"status": NOT_VERIFIABLE, "evidence": "anno assente"}
    status = VERIFIED if start <= int(year) <= start + 9 else CONTRADICTED
    return {"status": status, "evidence": f"anno {year}"}


def _plot_require(signal: str, chunk: dict[str, Any]) -> dict[str, Any]:
    terms = _content_terms(signal)
    nationalities = set(_words(signal)) & _NATIONALITIES
    if nationalities:
        genre_words = set(_words(_genres(chunk)))
        if nationalities & genre_words:
            return {"status": VERIFIED, "evidence": f"generi: {_genres(chunk)}"}
        return {"status": NOT_VERIFIABLE, "evidence": "paese di produzione assente nei metadati"}
    if not terms or any(term in _SUBJECTIVE for term in terms):
        return {"status": NOT_VERIFIABLE, "evidence": None}
    tokens = set(_words(f"{chunk.get('title') or ''} {chunk.get('testo') or ''}"))
    found = [term for term in terms if _term_found(term, tokens)]
    if len(found) == len(terms):
        return {"status": PROBABLE, "evidence": f"termini nella trama: {', '.join(found)}"}
    return {"status": NOT_VERIFIABLE, "evidence": None}


def _plot_avoid(signal: str, chunk: dict[str, Any]) -> dict[str, Any]:
    text = f"{chunk.get('title') or ''} {chunk.get('testo') or ''}".lower()
    phrase = " ".join(word for word in _words(signal) if word not in _NEGATIONS)
    if phrase and re.search(rf"\b{re.escape(phrase)}\b", text):
        return {"status": CONTRADICTED, "evidence": f"la trama contiene «{phrase}»"}
    return {"status": NOT_VERIFIABLE, "evidence": None}


def _title_exclusion(name: str, chunk: dict[str, Any]) -> dict[str, Any]:
    wanted = " ".join(_words(name))
    for field in ("title", "cast"):
        if wanted and re.search(rf"\b{re.escape(wanted)}\b", " ".join(_words(str(chunk.get(field) or "")))):
            return {"status": CONTRADICTED, "evidence": f"{field}: {chunk.get(field)}"}
    checked = "titolo e cast" if str(chunk.get("cast") or "").strip() else "titolo"
    return {"status": VERIFIED, "evidence": f"assente da {checked}"}


def _check(kind: str, constraint: str, rule, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "constraint": constraint,
        "type": kind,
        "results": {_label(chunk): rule(chunk) for chunk in chunks},
    }


def constraint_report(signals: QuerySignals, final_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-constraint, per-title statuses for the final chunks; {} when nothing was asked."""
    checks: list[dict[str, Any]] = []
    for genre in signals.excluded_genres:
        checks.append(_check("excluded_genre", genre, lambda c, g=genre: _excluded_genre(g, c), final_chunks))
    for genre in signals.genres:
        checks.append(_check("genre", genre, lambda c, g=genre: _requested_genre(g, c), final_chunks))
    # A positive signal that only repeats a genre ("comedy" next to genre "Comedy") would get a
    # second, conflicting status (real case 20): the genre check on metadata covers it.
    genre_names = {" ".join(_words(genre)) for genre in [*signals.genres, *signals.excluded_genres]}
    for signal in signals.positive_signals:
        if " ".join(_words(signal)) in genre_names:
            continue
        words = set(_words(signal))
        if decade := _DECADE.search(signal.lower()):
            start = int(decade.group(1))
            checks.append(_check("decade", signal, lambda c, s=start: _decade(s, c), final_chunks))
        elif words & _NEGATIONS:
            # "non-tragic ending" is a requirement to avoid something: never proven by presence.
            checks.append(_check("plot_avoid", signal, lambda c, s=signal: _plot_avoid(s, c), final_chunks))
        else:
            checks.append(_check("plot_require", signal, lambda c, s=signal: _plot_require(s, c), final_chunks))
    for signal in signals.negative_signals:
        checks.append(_check("plot_avoid", signal, lambda c, s=signal: _plot_avoid(s, c), final_chunks))
    for name in signals.hard_exclusions:
        checks.append(_check("title_exclusion", name, lambda c, n=name: _title_exclusion(n, c), final_chunks))
    return {"checks": checks} if checks else {}


# Constraints the catalog metadata decides on its own (never plot wording or tone).
_METADATA_KINDS = frozenset({"genre", "excluded_genre", "decade", "title_exclusion"})


def demote_contradicted(signals: QuerySignals, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable reorder: films the metadata contradicts go after those it does not.

    The cross-encoder reads genre and decade as soft text and ranks a plot-similar film of
    the wrong genre or decade above a compliant one. The metadata states these facts, so a
    chunk with fewer `contradicted` genre, excluded-genre, decade or title-exclusion checks
    comes first; ties keep the reranker order. Nothing is removed and no weak signal counts.
    """
    checks = [c for c in constraint_report(signals, ranked).get("checks", [])
              if c["type"] in _METADATA_KINDS]
    if not checks:
        return ranked

    def violations(chunk: dict[str, Any]) -> int:
        label = _label(chunk)
        return sum(1 for c in checks if c["results"][label]["status"] == CONTRADICTED)

    return sorted(ranked, key=violations)  # sorted() is stable


# How the final answer may speak about each status (Italian: the answer is in Italian).
_SUMMARY_LABELS = {
    VERIFIED: "verificato",
    PROBABLE: "probabile (solo un indizio nella trama, non una conferma)",
    NOT_VERIFIABLE: "non verificabile (non dire né che lo rispetta né che non lo rispetta, non dedurlo)",
    CONTRADICTED: "contraddetto (dillo esplicitamente)",
}


def constraint_summary(report: dict[str, Any]) -> dict[str, list[str]]:
    """Per film, one line per constraint: what the answer may claim, ready for the prompt."""
    summary: dict[str, list[str]] = {}
    for check in report.get("checks", []):
        for title, result in check["results"].items():
            line = f"{check['constraint']}: {_SUMMARY_LABELS[result['status']]}"
            if result.get("evidence"):
                line += f" — {result['evidence']}"
            summary.setdefault(title, []).append(line)
    return summary
