"""Channel-neutral view of an `omdb_calls` step, shared by the terminal and web presenters.

Holds the labels (it/en/de) and the `OmdbCallsView` both channels show: the same status, scores
(each with what it measures: audience or critics, and "not available" when OMDb has no value) and
alternatives; only the format differs. Reads only `step.data`; imports nothing but `turn`: no
`omdb` package, no tool logic. OMDb is named as the source by the view, never left to the model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

from .calls_view import CallView, call_views

LABELS = {
    "it": {
        "title": "OMDB",
        "source": "Fonte: OMDb API (uso non commerciale; non affiliata a IMDb)",
        "called": "Chiamato",
        "no_calls": "Nessuna chiamata a OMDb in questo turno.",
        "imdb": "IMDb",
        "metascore": "Metascore",
        "rotten_tomatoes": "Rotten Tomatoes",
        "audience": "pubblico",
        "critics": "critica",
        "not_available": "non disponibile",
        "unparsed": "valore non leggibile",
        "votes": "voti",
        "candidates": "Opere con titolo simile",
        "ok": "Punteggi trovati",
        "empty": "Nessun punteggio disponibile per questo titolo",
        "ambiguous": "Più opere corrispondono: nessun punteggio assegnato",
        "unverified": "Titolo non verificato: nessun punteggio assegnato",
        "not_found": "Titolo non trovato",
        "error": "Errore",
    },
    "en": {
        "title": "OMDB",
        "source": "Source: OMDb API (non-commercial use; not affiliated with IMDb)",
        "called": "Called",
        "no_calls": "No OMDb call in this turn.",
        "imdb": "IMDb",
        "metascore": "Metascore",
        "rotten_tomatoes": "Rotten Tomatoes",
        "audience": "audience",
        "critics": "critics",
        "not_available": "not available",
        "unparsed": "unreadable value",
        "votes": "votes",
        "candidates": "Works with a similar title",
        "ok": "Scores found",
        "empty": "No score available for this title",
        "ambiguous": "Several works match: no score assigned",
        "unverified": "Title not verified: no score assigned",
        "not_found": "Title not found",
        "error": "Error",
    },
    "de": {
        "title": "OMDB",
        "source": "Quelle: OMDb API (nicht kommerzielle Nutzung; nicht mit IMDb verbunden)",
        "called": "Aufgerufen",
        "no_calls": "Kein OMDb-Aufruf in diesem Durchgang.",
        "imdb": "IMDb",
        "metascore": "Metascore",
        "rotten_tomatoes": "Rotten Tomatoes",
        "audience": "Publikum",
        "critics": "Kritik",
        "not_available": "nicht verfügbar",
        "unparsed": "Wert nicht lesbar",
        "votes": "Stimmen",
        "candidates": "Werke mit ähnlichem Titel",
        "ok": "Bewertungen gefunden",
        "empty": "Keine Bewertung für diesen Titel verfügbar",
        "ambiguous": "Mehrere Werke passen: keine Bewertung zugeordnet",
        "unverified": "Titel nicht bestätigt: keine Bewertung zugeordnet",
        "not_found": "Titel nicht gefunden",
        "error": "Fehler",
    },
}

# Codes of errors; an unknown code is shown as it is.
CODE_LABELS = {
    "it": {
        "not_configured": "chiave OMDb non configurata",
        "unauthorized": "chiave API rifiutata",
        "quota_exceeded": "limite giornaliero raggiunto",
        "turn_limit": "limite di chiamate per turno",
        "timeout": "tempo scaduto",
        "network_error": "errore di rete",
        "http_error": "risposta non valida",
        "api_error": "richiesta rifiutata",
        "id_mismatch": "opera restituita diversa da quella identificata",
        "invalid_request": "richiesta non valida",
        "no_ratings": "nessun punteggio disponibile",
        "too_many_results": "troppi risultati: indica anno o titolo completo",
    },
    "en": {
        "not_configured": "OMDb key not configured",
        "unauthorized": "API key rejected",
        "quota_exceeded": "daily limit reached",
        "turn_limit": "per-turn call limit",
        "timeout": "timed out",
        "network_error": "network error",
        "http_error": "invalid answer",
        "api_error": "request refused",
        "id_mismatch": "returned work differs from the one identified",
        "invalid_request": "invalid request",
        "no_ratings": "no score available",
        "too_many_results": "too many results: give the year or the full title",
    },
    "de": {
        "not_configured": "OMDb-Schlüssel nicht konfiguriert",
        "unauthorized": "API-Schlüssel abgelehnt",
        "quota_exceeded": "Tageslimit erreicht",
        "turn_limit": "Aufruflimit pro Durchgang",
        "timeout": "Zeitüberschreitung",
        "network_error": "Netzwerkfehler",
        "http_error": "ungültige Antwort",
        "api_error": "Anfrage abgelehnt",
        "id_mismatch": "zurückgegebenes Werk weicht vom identifizierten ab",
        "invalid_request": "ungültige Anfrage",
        "no_ratings": "keine Bewertung verfügbar",
        "too_many_results": "zu viele Treffer: Jahr oder vollständigen Titel angeben",
    },
}

# Same control-character removal as the other views: API text is shown, never obeyed.
_WHITESPACE_CONTROLS = {"\t", "\n", "\r", "\x0b", "\x0c", "\x85"}


def printable(value: Any) -> str:
    """Display copy of a text without C0/C1 control characters; printable text is unchanged."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    out = []
    for char in text:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            if char in _WHITESPACE_CONTROLS:
                out.append(" ")
            continue
        out.append(char)
    return "".join(out)


def labels(language: str | None) -> dict[str, str]:
    return LABELS[label_language(language)]


def code_label(code: Any, language: str | None) -> str:
    if not isinstance(code, str):
        return "?"
    return CODE_LABELS[label_language(language)].get(code, printable(code))


class RatingView(BaseModel):
    source_label: str
    kind_label: str
    # Already formatted ("8.8/10", "82/100", "94%") or the "not available" text.
    value: str
    available: bool
    votes: str | None = None


class CandidateView(BaseModel):
    text: str


class OmdbCallsView(BaseModel):
    title: str
    source: str
    labels: dict[str, str]
    calls: list[CallView] = Field(default_factory=list)
    status: str
    status_label: str
    reason: str | None = None
    work: str | None = None
    imdb_id: str | None = None
    ratings: list[RatingView] = Field(default_factory=list)
    candidates: list[CandidateView] = Field(default_factory=list)


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw or [] if isinstance(row, dict)] if isinstance(raw, list) else []


def _https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _formatted(source: str, value: Any) -> str:
    number = _number(value)
    return {"imdb": f"{number}/10", "metascore": f"{number}/100", "rotten_tomatoes": f"{number}%"}.get(source, number)


def _rating_view(row: dict[str, Any], text: dict[str, str]) -> RatingView:
    source = row.get("source") if isinstance(row.get("source"), str) else "?"
    status = row.get("status")
    value = row.get("value")
    available = status == "available" and isinstance(value, (int, float)) and not isinstance(value, bool)
    votes = row.get("votes")
    return RatingView(
        source_label=text.get(source, printable(source)),
        kind_label=text.get(row.get("kind"), "") if isinstance(row.get("kind"), str) else "",
        value=_formatted(source, value) if available else text["unparsed" if status == "unparsed" else "not_available"],
        available=available,
        votes=f"{votes:,} {text['votes']}".replace(",", ".") if available and isinstance(votes, int) and votes > 0 else None,
    )


def omdb_calls_view(step: TraceStep, language: str | None) -> OmdbCallsView:
    data = step.data
    text = labels(language)
    status = data.get("status") if data.get("status") in text else "error"
    raw_calls = data.get("calls")
    title, year = printable(data.get("title")), printable(data.get("year"))
    reason = data.get("reason")
    candidates = []
    for row in _rows(data.get("candidates")):
        line = f"{printable(row.get('title'))} ({printable(row.get('year'))})"
        kind = printable(row.get("type"))
        candidates.append(CandidateView(text=f"{line} — {kind}, {printable(row.get('imdb_id'))}" if kind else line))
    return OmdbCallsView(
        title=text["title"],
        source=text["source"],
        labels=text,
        calls=call_views(raw_calls),
        status=status,
        status_label=text[status],
        reason=code_label(reason, language) if reason else None,
        work=(f"{title} ({year})" if year else title) if title else None,
        imdb_id=printable(data.get("imdb_id")) or None,
        ratings=[_rating_view(row, text) for row in _rows(data.get("ratings"))],
        candidates=candidates,
    )
