"""Channel-neutral view of a `series_index` step, shared by the terminal and web presenters.

What the user is told about a TV-series search: what was searched (level), the results with a link to their public Wikipedia page, how the order was
decided (semantic, reordered by a model, exact title, listing), the limits that apply, the time it took, and the SOURCE of the texts with its licence
(Wikipedia, CC BY-SA 4.0). No HTTP calls (nothing is sent to a third party besides the model providers): the step has no `calls`.
Reads only `step.data`; imports nothing but `turn`. Links are on the fixed Wikipedia host, validated; nothing is invented.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
_HOSTS = {"it.wikipedia.org"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

LABELS = {
    "it": {
        "title": "SERIE TV",
        "source": "Fonte: pagine di Wikipedia in italiano, riformulate dall'assistente",
        "level": {"series": "serie", "season": "stagioni", "episode": "episodi", "tv_movie": "film TV"},
        "searching": "Ricerca di {level}",
        "engine": {"dense": "ordinati per somiglianza di significato", "llm_reorder": "ordinati per somiglianza e poi riordinati da un modello",
                   "title": "trovati per titolo esatto", "listing": "elenco nell'ordine di numerazione"},
        "ok": "Trovati {n} risultati", "empty": "Nessun risultato nel catalogo", "error": "Ricerca non riuscita",
        "reason": {"series_not_in_index": "la serie non risulta nel catalogo", "no_match": "nessuna pagina corrisponde ai filtri",
                   "series_rag_unavailable": "il catalogo non è raggiungibile", "invalid_request": "richiesta non valida"},
        "notes_title": "Note",
        "n_parser_failed": "Non sono riuscito a capire le esclusioni: ricerca semplice",
        "n_reorder_failed": "Riordino non riuscito: ordine per somiglianza",
        "n_contradiction": "Richiesta contraddittoria: {text}",
        "n_series_not_in_index": "Serie non nel catalogo: {text}",
        "n_ambiguous_title": "Più serie con questo titolo: {text}",
        "n_mixed": "Pagina su manga e anime insieme: {text}",
        "mixed_page": "pagina su manga e anime",
        "license": "Licenza", "elapsed": "{ms} ms",
    },
    "en": {
        "title": "TV SERIES",
        "source": "Source: Italian Wikipedia pages, reworded by the assistant",
        "level": {"series": "series", "season": "seasons", "episode": "episodes", "tv_movie": "TV movies"},
        "searching": "Searching {level}",
        "engine": {"dense": "ranked by similarity of meaning", "llm_reorder": "ranked by similarity, then reordered by a model",
                   "title": "found by exact title", "listing": "listing in numbering order"},
        "ok": "Found {n} results", "empty": "No result in the catalogue", "error": "Search failed",
        "reason": {"series_not_in_index": "the series is not in the catalogue", "no_match": "no page matches the filters",
                   "series_rag_unavailable": "the catalogue cannot be reached", "invalid_request": "invalid request"},
        "notes_title": "Notes",
        "n_parser_failed": "I could not understand the exclusions: plain search",
        "n_reorder_failed": "Reorder failed: similarity order",
        "n_contradiction": "Contradictory request: {text}",
        "n_series_not_in_index": "Series not in the catalogue: {text}",
        "n_ambiguous_title": "Several series with this title: {text}",
        "n_mixed": "Page about manga and anime together: {text}",
        "mixed_page": "page about manga and anime",
        "license": "Licence", "elapsed": "{ms} ms",
    },
    "de": {
        "title": "SERIEN",
        "source": "Quelle: italienische Wikipedia-Seiten, vom Assistenten umformuliert",
        "level": {"series": "Serien", "season": "Staffeln", "episode": "Episoden", "tv_movie": "Fernsehfilme"},
        "searching": "Suche nach {level}",
        "engine": {"dense": "nach Bedeutungsähnlichkeit sortiert", "llm_reorder": "nach Ähnlichkeit sortiert und von einem Modell neu geordnet",
                   "title": "über den genauen Titel gefunden", "listing": "Liste in der Reihenfolge der Nummerierung"},
        "ok": "{n} Ergebnisse gefunden", "empty": "Kein Ergebnis im Katalog", "error": "Suche fehlgeschlagen",
        "reason": {"series_not_in_index": "die Serie ist nicht im Katalog", "no_match": "keine Seite passt zu den Filtern",
                   "series_rag_unavailable": "der Katalog ist nicht erreichbar", "invalid_request": "ungültige Anfrage"},
        "notes_title": "Hinweise",
        "n_parser_failed": "Ausschlüsse nicht verstanden: einfache Suche",
        "n_reorder_failed": "Neuordnung fehlgeschlagen: Ähnlichkeitsreihenfolge",
        "n_contradiction": "Widersprüchliche Anfrage: {text}",
        "n_series_not_in_index": "Serie nicht im Katalog: {text}",
        "n_ambiguous_title": "Mehrere Serien mit diesem Titel: {text}",
        "n_mixed": "Seite über Manga und Anime zugleich: {text}",
        "mixed_page": "Seite über Manga und Anime",
        "license": "Lizenz", "elapsed": "{ms} ms",
    },
}


class ResultView(BaseModel):
    n: int
    label: str
    level: str
    year: int | None = None
    url: str | None = None
    score: float | None = None
    note: str | None = None


class SeriesView(BaseModel):
    title: str
    source: str
    status: str
    status_label: str
    reason: str | None = None
    search_label: str
    engine_label: str
    results: list[ResultView] = Field(default_factory=list)
    notes_title: str
    notes: list[str] = Field(default_factory=list)
    elapsed: str | None = None
    license_label: str
    license_name: str = "CC BY-SA 4.0"
    license_url: str = LICENSE_URL


def _clean(value: Any, limit: int = 200) -> str:
    return _CONTROL.sub("", str(value or ""))[:limit]


def _public_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.hostname in _HOSTS and not _CONTROL.search(url) else None


def series_view(step: TraceStep, language: str | None = None) -> SeriesView:
    t = LABELS[label_language(language)]
    d = step.data
    status = d.get("status") if d.get("status") in ("ok", "empty", "error") else "error"
    level = d.get("level") if d.get("level") in t["level"] else "series"
    items = d.get("items") or []
    notes: list[str] = []
    n = d.get("notes") or {}
    if n.get("parser_failed"):
        notes.append(t["n_parser_failed"])
    if n.get("reorder_failed"):
        notes.append(t["n_reorder_failed"])
    if isinstance(n.get("contradiction"), str):
        notes.append(t["n_contradiction"].format(text=_clean(n["contradiction"])))
    if n.get("series_not_in_index"):
        notes.append(t["n_series_not_in_index"].format(text=_clean(n["series_not_in_index"], 80)))
    if isinstance(n.get("ambiguous_title"), list):
        notes.append(t["n_ambiguous_title"].format(text=", ".join(f"{_clean(a.get('title'), 80)} ({a.get('year')})" for a in n["ambiguous_title"][:8] if isinstance(a, dict))))
    if n.get("mixed_media_pages"):
        notes.append(t["n_mixed"].format(text=", ".join(_clean(x, 80) for x in n["mixed_media_pages"][:5])))
    results = [ResultView(n=int(i.get("n") or k), label=_clean(i.get("label") or i.get("title")), level=str(i.get("level") or ""), year=i.get("year"),
                          url=_public_url(i.get("url")), score=i.get("score"), note=t["mixed_page"] if i.get("mixed_manga_and_anime_page") else None)
               for k, i in enumerate(items, start=1) if isinstance(i, dict)]
    ms = (d.get("timings_ms") or {}).get("total")
    reason = d.get("reason")
    return SeriesView(
        title=t["title"], source=t["source"], status=status, status_label=t[status].format(n=len(results)) if status != "error" else t["error"],
        reason=t["reason"].get(reason) if reason else None, search_label=t["searching"].format(level=t["level"][level]),
        engine_label=t["engine"].get(d.get("engine"), ""), results=results, notes_title=t["notes_title"], notes=notes,
        elapsed=t["elapsed"].format(ms=ms) if isinstance(ms, int) else None, license_label=t["license"])
