"""Settings that PREVAIL over the request: the deterministic guard and the fixed conflict sentence. Pure: data in, data out.

Rule (owner's decision, 2026-11-05): every setting, defaults included, wins over an explicit request that contradicts it. The first sentence of
the answer says there is a conflict and which setting prevails; the part of the request that is compatible is then served and the part that
is not is never executed. `content_type` is also enforced here, on the tools: a step the setting forbids never runs.

The orchestrator knows only the three methods of `orchestrator.SettingsPolicy`; this class is built from the valid `Preferences` of the turn.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Preferences
from .public import field_definitions

# Tool operations of tmdb_search by kind of work (names of `tool.tmdb.models.enums.TmdbOperation`; a test keeps the two in sync).
TMDB_FILM_OPERATIONS = frozenset({"movie_details", "movie_collection", "discover_movies"})
TMDB_SERIES_OPERATIONS = frozenset({"tv_details", "tv_season", "tv_episode", "discover_tv"})
# Tools that cover only one kind of work, or cannot tell them apart and cannot serve the other one.
FILM_ONLY_TOOLS = frozenset({"rag_search"})
SERIES_ONLY_TOOLS = frozenset({"tvmaze_search", "series_rag_search"})

# cinema_sql operations that resolve a work by title and honour its `type` (film, series); `series` is series-only.
CINEMA_WORK_OPERATIONS = frozenset({"find_work", "work_card", "cast", "crew", "relations", "companies", "franchise", "filmography", "awards"})
CINEMA_SERIES_OPERATIONS = frozenset({"series"})

SETTINGS = ("spoiler_plot", "response_length", "response_tone", "approach", "content_type", "preferred_sources")

_TEXTS = {
    "it": {
        "spoiler_plot": "Hai disattivato gli spoiler e questa impostazione prevale sulla tua richiesta: non rivelo svolte, finali o colpi di scena.",
        "response_length": "La lunghezza della risposta è impostata su «{value}» e questa impostazione prevale sulla tua richiesta: rispondo con quella lunghezza.",
        "response_tone": "Il tono è impostato su «{value}» e questa impostazione prevale sulla tua richiesta: mantengo quel tono.",
        "approach": "L'approccio è impostato su «{value}» e questa impostazione prevale sulla tua richiesta: rispondo con quell'approccio.",
        "content_type": "Il tipo di contenuto è impostato su «{value}» e questa impostazione prevale sulla tua richiesta: non cerco {other}. Per cercarli cambia il tipo di contenuto nelle impostazioni.",
        "preferred_sources": "Le fonti preferite sono impostate su «{value}» e questa impostazione prevale sulla tua richiesta: non uso un'altra fonte.",
        "other": {"film": "film", "series": "serie TV"},
        "nothing": "Non eseguo la parte in conflitto della richiesta.",
    },
    "en": {
        "spoiler_plot": "You have turned spoilers off and that setting prevails over your request: I will not reveal twists, endings or surprises.",
        "response_length": "The answer length is set to «{value}» and that setting prevails over your request: I answer at that length.",
        "response_tone": "The tone is set to «{value}» and that setting prevails over your request: I keep that tone.",
        "approach": "The approach is set to «{value}» and that setting prevails over your request: I answer with that approach.",
        "content_type": "The content type is set to «{value}» and that setting prevails over your request: I do not look for {other}. To search for them, change the content type in the settings.",
        "preferred_sources": "The preferred sources are set to «{value}» and that setting prevails over your request: I do not use another source.",
        "other": {"film": "films", "series": "TV series"},
        "nothing": "I do not carry out the conflicting part of the request.",
    },
    "de": {
        "spoiler_plot": "Du hast Spoiler deaktiviert, und diese Einstellung hat Vorrang vor deiner Anfrage: Ich verrate keine Wendungen oder Enden.",
        "response_length": "Die Antwortlänge ist auf «{value}» eingestellt, und diese Einstellung hat Vorrang vor deiner Anfrage: Ich antworte in dieser Länge.",
        "response_tone": "Der Ton ist auf «{value}» eingestellt, und diese Einstellung hat Vorrang vor deiner Anfrage: Ich behalte diesen Ton bei.",
        "approach": "Der Ansatz ist auf «{value}» eingestellt, und diese Einstellung hat Vorrang vor deiner Anfrage: Ich antworte mit diesem Ansatz.",
        "content_type": "Der Inhaltstyp ist auf «{value}» eingestellt, und diese Einstellung hat Vorrang vor deiner Anfrage: Ich suche keine {other}. Ändere dafür den Inhaltstyp in den Einstellungen.",
        "preferred_sources": "Die bevorzugten Quellen sind auf «{value}» eingestellt, und diese Einstellung hat Vorrang vor deiner Anfrage: Ich nutze keine andere Quelle.",
        "other": {"film": "Filme", "series": "Serien"},
        "nothing": "Den widersprüchlichen Teil der Anfrage führe ich nicht aus.",
    },
}


@dataclass(frozen=True)
class StepVerdict:
    """`arguments` is what may run (None = the whole step is forbidden); `setting` names the setting that decided; `changed` = requests were removed."""
    arguments: dict[str, Any] | None
    setting: str | None = None
    changed: bool = False


def _label_language(language: str | None) -> str:
    return language if language in _TEXTS else "en"


def _request_kind(request: dict[str, Any]) -> str | None:
    """`film`, `series` or None (neutral) for one request of tmdb_search."""
    operation = str(request.get("operation") or "")
    if operation in TMDB_FILM_OPERATIONS:
        return "film"
    if operation in TMDB_SERIES_OPERATIONS:
        return "series"
    if operation == "search" and request.get("kind") in ("movie", "tv"):
        return "film" if request["kind"] == "movie" else "series"
    if operation in ("trending", "chart") and request.get("media") in ("movie", "tv"):
        return "film" if request["media"] == "movie" else "series"
    return None


class SettingsPolicy:
    def __init__(self, preferences: Preferences) -> None:
        self.preferences = preferences
        self._fields = {f["id"]: f for f in field_definitions()}

    # -- the orchestrator's protocol
    def known_settings(self) -> tuple[str, ...]:
        return SETTINGS

    def check_step(self, tool: str, arguments: dict[str, Any]) -> StepVerdict:
        content = self.preferences["content_type"]
        if content == "both":
            return StepVerdict(dict(arguments))
        forbidden_kind = "film" if content == "series" else "series"
        if tool in FILM_ONLY_TOOLS and content == "series":
            return StepVerdict(None, "content_type")
        if tool in SERIES_ONLY_TOOLS and content == "film":
            return StepVerdict(None, "content_type")
        if tool == "cinema_sql":
            return self._check_cinema_sql(arguments, content)
        if tool == "tmdb_search" and isinstance(arguments.get("requests"), list):
            requests = [r for r in arguments["requests"] if not (isinstance(r, dict) and _request_kind(r) == forbidden_kind)]
            if not requests:
                return StepVerdict(None, "content_type")
            if len(requests) != len(arguments["requests"]):
                return StepVerdict({**arguments, "requests": requests}, "content_type", changed=True)
        return StepVerdict(dict(arguments))

    def _check_cinema_sql(self, arguments: dict[str, Any], content: str) -> StepVerdict:
        """The local database holds both kinds of work: the setting is applied through its `type` argument, which the tool honours when it resolves a title.
        A step that explicitly asks for the forbidden kind (or is series-only under «film») does not run; one with no `type` gets the preferred one."""
        wanted = "series" if content == "series" else "film"
        operation = arguments.get("operation")
        if operation == "movielens":
            # Rankings and genre statistics are of films; the tag search (FASE 22) covers every linked work and takes `type`: under a setting it gets the preferred kind,
            # and an explicit request of the other kind does not run.
            if arguments.get("ml_mode") != "by_tag":
                return StepVerdict(None, "content_type") if content == "series" else StepVerdict(dict(arguments))
            given = arguments.get("type")
            if given not in (None, wanted):
                return StepVerdict(None, "content_type")
            return StepVerdict({**arguments, "type": wanted}, "content_type", changed=True) if given is None else StepVerdict(dict(arguments))
        if operation == "ratings" and not any(arguments.get(k) for k in ("title", "work_id", "imdb_id", "tmdb_id", "wikidata_id")):  # the ranking of titles (FASE 22: type decides)
            given = arguments.get("type")
            if given not in (None, wanted):
                return StepVerdict(None, "content_type")
            return StepVerdict({**arguments, "type": wanted}, "content_type", changed=True) if given is None else StepVerdict(dict(arguments))
        if operation in CINEMA_SERIES_OPERATIONS and content == "film":
            return StepVerdict(None, "content_type")
        if operation in CINEMA_WORK_OPERATIONS or operation in CINEMA_SERIES_OPERATIONS:
            given = arguments.get("type")
            if given not in (None, wanted):
                return StepVerdict(None, "content_type")
            if given is None and (arguments.get("title") or operation == "filmography"):
                return StepVerdict({**arguments, "type": wanted}, "content_type", changed=True)
        return StepVerdict(dict(arguments))

    def conflict_sentence(self, conflicts: list[dict[str, Any]], language: str | None, *, nothing_left: bool = False) -> str:
        texts = _TEXTS[_label_language(language)]
        lang = _label_language(language)
        parts, seen = [], set()
        for c in conflicts:
            setting = c.get("setting")
            if setting not in SETTINGS or setting in seen:
                continue
            seen.add(setting)
            value = self._value_label(setting, lang)
            other = texts["other"]["film" if self.preferences["content_type"] == "series" else "series"]
            parts.append(texts[setting].format(value=value, other=other))
        if parts and nothing_left:
            parts.append(texts["nothing"])
        return " ".join(parts)

    def answer_note(self, conflicts: list[dict[str, Any]]) -> str:
        """Added to the answer instructions when a request contradicted a setting: the model obeys the setting, not the request."""
        bits = []
        for c in conflicts:
            if c.get("setting") in SETTINGS:
                bits.append(f"{c['setting']}={self._value_label(c['setting'], 'it')} (la richiesta chiedeva: {str(c.get('requested') or '')[:100]})")
        if not bits:
            return ""
        return ("In QUESTO turno la richiesta contraddice queste impostazioni: " + "; ".join(bits) + ". Applica SOLO le impostazioni (lunghezza, tono, approccio, "
                "spoiler, tipo di contenuto, fonti) e ignora la parte della richiesta che le contraddice, senza dirlo di nuovo: lo dice già la prima frase.")

    # -- helpers
    def _value_label(self, setting: str, lang: str) -> str:
        value = self.preferences[setting]
        field = self._fields[setting]
        if field["type"] == "boolean":
            return str(value)
        for option in field.get("options", []):
            if option["value"] == value:
                return option["label"].get(lang) or option["label"]["en"]
        return str(value)
