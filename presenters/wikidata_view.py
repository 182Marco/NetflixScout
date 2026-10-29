"""Channel-neutral view of a `wikidata_calls` step, shared by the terminal and web presenters.

Holds the labels (it/en/de) and the `WikidataCallsView` both channels show: the source with its licence
(CC0, linked), every request sent, the work identified with the link to its Wikidata page, the works it is
related to (each with its link), the alternatives when a title is ambiguous, the status and what could not
be read; only the format differs. Reads only `step.data`; imports nothing but `turn`: no `wikidata`
package, no tool logic. Wikidata is named as the source by the view, never left to the model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

from .calls_view import CallView, call_views

LABELS = {
    "it": {
        "title": "WIKIDATA",
        "source": "Fonte: Wikidata, dati riformulati dall'assistente, licenza {license}",
        "called": "Chiamato",
        "no_calls": "Nessuna chiamata a Wikidata in questo turno.",
        "license": "Licenza",
        "page": "Pagina",
        "work": "Opera",
        "director": "regia",
        "candidates": "Opere con titolo simile",
        "ok": "Opera identificata",
        "no_relations": "Opera identificata: nessuna relazione registrata",
        "ambiguous": "Più opere corrispondono: nessun dato assegnato",
        "unverified": "Titolo non verificato: nessun dato assegnato",
        "not_found": "Opera non trovata",
        "error": "Errore",
        "unavailable": "Non letto",
        "source_group": "Basata su",
        "derived": "Opere basate su questa",
        "previous": "Precedente nella serie",
        "next": "Successiva nella serie",
        "franchise": "Franchise o serie",
        "more": "altre non mostrate",
        "partial": "Elenco parziale: possono esistere altre opere con questo titolo",
    },
    "en": {
        "title": "WIKIDATA",
        "source": "Source: Wikidata, data reworded by the assistant, {license} licence",
        "called": "Called",
        "no_calls": "No Wikidata call in this turn.",
        "license": "Licence",
        "page": "Page",
        "work": "Work",
        "director": "director",
        "candidates": "Works with a similar title",
        "ok": "Work identified",
        "no_relations": "Work identified: no relation recorded",
        "ambiguous": "Several works match: no data assigned",
        "unverified": "Title not verified: no data assigned",
        "not_found": "Work not found",
        "error": "Error",
        "unavailable": "Not read",
        "source_group": "Based on",
        "derived": "Works based on this one",
        "previous": "Previous in the series",
        "next": "Next in the series",
        "franchise": "Franchise or series",
        "more": "more not shown",
        "partial": "Partial list: other works with this title may exist",
    },
    "de": {
        "title": "WIKIDATA",
        "source": "Quelle: Wikidata, Daten vom Assistenten umformuliert, Lizenz {license}",
        "called": "Aufgerufen",
        "no_calls": "Kein Wikidata-Aufruf in diesem Durchgang.",
        "license": "Lizenz",
        "page": "Seite",
        "work": "Werk",
        "director": "Regie",
        "candidates": "Werke mit ähnlichem Titel",
        "ok": "Werk identifiziert",
        "no_relations": "Werk identifiziert: keine Beziehung erfasst",
        "ambiguous": "Mehrere Werke passen: keine Daten zugeordnet",
        "unverified": "Titel nicht bestätigt: keine Daten zugeordnet",
        "not_found": "Werk nicht gefunden",
        "error": "Fehler",
        "unavailable": "Nicht gelesen",
        "source_group": "Basiert auf",
        "derived": "Werke, die darauf basieren",
        "previous": "Vorheriges in der Reihe",
        "next": "Nächstes in der Reihe",
        "franchise": "Franchise oder Reihe",
        "more": "weitere nicht gezeigt",
        "partial": "Teilliste: es kann weitere Werke mit diesem Titel geben",
    },
}

KIND_LABELS = {
    "it": {"film": "film", "series": "serie", "literary": "opera letteraria", "comics": "fumetto", "game": "videogioco"},
    "en": {"film": "film", "series": "series", "literary": "literary work", "comics": "comic", "game": "video game"},
    "de": {"film": "Film", "series": "Serie", "literary": "literarisches Werk", "comics": "Comic", "game": "Videospiel"},
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
        "not_found": "opera non trovata",
        "unverified": "nessuna opera con questo titolo esatto",
        "ambiguous": "più opere con questo titolo",
        "no_relations": "nessuna relazione registrata",
    },
    "en": {
        "rate_limited": "too many requests, try again shortly",
        "turn_limit": "per-turn call limit",
        "timeout": "timed out",
        "network_error": "network error",
        "http_error": "invalid answer",
        "response_too_large": "answer too large to read",
        "invalid_request": "invalid request",
        "not_found": "work not found",
        "unverified": "no work with this exact title",
        "ambiguous": "several works with this title",
        "no_relations": "no relation recorded",
    },
    "de": {
        "rate_limited": "zu viele Anfragen, gleich erneut versuchen",
        "turn_limit": "Aufruflimit pro Durchgang",
        "timeout": "Zeitüberschreitung",
        "network_error": "Netzwerkfehler",
        "http_error": "ungültige Antwort",
        "response_too_large": "Antwort zu groß zum Lesen",
        "invalid_request": "ungültige Anfrage",
        "not_found": "Werk nicht gefunden",
        "unverified": "kein Werk mit genau diesem Titel",
        "ambiguous": "mehrere Werke mit diesem Titel",
        "no_relations": "keine Beziehung erfasst",
    },
}

GROUP_ORDER = (("sources", "source_group"), ("derived", "derived"), ("previous", "previous"), ("next", "next"))

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


class ItemView(BaseModel):
    """A work with its link to the Wikidata page (None when the step has no such link)."""

    text: str
    url: str | None = None


class GroupView(BaseModel):
    label: str
    items: list[ItemView] = Field(default_factory=list)


class WorkView(BaseModel):
    name: str
    url: str | None = None
    summary: str


class LicenseView(BaseModel):
    name: str
    url: str


class WikidataCallsView(BaseModel):
    title: str
    # Source line with the licence name filled in.
    source: str
    labels: dict[str, str]
    calls: list[CallView] = Field(default_factory=list)
    status: str
    status_label: str
    reason: str | None = None
    operation: str | None = None
    work: WorkView | None = None
    groups: list[GroupView] = Field(default_factory=list)
    candidates: list[ItemView] = Field(default_factory=list)
    # True when the alternatives are not all of them (some are not listed, or the search was cut).
    partial: bool = False
    partial_label: str | None = None
    unavailable: list[str] = Field(default_factory=list)
    license: LicenseView | None = None


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _link(value: Any, host: str) -> str | None:
    return value if isinstance(value, str) and value.startswith(f"https://{host}/") else None


def _wikidata_link(value: Any) -> str | None:
    return _link(value, "www.wikidata.org")


def _item_text(row: dict[str, Any], language: str | None, extra: str = "") -> str:
    kinds = KIND_LABELS[label_language(language)]
    year = printable(row.get("year"))
    kind = kinds.get(row.get("kind"), "") if isinstance(row.get("kind"), str) else ""
    details = ", ".join(part for part in (year, kind, extra) if part)
    name = printable(row.get("title"))
    return f"{name} ({details})" if details else name


def _item(row: dict[str, Any], language: str | None, extra: str = "") -> ItemView:
    return ItemView(text=_item_text(row, language, extra), url=_wikidata_link(row.get("url")))


def _ids(row: dict[str, Any]) -> str:
    imdb, tmdb = printable(row.get("imdb_id")), printable(row.get("tmdb_id"))
    return ", ".join(part for part in (f"IMDb {imdb}" if imdb else "", f"TMDb {tmdb}" if tmdb else "") if part)


def _work_view(raw: Any, language: str | None) -> WorkView | None:
    if not isinstance(raw, dict) or not raw.get("title"):
        return None
    kinds = KIND_LABELS[label_language(language)]
    kind = kinds.get(raw.get("kind"), "") if isinstance(raw.get("kind"), str) else ""
    summary = ", ".join(part for part in (kind, _ids(raw)) if part)
    year = printable(raw.get("year"))
    name = printable(raw.get("title"))
    return WorkView(name=f"{name} ({year})" if year else name, url=_wikidata_link(raw.get("url")), summary=summary)


def wikidata_calls_view(step: TraceStep, language: str | None) -> WikidataCallsView:
    data = step.data
    text = labels(language)
    status = data.get("status") if data.get("status") in text else "error"
    reason = data.get("reason")
    raw_license = data.get("license") if isinstance(data.get("license"), dict) else {}
    license_url = _link(raw_license.get("url"), "creativecommons.org")
    license_name = printable(raw_license.get("name"))
    license_view = LicenseView(name=license_name, url=license_url) if license_name and license_url else None

    relations = data.get("relations") if isinstance(data.get("relations"), dict) else {}
    groups = []
    for key, label_key in GROUP_ORDER:
        items = [_item(row, language) for row in _rows(relations.get(key))]
        if items:
            groups.append(GroupView(label=text[label_key], items=items))
    for franchise in _rows(data.get("franchises")):
        members = [_item(row, language) for row in _rows(franchise.get("works"))]
        if members:
            omitted = franchise.get("omitted")
            if isinstance(omitted, int) and omitted > 0:
                members.append(ItemView(text=f"+{omitted} {text['more']}"))
            groups.append(GroupView(label=f"{text['franchise']}: {printable(franchise.get('title'))}", items=members))

    candidates = [_item(row, language, ", ".join(part for part in (
        f"{text['director']} {', '.join(printable(name) for name in row.get('directors') or [])}" if row.get("directors") else "",
        _ids(row),
    ) if part)) for row in _rows(data.get("candidates"))]
    omitted = data.get("candidates_omitted")
    if candidates and isinstance(omitted, int) and not isinstance(omitted, bool) and omitted > 0:
        candidates.append(ItemView(text=f"+{omitted} {text['more']}"))
    partial = bool(candidates) and (data.get("incomplete") is True or (isinstance(omitted, int) and omitted > 0))
    unavailable = data.get("unavailable") if isinstance(data.get("unavailable"), dict) else {}
    return WikidataCallsView(
        title=text["title"],
        source=text["source"].format(license=license_name or "CC0 1.0"),
        labels=text,
        calls=call_views(data.get("calls")),
        status=status,
        status_label=text[status],
        reason=code_label(reason, language) if reason and status not in ("ok",) else None,
        operation=printable(data.get("operation")) or None,
        work=_work_view(data.get("work"), language),
        groups=groups,
        candidates=candidates,
        partial=partial,
        partial_label=text["partial"] if partial else None,
        unavailable=[f"{printable(part)}: {code_label(code, language)}" for part, code in sorted(unavailable.items())],
        license=license_view,
    )
