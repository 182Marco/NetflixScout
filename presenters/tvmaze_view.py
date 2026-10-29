"""Channel-neutral view of a `tvmaze_calls` step, shared by the terminal and web presenters.

Holds the labels (it/en/de) and the `TvmazeCallsView` both channels show: the source with its licence
(CC BY-SA 4.0, linked), the link to the TVmaze page of the series identified, what was read, the
status and the alternatives; only the format differs. Reads only `step.data`; imports nothing but
`turn`: no `tvmaze` package, no tool logic. TVmaze is named as the source by the view, never left to
the model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

from .calls_view import CallView, call_views

LABELS = {
    "it": {
        "title": "TVMAZE",
        "source": "Fonte: TVmaze, dati riformulati dall'assistente, licenza {license}",
        "called": "Chiamato",
        "no_calls": "Nessuna chiamata a TVmaze in questo turno.",
        "page": "Pagina della serie",
        "license": "Licenza",
        "read": "Letto",
        "info": "scheda",
        "cast": "cast",
        "seasons": "stagioni",
        "episodes": "episodi",
        "next": "prossimo episodio",
        "candidates": "Serie con titolo simile",
        "ok": "Serie trovata",
        "ambiguous": "Più serie corrispondono: nessun dato assegnato",
        "unverified": "Titolo non verificato: nessun dato assegnato",
        "not_found": "Serie non trovata",
        "error": "Errore",
    },
    "en": {
        "title": "TVMAZE",
        "source": "Source: TVmaze, data reworded by the assistant, {license} licence",
        "called": "Called",
        "no_calls": "No TVmaze call in this turn.",
        "page": "Series page",
        "license": "Licence",
        "read": "Read",
        "info": "card",
        "cast": "cast",
        "seasons": "seasons",
        "episodes": "episodes",
        "next": "next episode",
        "candidates": "Series with a similar title",
        "ok": "Series found",
        "ambiguous": "Several series match: no data assigned",
        "unverified": "Title not verified: no data assigned",
        "not_found": "Series not found",
        "error": "Error",
    },
    "de": {
        "title": "TVMAZE",
        "source": "Quelle: TVmaze, Daten vom Assistenten umformuliert, Lizenz {license}",
        "called": "Aufgerufen",
        "no_calls": "Kein TVmaze-Aufruf in diesem Durchgang.",
        "page": "Serienseite",
        "license": "Lizenz",
        "read": "Gelesen",
        "info": "Steckbrief",
        "cast": "Besetzung",
        "seasons": "Staffeln",
        "episodes": "Folgen",
        "next": "nächste Folge",
        "candidates": "Serien mit ähnlichem Titel",
        "ok": "Serie gefunden",
        "ambiguous": "Mehrere Serien passen: keine Daten zugeordnet",
        "unverified": "Titel nicht bestätigt: keine Daten zugeordnet",
        "not_found": "Serie nicht gefunden",
        "error": "Fehler",
    },
}

# Codes of errors; an unknown code is shown as it is.
CODE_LABELS = {
    "it": {
        "rate_limited": "troppe richieste, riprova tra poco",
        "turn_limit": "limite di chiamate per turno",
        "timeout": "tempo scaduto",
        "network_error": "errore di rete",
        "http_error": "risposta non valida",
        "response_too_large": "risposta troppo grande da leggere",
        "invalid_request": "richiesta non valida",
        "not_found": "serie non trovata",
        "unverified": "nessuna serie con questo titolo esatto",
        "ambiguous": "più serie con questo titolo",
    },
    "en": {
        "rate_limited": "too many requests, try again shortly",
        "turn_limit": "per-turn call limit",
        "timeout": "timed out",
        "network_error": "network error",
        "http_error": "invalid answer",
        "response_too_large": "answer too large to read",
        "invalid_request": "invalid request",
        "not_found": "series not found",
        "unverified": "no series with this exact title",
        "ambiguous": "several series with this title",
    },
    "de": {
        "rate_limited": "zu viele Anfragen, gleich erneut versuchen",
        "turn_limit": "Aufruflimit pro Durchgang",
        "timeout": "Zeitüberschreitung",
        "network_error": "Netzwerkfehler",
        "http_error": "ungültige Antwort",
        "response_too_large": "Antwort zu groß zum Lesen",
        "invalid_request": "ungültige Anfrage",
        "not_found": "Serie nicht gefunden",
        "unverified": "keine Serie mit genau diesem Titel",
        "ambiguous": "mehrere Serien mit diesem Titel",
    },
}

FACET_ORDER = ("info", "cast", "seasons", "episodes", "next")

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


class ShowView(BaseModel):
    name: str
    # Public page on tvmaze.com, or None when the step has no such link.
    url: str | None = None
    summary: str


class LicenseView(BaseModel):
    name: str
    url: str


class CandidateView(BaseModel):
    text: str


class TvmazeCallsView(BaseModel):
    title: str
    # Source line with the licence name filled in.
    source: str
    labels: dict[str, str]
    calls: list[CallView] = Field(default_factory=list)
    status: str
    status_label: str
    reason: str | None = None
    show: ShowView | None = None
    read: list[str] = Field(default_factory=list)
    license: LicenseView | None = None
    candidates: list[CandidateView] = Field(default_factory=list)


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _link(value: Any, host: str) -> str | None:
    return value if isinstance(value, str) and value.startswith(f"https://{host}/") else None


def _show_view(raw: Any) -> ShowView | None:
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    parts = [printable(raw.get("status")), printable(raw.get("network"))]
    year = printable(raw.get("premiered"))[:4]
    name = printable(raw.get("name"))
    summary = ", ".join(part for part in parts if part)
    return ShowView(
        name=f"{name} ({year})" if year else name,
        url=_link(raw.get("url"), "www.tvmaze.com"),
        summary=summary,
    )


def tvmaze_calls_view(step: TraceStep, language: str | None) -> TvmazeCallsView:
    data = step.data
    text = labels(language)
    status = data.get("status") if data.get("status") in text else "error"
    reason = data.get("reason")
    raw_license = data.get("license") if isinstance(data.get("license"), dict) else {}
    license_url = _link(raw_license.get("url"), "creativecommons.org")
    license_name = printable(raw_license.get("name"))
    license_view = LicenseView(name=license_name, url=license_url) if license_name and license_url else None
    facets = data.get("facets") if isinstance(data.get("facets"), list) else []
    show = _show_view(data.get("show"))
    candidates = []
    for row in _rows(data.get("candidates")):
        year, channel = printable(row.get("year")), printable(row.get("channel"))
        details = ", ".join(part for part in (year, channel) if part)
        candidates.append(CandidateView(text=f"{printable(row.get('name'))} ({details})" if details else printable(row.get("name"))))
    return TvmazeCallsView(
        title=text["title"],
        source=text["source"].format(license=license_name or "CC BY-SA 4.0"),
        labels=text,
        calls=call_views(data.get("calls")),
        status=status,
        status_label=text[status],
        reason=code_label(reason, language) if reason and status != "ok" else None,
        show=show,
        read=[text[name] for name in FACET_ORDER if name in facets and show is not None],
        license=license_view,
        candidates=candidates,
    )
