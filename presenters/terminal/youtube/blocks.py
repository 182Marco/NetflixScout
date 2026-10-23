"""Terminal print blocks for YouTube (same box style as `terminal/box.py`).

Every text from the trace is printed through `printable`, which removes C0 and C1 control
characters (ANSI escapes, bell, ...) so a video title cannot drive the terminal. It is a
display-only copy: the trace, the metadata and the LLM prompt keep the API values unchanged.
"""
from __future__ import annotations

from typing import Any

from ..box import print_box

# Notice for the YouTube API Services Developer Policies III.A (links to the YouTube Terms
# of Service and the Google Privacy Policy) and III.F (YouTube named as the source).
YOUTUBE_NOTICE = (
    "This application uses YouTube API Services. YouTube Terms of Service: "
    "https://www.youtube.com/t/terms · Google Privacy Policy: https://policies.google.com/privacy"
)

# Whitespace controls become a space so words do not merge; every other control is removed.
_WHITESPACE_CONTROLS = {"\t", "\n", "\r", "\x0b", "\x0c", "\x85"}

LABELS = {
    "it": {
        "title": "YOUTUBE",
        "videos": "video",
        "source": "Fonte: YouTube (risultati di ricerca, non verificati come ufficiali)",
        "called": "Chiamato",
        "no_calls": "Nessuna chiamata a YouTube in questo turno.",
        "search": "Ricerca",
        "received": "ricevuti",
        "kept": "tenuti",
        "dropped": "scartati",
        "error": "errore",
        "not_searched": "Non cercati in questo turno",
        "quota_paused": "Quota di ricerca YouTube esaurita (condivisa dal progetto Google) fino a",
        "no_videos": "Nessun video da mostrare.",
        "notes": "note",
    },
    "en": {
        "title": "YOUTUBE",
        "videos": "videos",
        "source": "Source: YouTube (search results, not verified as official)",
        "called": "Called",
        "no_calls": "No YouTube call in this turn.",
        "search": "Search",
        "received": "received",
        "kept": "kept",
        "dropped": "dropped",
        "error": "error",
        "not_searched": "Not searched in this turn",
        "quota_paused": "YouTube search quota exhausted (shared by the Google project) until",
        "no_videos": "No video to show.",
        "notes": "notes",
    },
}

KIND_LABELS = {
    "it": {
        "trailer": "trailer",
        "director_interview": "interviste",
        "making_of": "making-of",
        "behind_the_scenes": "dietro le quinte",
        "author_commentary": "commenti degli autori",
    },
    "en": {
        "trailer": "trailer",
        "director_interview": "interviews",
        "making_of": "making-of",
        "behind_the_scenes": "behind the scenes",
        "author_commentary": "authors' commentary",
    },
}

# Codes of reasons, errors, drops and notes; an unknown code is shown as it is.
CODE_LABELS = {
    "it": {
        "turn_limit": "limite di ricerche per turno",
        "quota_exceeded": "quota giornaliera esaurita",
        "rate_limited": "troppe richieste, pausa breve",
        "unauthorized": "chiave API rifiutata",
        "api_not_enabled": "YouTube Data API non abilitata",
        "timeout": "tempo scaduto",
        "network_error": "errore di rete",
        "http_error": "risposta non valida",
        "no_anchor": "film non nominato",
        "negative_pattern": "reaction/parodia/fan made",
        "other_format": "altro formato (recensione, film completo, trailer)",
        "year_conflict": "anno diverso",
        "homonym_risk": "possibile omonimo",
        "short_video": "Short",
        "unavailable": "non più disponibile",
        "invalid_id": "non è un video",
        "duplicate_of_other_kind": "già in un'altra categoria",
        "kind_unconfirmed": "categoria non confermata dal titolo",
        "title_in_description_only": "film citato solo nella descrizione",
        "film_title_absent": "titolo del film assente",
        "homonym_unchecked": "omonimia non verificabile",
        "very_short": "molto breve",
        "duration_unknown": "durata sconosciuta",
        "title_from_search": "dati della ricerca",
    },
    "en": {
        "turn_limit": "per-turn search limit",
        "quota_exceeded": "daily quota exhausted",
        "rate_limited": "too many requests, short pause",
        "unauthorized": "API key rejected",
        "api_not_enabled": "YouTube Data API not enabled",
        "timeout": "timed out",
        "network_error": "network error",
        "http_error": "invalid answer",
        "no_anchor": "film not named",
        "negative_pattern": "reaction/parody/fan made",
        "other_format": "another format (review, full movie, trailer)",
        "year_conflict": "different year",
        "homonym_risk": "possible homonym",
        "short_video": "Short",
        "unavailable": "no longer available",
        "invalid_id": "not a video",
        "duplicate_of_other_kind": "already in another category",
        "kind_unconfirmed": "category not confirmed by the title",
        "title_in_description_only": "film named only in the description",
        "film_title_absent": "film title absent",
        "homonym_unchecked": "homonymy not checkable",
        "very_short": "very short",
        "duration_unknown": "unknown duration",
        "title_from_search": "search data",
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


def kind_label(kind: Any, language: str | None) -> str:
    table = KIND_LABELS["it" if language == "it" else "en"]
    return table.get(kind, printable(kind)) if isinstance(kind, str) else "?"


def code_label(code: Any, language: str | None) -> str:
    if not isinstance(code, str):
        return "?"
    table = CODE_LABELS["it" if language == "it" else "en"]
    if code.startswith("blocked_in:"):
        country = printable(code.split(":", 1)[1])
        return f"non visibile in {country}" if language == "it" else f"not viewable in {country}"
    return table.get(code, printable(code))


def print_youtube_calls(
    *,
    calls: list[str],
    searches: list[dict[str, Any]],
    not_searched: list[dict[str, Any]],
    videos: list[dict[str, Any]],
    quota_paused_until: str | None,
    language: str | None,
) -> None:
    text = labels(language)
    print_box("▶️", f"{text['title']} — {len(videos)} {text['videos']}")
    print(f"  {text['source']}")

    print()
    if not calls:
        print(f"  {text['no_calls']}")
    for url in calls:
        print(f"  {text['called']}: {printable(url)}")

    for search in searches:
        print(f"\n  🔎 {text['search']} {kind_label(search.get('kind'), language)}: {printable(search.get('q'))}")
        line = f"     {search.get('returned', 0)} {text['received']}, {search.get('kept', 0)} {text['kept']}"
        dropped = search.get("filtered_out") or {}
        if isinstance(dropped, dict) and dropped:
            parts = ", ".join(f"{code_label(code, language)} {count}" for code, count in dropped.items())
            line += f"; {text['dropped']}: {parts}"
        print(line)
        if search.get("error"):
            print(f"     ⚠️  {text['error']}: {code_label(search['error'], language)}")

    if not_searched:
        parts = ", ".join(
            f"{kind_label(row.get('kind'), language)} ({code_label(row.get('reason'), language)})" for row in not_searched
        )
        print(f"\n  ⏭️  {text['not_searched']}: {parts}")
    if quota_paused_until:
        print(f"\n  ⛔ {text['quota_paused']} {printable(quota_paused_until)}")

    print()
    if not videos:
        print(f"  {text['no_videos']}")
    for video in videos:
        date = printable(video.get("published_at"))[:10]
        print(
            f"  ▶ [{kind_label(video.get('kind'), language)}] {printable(video.get('title'))}"
            f" — {printable(video.get('channel'))}" + (f" ({date})" if date else "")
        )
        print(f"     {printable(video.get('url'))}")
        notes = [code_label(note, language) for note in video.get("notes") or []]
        if notes:
            print(f"     {text['notes']}: {', '.join(notes)}")


def print_youtube_notice() -> None:
    """Startup notice: YouTube Terms of Service and Google Privacy Policy links."""
    print(f"ℹ️  {YOUTUBE_NOTICE}\n")
