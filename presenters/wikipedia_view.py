"""Channel-neutral view of a `wikipedia_calls` step, shared by the terminal and web presenters.

Holds the labels (it/en), the display copy of third-party text (`printable`: no C0/C1 control
characters; the trace and the LLM prompt keep the API values) and the `WikipediaCallsView` both
channels show: the calls, the searches and article openings, the pages read (title, language,
public URL, sections read and left out) and the credit the licence requires (page links, licence
and its link, a note that the text was reworked). Reads only `step.data`; imports nothing but
`turn`: no `wikipedia` package, no tool logic. Only `https://` URLs are shown.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep

# Whitespace controls become a space so words do not merge; every other control is removed.
_WHITESPACE_CONTROLS = {"\t", "\n", "\r", "\x0b", "\x0c", "\x85"}
DEFAULT_LICENSE = "CC BY-SA 4.0"

LABELS = {
    "it": {
        "title": "WIKIPEDIA",
        "page": "pagina",
        "pages": "pagine",
        "source": "Fonte: Wikipedia, testo riformulato e abbreviato, licenza {license}",
        "called": "Chiamato",
        "none": "Nessuna chiamata a Wikipedia in questo passo: dati già in cache.",
        "search": "Ricerca",
        "open": "Pagina aperta",
        "received": "ricevuti",
        "kept": "tenuti",
        "dropped": "scartati",
        "error": "errore",
        "notes": "note",
        "sections": "Sezioni lette",
        "omitted": "sezioni non lette",
        "license": "Licenza",
        "to_verify": "Da verificare (pagina non confermata):",
        "no_pages": "Nessuna pagina da mostrare.",
        "specify_year": "Indica l'anno del film per scegliere la pagina giusta.",
        "add_context": "Aggiungi un dettaglio (ruolo, nazionalità, anno) per distinguere le pagine omonime.",
    },
    "en": {
        "title": "WIKIPEDIA",
        "page": "page",
        "pages": "pages",
        "source": "Source: Wikipedia, text reworded and shortened, {license} licence",
        "called": "Called",
        "none": "No Wikipedia call in this step: data already cached.",
        "search": "Search",
        "open": "Page opened",
        "received": "received",
        "kept": "kept",
        "dropped": "dropped",
        "error": "error",
        "notes": "notes",
        "sections": "Sections read",
        "omitted": "sections not read",
        "license": "Licence",
        "to_verify": "To verify (page not confirmed):",
        "no_pages": "No page to show.",
        "specify_year": "Give the film's year to pick the right page.",
        "add_context": "Add a detail (role, nationality, year) to tell same-name pages apart.",
    },
}

# Codes of notes, drops and errors; an unknown code is shown as it is.
CODE_LABELS = {
    "it": {
        "disambiguation": "pagina di disambiguazione",
        "empty_extract": "senza testo",
        "title_partial": "titolo solo in parte uguale",
        "title_differs": "titolo diverso da quello cercato",
        "year_conflict": "anno diverso",
        "rate_limited": "troppe richieste, pausa breve",
        "timeout": "tempo scaduto",
        "network_error": "errore di rete",
        "http_error": "risposta non valida",
        "response_too_large": "pagina troppo grande da leggere",
        "turn_limit": "limite di chiamate per turno",
        "not_found": "pagina non trovata",
        "ambiguous": "pagina di disambiguazione",
        "ok": "letta",
    },
    "en": {
        "disambiguation": "disambiguation page",
        "empty_extract": "no text",
        "title_partial": "title only partly the same",
        "title_differs": "title differs from the one searched",
        "year_conflict": "different year",
        "rate_limited": "too many requests, short pause",
        "timeout": "timed out",
        "network_error": "network error",
        "http_error": "invalid answer",
        "response_too_large": "page too large to read",
        "turn_limit": "per-turn call limit",
        "not_found": "page not found",
        "ambiguous": "disambiguation page",
        "ok": "read",
    },
}


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
    return LABELS["it"] if language == "it" else LABELS["en"]


def code_label(code: Any, language: str | None) -> str:
    if not isinstance(code, str):
        return "?"
    return CODE_LABELS["it" if language == "it" else "en"].get(code, printable(code))


class SearchView(BaseModel):
    language: str
    q: str
    summary: str
    error: str | None = None


class OpenView(BaseModel):
    language: str
    title: str
    result: str
    error: str | None = None


class PageView(BaseModel):
    title: str
    language: str
    url: str
    verification: str
    notes: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    omitted: int = 0
    chars: str | None = None


class LicenseView(BaseModel):
    name: str
    url: str


class WikipediaCallsView(BaseModel):
    title: str
    source: str
    labels: dict[str, str]
    calls: list[str] = Field(default_factory=list)
    reused: int = 0
    searches: list[SearchView] = Field(default_factory=list)
    opens: list[OpenView] = Field(default_factory=list)
    pages: list[PageView] = Field(default_factory=list)
    license: LicenseView | None = None
    hints: list[str] = Field(default_factory=list)


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _page_view(row: dict[str, Any], language: str | None) -> PageView:
    delivered, total = row.get("delivered_chars"), row.get("total_chars")
    chars = None
    if isinstance(delivered, int):
        chars = f"{delivered}/{total}" if isinstance(total, int) else str(delivered)
    sections = row.get("sections")
    omitted = row.get("omitted")
    return PageView(
        title=printable(row.get("title")),
        language=printable(row.get("language")),
        url=printable(row.get("url")),
        verification=printable(row.get("verification")),
        notes=[code_label(note, language) for note in row.get("notes") or [] if isinstance(note, str)],
        sections=[printable(name) for name in sections] if isinstance(sections, list) else [],
        omitted=omitted if isinstance(omitted, int) else 0,
        chars=chars,
    )


def wikipedia_calls_view(step: TraceStep, language: str | None) -> WikipediaCallsView:
    data = step.data
    text = labels(language)
    raw_calls = data.get("calls")
    pages = [row for row in _rows(data.get("pages")) if _https(row.get("url"))]
    searches = []
    for search in _rows(data.get("searches")):
        summary = f"{search.get('returned', 0)} {text['received']}, {search.get('kept', 0)} {text['kept']}"
        dropped = search.get("filtered_out") or {}
        if isinstance(dropped, dict) and dropped:
            parts = ", ".join(f"{code_label(code, language)} {count}" for code, count in dropped.items())
            summary += f"; {text['dropped']}: {parts}"
        searches.append(
            SearchView(
                language=printable(search.get("language")),
                q=printable(search.get("q")),
                summary=summary,
                error=code_label(search["error"], language) if search.get("error") else None,
            )
        )
    opens = [
        OpenView(
            language=printable(row.get("language")),
            title=printable(row.get("title")),
            result=code_label(row.get("result"), language),
            error=code_label(row["error"], language) if row.get("error") else None,
        )
        for row in _rows(data.get("opens"))
    ]
    raw_license = data.get("license") if isinstance(data.get("license"), dict) else {}
    license_name = printable(raw_license.get("name")) or DEFAULT_LICENSE
    licence = (
        LicenseView(name=license_name, url=printable(raw_license.get("url")))
        if _https(raw_license.get("url"))
        else None
    )
    hints = data.get("hints")
    reused = data.get("reused")
    return WikipediaCallsView(
        title=f"{text['title']} — {len(pages)} {text['page'] if len(pages) == 1 else text['pages']}",
        source=text["source"].format(license=license_name),
        labels=text,
        calls=[printable(url) for url in raw_calls if _https(url)] if isinstance(raw_calls, list) else [],
        reused=reused if isinstance(reused, int) else 0,
        searches=searches,
        opens=opens,
        pages=[_page_view(row, language) for row in pages],
        license=licence,
        hints=[text[hint] for hint in hints if hint in ("specify_year", "add_context")] if isinstance(hints, list) else [],
    )
