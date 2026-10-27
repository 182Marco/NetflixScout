"""Channel-neutral view of a `youtube_calls` step, shared by the terminal and web presenters.

Holds the labels (it/en), the display copy of API text (`printable`: no C0/C1 control
characters, the trace and the LLM prompt keep the API values) and the `YoutubeCallsView`
both channels show: same searches, kept and dropped counts, videos (confirmed first, then
"to verify") and hints; only the format differs. Reads only `step.data`; imports nothing but
`turn`: no `youtube` package, no tool logic. Only `https://` URLs are shown.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

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
        "not_searched": "Non cercato",
        "quota_paused": "Quota di ricerca YouTube esaurita (condivisa dal progetto Google) fino a",
        "no_videos": "Nessun video da mostrare.",
        "notes": "note",
        "to_verify": "Da verificare (categoria o film non confermati):",
        "specify_year": "Indica l'anno del film per escludere eventuali omonimi.",
        "original_title": "Se il film ha un titolo originale diverso, indicarlo può aiutare.",
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
        "not_searched": "Not searched",
        "quota_paused": "YouTube search quota exhausted (shared by the Google project) until",
        "no_videos": "No video to show.",
        "notes": "notes",
        "to_verify": "To verify (category or film not confirmed):",
        "specify_year": "Give the film's year to rule out homonyms.",
        "original_title": "If the film has a different original title, giving it can help.",
    },
    "de": {
        "title": "YOUTUBE",
        "videos": "Videos",
        "source": "Quelle: YouTube (Suchergebnisse, nicht als offiziell geprüft)",
        "called": "Aufgerufen",
        "no_calls": "Kein YouTube-Aufruf in diesem Durchgang.",
        "search": "Suche",
        "received": "erhalten",
        "kept": "behalten",
        "dropped": "verworfen",
        "error": "Fehler",
        "not_searched": "Nicht gesucht",
        "quota_paused": "YouTube-Suchkontingent erschöpft (vom Google-Projekt geteilt) bis",
        "no_videos": "Kein Video anzuzeigen.",
        "notes": "Hinweise",
        "to_verify": "Zu prüfen (Kategorie oder Film nicht bestätigt):",
        "specify_year": "Nenne das Jahr des Films, um Namensgleiche auszuschließen.",
        "original_title": "Hat der Film einen anderen Originaltitel, kann dessen Angabe helfen.",
    },
}

KIND_LABELS = {
    "it": {
        "trailer": "trailer",
        "director_interview": "interviste al regista",
        "cast_interview": "interviste al cast",
        "making_of": "making-of",
        "behind_the_scenes": "dietro le quinte",
        "author_commentary": "commenti degli autori",
    },
    "en": {
        "trailer": "trailer",
        "director_interview": "director interviews",
        "cast_interview": "cast interviews",
        "making_of": "making-of",
        "behind_the_scenes": "behind the scenes",
        "author_commentary": "authors' commentary",
    },
    "de": {
        "trailer": "Trailer",
        "director_interview": "Interviews mit der Regie",
        "cast_interview": "Interviews mit der Besetzung",
        "making_of": "Making-of",
        "behind_the_scenes": "Blick hinter die Kulissen",
        "author_commentary": "Kommentare der Macher",
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
    "de": {
        "turn_limit": "Suchlimit pro Durchgang",
        "quota_exceeded": "Tageskontingent erschöpft",
        "rate_limited": "zu viele Anfragen, kurze Pause",
        "unauthorized": "API-Schlüssel abgelehnt",
        "api_not_enabled": "YouTube Data API nicht aktiviert",
        "timeout": "Zeitüberschreitung",
        "network_error": "Netzwerkfehler",
        "http_error": "ungültige Antwort",
        "no_anchor": "Film nicht genannt",
        "negative_pattern": "Reaction/Parodie/Fan-Made",
        "other_format": "anderes Format (Kritik, ganzer Film, Trailer)",
        "year_conflict": "anderes Jahr",
        "homonym_risk": "möglicherweise ein Namensgleicher",
        "short_video": "Short",
        "unavailable": "nicht mehr verfügbar",
        "invalid_id": "kein Video",
        "duplicate_of_other_kind": "schon in einer anderen Kategorie",
        "kind_unconfirmed": "Kategorie vom Titel nicht bestätigt",
        "title_in_description_only": "Film nur in der Beschreibung genannt",
        "film_title_absent": "Filmtitel fehlt",
        "homonym_unchecked": "Namensgleichheit nicht prüfbar",
        "very_short": "sehr kurz",
        "duration_unknown": "Dauer unbekannt",
        "title_from_search": "Daten aus der Suche",
    },
}


BLOCKED_IN = {
    "it": "non visibile in {country}",
    "en": "not viewable in {country}",
    "de": "nicht abrufbar in {country}",
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
    return LABELS[label_language(language)]


def kind_label(kind: Any, language: str | None) -> str:
    table = KIND_LABELS[label_language(language)]
    return table.get(kind, printable(kind)) if isinstance(kind, str) else "?"


def code_label(code: Any, language: str | None) -> str:
    if not isinstance(code, str):
        return "?"
    table = CODE_LABELS[label_language(language)]
    if code.startswith("blocked_in:"):
        country = printable(code.split(":", 1)[1])
        return BLOCKED_IN[label_language(language)].format(country=country)
    return table.get(code, printable(code))


class VideoView(BaseModel):
    kind_label: str
    title: str
    channel: str
    published: str
    url: str
    notes: list[str] = Field(default_factory=list)


class SearchView(BaseModel):
    kind_label: str
    q: str
    summary: str
    error: str | None = None


class VideoGroup(BaseModel):
    kind_label: str
    confirmed: list[VideoView] = Field(default_factory=list)
    to_verify: list[VideoView] = Field(default_factory=list)


class YoutubeCallsView(BaseModel):
    title: str
    source: str
    labels: dict[str, str]
    calls: list[str] = Field(default_factory=list)
    searches: list[SearchView] = Field(default_factory=list)
    not_searched: str | None = None
    quota_paused: str | None = None
    groups: list[VideoGroup] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw or [] if isinstance(row, dict)] if isinstance(raw, list) else []


def _https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _video_view(video: dict[str, Any], language: str | None) -> VideoView:
    return VideoView(
        kind_label=kind_label(video.get("kind"), language),
        title=printable(video.get("title")),
        channel=printable(video.get("channel")),
        published=printable(video.get("published_at"))[:10],
        url=printable(video.get("url")),
        notes=[code_label(note, language) for note in video.get("notes") or []],
    )


def youtube_calls_view(step: TraceStep, language: str | None) -> YoutubeCallsView:
    data = step.data
    text = labels(language)
    raw_calls = data.get("calls")
    videos = [video for video in _rows(data.get("videos")) if _https(video.get("url"))]
    searches = []
    for search in _rows(data.get("searches")):
        summary = f"{search.get('returned', 0)} {text['received']}, {search.get('kept', 0)} {text['kept']}"
        dropped = search.get("filtered_out") or {}
        if isinstance(dropped, dict) and dropped:
            parts = ", ".join(f"{code_label(code, language)} {count}" for code, count in dropped.items())
            summary += f"; {text['dropped']}: {parts}"
        searches.append(
            SearchView(
                kind_label=kind_label(search.get("kind"), language),
                q=printable(search.get("q")),
                summary=summary,
                error=code_label(search["error"], language) if search.get("error") else None,
            )
        )
    not_searched = _rows(data.get("not_searched"))
    paused = data.get("quota_paused_until")
    hints = data.get("hints")
    # Per kind, in the order received: confirmed videos first, then those to verify.
    groups = []
    for kind in dict.fromkeys(video.get("kind") for video in videos):
        rows = [video for video in videos if video.get("kind") == kind]
        groups.append(
            VideoGroup(
                kind_label=kind_label(kind, language),
                confirmed=[_video_view(v, language) for v in rows if v.get("verification") != "to_verify"],
                to_verify=[_video_view(v, language) for v in rows if v.get("verification") == "to_verify"],
            )
        )
    return YoutubeCallsView(
        title=f"{text['title']} — {len(videos)} {text['videos']}",
        source=text["source"],
        labels=text,
        calls=[printable(url) for url in raw_calls if _https(url)] if isinstance(raw_calls, list) else [],
        searches=searches,
        # Terminal only, and short: the categories, not the reasons (errors and the quota
        # pause have their own lines). The web serializer leaves it out.
        not_searched=", ".join(kind_label(row.get("kind"), language) for row in not_searched) or None,
        quota_paused=f"{text['quota_paused']} {printable(paused)}" if isinstance(paused, str) and paused else None,
        groups=groups,
        hints=[text[hint] for hint in hints if hint in ("specify_year", "original_title")] if isinstance(hints, list) else [],
    )
