"""Channel-neutral story of a turn, shared by the terminal and web presenters.

Turns the steps of a turn (and the passing stages) into a few short sentences for a person
who knows nothing about the system: what is being looked for and where, whether it was found,
how long it took, and when the system went on with less than planned. The terminal adds an
emoji per `level`, the web leaves the icon to the frontend; the text is the same.

Pure: no printing, no import of tool packages. A tool it does not know is called by its name.
"""
from __future__ import annotations

from turn import (
    OUTCOME_EMPTY,
    OUTCOME_ERROR,
    STAGE_ANSWERING,
    STAGE_UNDERSTANDING,
    STEP_CLASSIFICATION,
    STEP_PLANNING,
    STEP_QUERY_REWRITE,
    STEP_TOOL_OUTCOME,
    STEP_TOOL_SELECTION,
    StoryLine,
    TraceStep,
)

# After this many successful tool runs the "found" lines are dropped, so a long turn stays
# short; problems (`warn`) are always shown. The steps keep everything.
MAX_OK_LINES = 4

TEXT = {
    "it": {
        "understanding": "Capisco la domanda…",
        "answering": "Scrivo la risposta…",
        "understood": "Ho inteso la domanda così: {query}",
        "clarify": "Mi serve un chiarimento prima di cercare.",
        "searching": "Cerco {where}",
        "found": "{tool}: trovato",
        "empty": "{tool}: nessun risultato",
        "failed": "{tool}: {reason}",
        "not_searched": "Non ho cercato: {parts}",
        "seconds": "{n} s",
        "under_second": "meno di 1 s",
    },
    "en": {
        "understanding": "Understanding the question…",
        "answering": "Writing the answer…",
        "understood": "I understood the question as: {query}",
        "clarify": "I need a clarification before searching.",
        "searching": "Searching {where}",
        "found": "{tool}: found",
        "empty": "{tool}: no results",
        "failed": "{tool}: {reason}",
        "not_searched": "Not searched: {parts}",
        "seconds": "{n} s",
        "under_second": "under 1 s",
    },
}

# tool -> (where it searches, short name)
TOOLS = {
    "it": {
        "rag_search": ("tra le trame dei film", "Trame"),
        "movie_db_search": ("nei voti e nelle classifiche MovieLens", "Voti"),
        "tmdb_search": ("su TMDb", "TMDb"),
        "youtube_search": ("su YouTube", "YouTube"),
        "wikipedia_search": ("su Wikipedia", "Wikipedia"),
    },
    "en": {
        "rag_search": ("among the movie plots", "Plots"),
        "movie_db_search": ("in the MovieLens ratings and charts", "Ratings"),
        "tmdb_search": ("on TMDb", "TMDb"),
        "youtube_search": ("on YouTube", "YouTube"),
        "wikipedia_search": ("on Wikipedia", "Wikipedia"),
    },
}

# Reason codes of a failed tool run or of a turn that went on with less than planned.
REASONS = {
    "it": {
        "unsupported_request": "questa richiesta non si può cercare qui",
        "parser_failed": "non sono riuscito a capire la richiesta",
        "unverified_match": "titolo non verificato, ci sono versioni simili",
        "invalid_request": "richiesta non valida",
        "quota_exceeded": "quota giornaliera esaurita",
        "turn_limit": "limite di ricerche per questa domanda raggiunto",
        "rate_limited": "troppe richieste, riprova tra poco",
        "timeout": "tempo scaduto",
        "network_error": "errore di rete",
        "http_error": "risposta non valida",
        "response_too_large": "pagina troppo grande da leggere",
        "default": "non è andata a buon fine",
    },
    "en": {
        "unsupported_request": "this kind of request cannot be searched here",
        "parser_failed": "I could not understand the request",
        "unverified_match": "title not verified, there are similar versions",
        "invalid_request": "invalid request",
        "quota_exceeded": "daily quota exhausted",
        "turn_limit": "search limit for this question reached",
        "rate_limited": "too many requests, try again shortly",
        "timeout": "timed out",
        "network_error": "network error",
        "http_error": "invalid answer",
        "response_too_large": "page too large to read",
        "default": "it did not work",
    },
}

FALLBACKS = {
    "it": {
        "planner_failed": "Non ho capito bene come cercare: ho usato la ricerca per trama.",
        "low_confidence": "Non ero sicuro di come cercare: ho usato la ricerca per trama.",
        "unknown_tool": "Non ero sicuro di come cercare: ho usato la ricerca per trama.",
        "next_step_failed": "Non ho potuto pianificare il passo successivo: rispondo con quello che ho.",
        "max_tool_calls": "Ho raggiunto il limite di passaggi per questa domanda.",
        "max_iterations": "Ho raggiunto il limite di pianificazioni per questa domanda.",
        "max_execution_time": "Ho raggiunto il tempo massimo per questa domanda.",
        "token_budget": "Ho raggiunto il budget di token per questa domanda.",
        "answer_failed": "Non sono riuscito a scrivere la risposta completa: ti mostro i risultati trovati.",
    },
    "en": {
        "planner_failed": "I could not work out how to search: I used the plot search.",
        "low_confidence": "I was not sure how to search: I used the plot search.",
        "unknown_tool": "I was not sure how to search: I used the plot search.",
        "next_step_failed": "I could not plan the next step: I am answering with what I have.",
        "max_tool_calls": "I reached the step limit for this question.",
        "max_iterations": "I reached the planning limit for this question.",
        "max_execution_time": "I reached the time limit for this question.",
        "token_budget": "I reached the token budget for this question.",
        "answer_failed": "I could not write the full answer: here are the results I found.",
    },
}


def _table(table: dict[str, dict], language: str) -> dict:
    return table["it"] if language == "it" else table["en"]


def _seconds(elapsed_ms: object, language: str) -> str:
    text = _table(TEXT, language)
    ms = elapsed_ms if isinstance(elapsed_ms, (int, float)) else 0
    return text["seconds"].format(n=round(ms / 1000)) if ms >= 1000 else text["under_second"]


class StoryBuilder:
    """Feed it the stages and steps in the order they happen; it returns the new lines.

    The terminal and the turn itself each hold one, so the live story and `TurnResult.story`
    are the same text by construction. The language comes from the `classification` step
    (Italian until then).
    """

    def __init__(self, language: str = "it") -> None:
        self.language = language
        self._ok_shown = 0

    def status(self, stage: str) -> list[StoryLine]:
        text = _table(TEXT, self.language)
        if stage in (STAGE_UNDERSTANDING, STAGE_ANSWERING):
            return [StoryLine(level="progress", text=text[stage])]
        return []

    def step(self, step: TraceStep) -> list[StoryLine]:
        handler = _HANDLERS.get(step.kind)
        return handler(self, step) if handler else []

    def _classification(self, step: TraceStep) -> list[StoryLine]:
        language = step.data.get("language")
        if language in ("it", "en"):
            self.language = language
        return []

    def _query_rewrite(self, step: TraceStep) -> list[StoryLine]:
        if not step.data.get("rewritten"):
            return []
        text = _table(TEXT, self.language)
        return [StoryLine(level="info", text=text["understood"].format(query=step.data.get("used", "")))]

    def _tool_selection(self, step: TraceStep) -> list[StoryLine]:
        text = _table(TEXT, self.language)
        tool = step.data.get("tool")
        if step.data.get("clarification") or not tool:
            return [StoryLine(level="info", text=text["clarify"])]
        where, _ = _table(TOOLS, self.language).get(tool, (tool, tool))
        line = text["searching"].format(where=where)
        purpose = step.data.get("purpose")
        return [StoryLine(level="progress", text=f"{line}: {purpose}" if purpose else line, tool=tool)]

    def _tool_outcome(self, step: TraceStep) -> list[StoryLine]:
        text = _table(TEXT, self.language)
        tool = step.data.get("tool")
        _, short = _table(TOOLS, self.language).get(tool, (tool, tool))
        status = step.data.get("status")
        if status == OUTCOME_ERROR:
            reasons = _table(REASONS, self.language)
            body = text["failed"].format(tool=short, reason=reasons.get(step.data.get("reason"), reasons["default"]))
            level = "warn"
        elif status == OUTCOME_EMPTY:
            body, level = text["empty"].format(tool=short), "warn"
        else:
            self._ok_shown += 1
            if self._ok_shown > MAX_OK_LINES:
                return []
            body, level = text["found"].format(tool=short), "ok"
        return [StoryLine(level=level, text=f"{body}, {_seconds(step.data.get('elapsed_ms'), self.language)}", tool=tool)]

    def _planning(self, step: TraceStep) -> list[StoryLine]:
        text = _table(TEXT, self.language)
        fallbacks = _table(FALLBACKS, self.language)
        lines = [
            StoryLine(level="warn", text=fallbacks[code])
            for code in dict.fromkeys(step.data.get("fallbacks") or [])
            if code in fallbacks
        ]
        pending = [str(part.get("part")) for part in step.data.get("pending") or [] if isinstance(part, dict)]
        if pending:
            lines.append(StoryLine(level="warn", text=text["not_searched"].format(parts="; ".join(pending))))
        return lines


_HANDLERS = {
    STEP_CLASSIFICATION: StoryBuilder._classification,
    STEP_QUERY_REWRITE: StoryBuilder._query_rewrite,
    STEP_TOOL_SELECTION: StoryBuilder._tool_selection,
    STEP_TOOL_OUTCOME: StoryBuilder._tool_outcome,
    STEP_PLANNING: StoryBuilder._planning,
}

# Steps whose content the story already tells: the terminal prints their lines, not a block.
STORY_STEP_KINDS = frozenset(_HANDLERS)


def build_story(steps: list[TraceStep], language: str = "it") -> list[StoryLine]:
    """The story of finished steps (no passing stages): for a replay or a web payload."""
    builder = StoryBuilder(language)
    return [line for step in steps for line in builder.step(step)]
