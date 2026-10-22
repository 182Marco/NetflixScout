"""Channel-neutral view of a `tmdb_calls` step, shared by the terminal and web presenters.

Shows only the endpoints actually called (credential already masked by the tool) and the
sources that must be credited. Labels are Italian when the turn is Italian, English
otherwise; this never affects the language of the LLM answer.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep

# Notice required by the TMDb API Terms of Use (§3 Attribution, updated 2023-10-20).
TMDB_NOTICE = (
    "This application uses TMDB and the TMDB APIs but is not endorsed, certified, "
    "or otherwise approved by TMDB."
)

ATTRIBUTION_SOURCES = {"justwatch": "JustWatch"}

LABELS = {
    "it": {
        "title": "CHIAMATE TMDB",
        "called": "Chiamato",
        "none": "Nessuna chiamata a TMDb in questo turno: dati già in cache.",
        "justwatch": "Dati sulla disponibilità in streaming: JustWatch",
    },
    "en": {
        "title": "TMDB CALLS",
        "called": "Called",
        "none": "No TMDb call in this turn: data already cached.",
        "justwatch": "Streaming availability data: JustWatch",
    },
}


class Attribution(BaseModel):
    source: str
    text: str


class TmdbCallsView(BaseModel):
    title: str
    called_label: str
    calls: list[str] = Field(default_factory=list)
    empty_message: str
    attributions: list[Attribution] = Field(default_factory=list)


def labels(language: str | None) -> dict[str, str]:
    return LABELS["it"] if language == "it" else LABELS["en"]


def _calls(raw: Any) -> list[str]:
    # Only display URLs built by the tool; anything else is not shown.
    return [url for url in raw or [] if isinstance(url, str) and url.startswith("https://")]


def tmdb_calls_view(step: TraceStep, language: str | None) -> TmdbCallsView:
    text = labels(language)
    attributions = [
        Attribution(source=ATTRIBUTION_SOURCES[key], text=text[key])
        for key in step.data.get("attributions") or []
        if key in ATTRIBUTION_SOURCES
    ]
    return TmdbCallsView(
        title=text["title"],
        called_label=text["called"],
        calls=_calls(step.data.get("calls")),
        empty_message=text["none"],
        attributions=attributions,
    )
