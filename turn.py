"""Channel-neutral result of one chat turn.

The core (`app.handle_query`) produces a `TurnResult` and never prints. Each output
channel in `presenters/` decides how to show it (terminal text, web payload, ...).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal, Protocol
from urllib.parse import quote, quote_plus, urlsplit

from pydantic import BaseModel, Field

# Known step kinds. Tools may add new ones: presenters must fall back gracefully.
STEP_CLASSIFICATION = "classification"
STEP_QUERY_REWRITE = "query_rewrite"
STEP_TOOL_SELECTION = "tool_selection"
# Multi-tool turns only: the parts of the request, the tools that ran and why the loop stopped.
STEP_PLANNING = "planning"
# One per tool run, after it: how long it took and whether it found something.
STEP_TOOL_OUTCOME = "tool_outcome"
STEP_RETRIEVAL = "retrieval"
STEP_RERANK = "rerank"
STEP_DB_QUERY = "db_query"
STEP_TMDB_CALLS = "tmdb_calls"
STEP_YOUTUBE_CALLS = "youtube_calls"
STEP_OMDB_CALLS = "omdb_calls"
STEP_TVMAZE_CALLS = "tvmaze_calls"
STEP_WIKIPEDIA_CALLS = "wikipedia_calls"

# Tool parameter set by `handle_query` with the turn language (ISO 639-1 code of the latest
# user message, from the classifier). Tools that do not use it ignore it.
TOOL_PARAM_TURN_LANGUAGE = "turn_language"

# Languages with fixed texts (labels, refusals, fallbacks) in the presenters. Any other turn
# language keeps its real code, but the fixed texts are shown in `DEFAULT_LANGUAGE`.
SUPPORTED_LABEL_LANGUAGES = ("it", "en", "de")
DEFAULT_LANGUAGE = "en"

# ISO 639-1 codes and the English names the classifier or a prompt may use for them.
_LANGUAGE_NAMES = {
    "ar": "Arabic", "bg": "Bulgarian", "ca": "Catalan", "cs": "Czech", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian",
    "fa": "Persian", "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sl": "Slovenian", "sr": "Serbian", "sv": "Swedish", "th": "Thai", "tr": "Turkish",
    "uk": "Ukrainian", "vi": "Vietnamese", "zh": "Chinese",
}
# Other ISO 639-1 codes accepted as a valid language even without a name above.
_OTHER_CODES = frozenset(
    "af am az be bn bs cy eu ga gl gu hy is ka kk km kn lo mk ml mn mr ms my ne pa si sq sw ta te "
    "ur uz".split()
)
_NAME_TO_CODE = {name.casefold(): code for code, name in _LANGUAGE_NAMES.items()} | {
    "deutsch": "de", "italiano": "it", "español": "es", "espanol": "es", "français": "fr",
    "francais": "fr", "português": "pt", "portugues": "pt", "norwegian bokmål": "no",
    "mandarin": "zh",
}


def normalize_language(value: object) -> str | None:
    """The ISO 639-1 code for a classifier output (`de`, `de-DE`, `German`), else None."""
    if not isinstance(value, str):
        return None
    text = value.strip().casefold().replace("_", "-")
    if text in _NAME_TO_CODE:
        return _NAME_TO_CODE[text]
    code = text.split("-", 1)[0] if len(text) > 2 and text[2] == "-" else text
    if code in _LANGUAGE_NAMES or code in _OTHER_CODES:
        return code
    return None


def label_language(code: str | None) -> str:
    """The language of the fixed texts for a turn language: it, en or de (else English)."""
    return code if code in SUPPORTED_LABEL_LANGUAGES else DEFAULT_LANGUAGE


def language_name(code: str | None) -> str:
    """English name of a language for prompts ("German"); the code itself when unknown."""
    return _LANGUAGE_NAMES.get(code or "", code or _LANGUAGE_NAMES[DEFAULT_LANGUAGE])

# Tool parameter set by the orchestrator: identifies the turn. A turn can run several tools,
# so per-turn limits (TMDb calls, YouTube searches) are counted per `turn_id`, not per run.
TOOL_PARAM_TURN_ID = "turn_id"


# Result of one tool run, set by the tool in `result["outcome"]` (outside `metadata`, so it
# never reaches the LLM prompt). `reason` is a short code the presenters turn into a sentence.
OUTCOME_OK = "ok"
OUTCOME_EMPTY = "empty"
OUTCOME_ERROR = "error"

# Optional key of a tool result (outside `metadata`, so outside the final prompt): the tool says it
# has more to give and describes what it already gave, so the orchestrator asks the planner whether
# to go on (`{"available": bool, "reasons": [str], "summary": str}`). Tools without it are unaffected.
RESULT_FOLLOW_UP = "follow_up"


def tool_outcome(status: str, reason: str | None = None) -> dict[str, str | None]:
    return {"status": status, "reason": reason}


# HTTP calls of the tools, as the user sees them: the request actually sent (method and full URL, path and
# every query parameter) with ONLY the value of a credential replaced by `***`. A tool records a call with
# `http_call` at the point where it builds the URL it sends, so what is shown is never rebuilt from a
# description; the presenters mask once more (`mask_url` is idempotent) so a tool cannot leak by forgetting.
MASK = "***"
# Names a credential travels under in the tools' APIs (TMDb `api_key`, YouTube `key`, OMDb `apikey`) and the
# usual others; the match is case-insensitive and on the whole name.
CREDENTIAL_PARAMS = frozenset(
    {"api_key", "apikey", "key", "access_token", "token", "auth", "authorization", "client_secret", "secret", "password"}
)
_METHOD = re.compile(r"^[A-Z]{3,7}$")


def _mask_query(query: str) -> str:
    pairs = []
    for pair in query.split("&"):
        name, sep, _ = pair.partition("=")
        pairs.append(f"{name}={MASK}" if sep and name.lower() in CREDENTIAL_PARAMS else pair)
    return "&".join(pairs)


def mask_url(url: str, secrets: Iterable[str] = ()) -> str:
    """`url` with the value of every credential parameter, any user:password and every occurrence of a known
    secret (raw or percent-encoded, wherever it is) replaced by `***`; the rest is left exactly as it is."""
    try:
        parts = urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            netloc = f"{MASK}@{netloc.rpartition('@')[2]}"
        masked = parts._replace(netloc=netloc, query=_mask_query(parts.query)).geturl()
    except ValueError:
        masked = MASK
    for secret in sorted({value for value in secrets if isinstance(value, str) and value}, key=len, reverse=True):
        for form in dict.fromkeys((secret, quote(secret, safe=""), quote_plus(secret))):
            masked = masked.replace(form, MASK)
    return masked


def http_call(method: str, url: str, secrets: Iterable[str] = ()) -> dict[str, str]:
    """The record of one HTTP request for a tool trace: `{"method", "url"}` with the credentials masked."""
    return {"method": method.upper() if _METHOD.match(method.upper()) else "?", "url": mask_url(url, secrets)}


class TraceStep(BaseModel):
    """One step of the procedure, in execution order."""

    kind: str
    title: str
    data: dict[str, Any] = Field(default_factory=dict)


# Moments of a turn that have no step of their own, shown while the user waits.
STAGE_UNDERSTANDING = "understanding"
STAGE_ANSWERING = "answering"


class StoryLine(BaseModel):
    """One short, non-technical sentence of the turn story, the same for every channel.

    `level` is how to show it (the terminal picks an emoji, the web an icon): `progress`
    (work in progress), `info`, `ok`, `warn`.
    """

    level: Literal["progress", "info", "ok", "warn"]
    text: str
    tool: str | None = None


class TurnObserver(Protocol):
    """Receives the turn while it happens. The core never prints: a channel implements this.

    `step` gets every `TraceStep` as soon as it exists; `status` gets a passing stage
    (`STAGE_*`) that is not a step and is not kept in `TurnResult.steps`; `answer_delta` gets
    the text of the final answer as it is written. Implementations
    must be quick: they run inside the turn.
    """

    def step(self, step: TraceStep) -> None:
        ...

    def status(self, stage: str) -> None:
        ...

    def answer_delta(self, text: str) -> None:
        """A piece of the final answer, in order, while the model writes it. Every answer
        (also a block message, a clarification question or a fallback) arrives as one or more
        deltas; a channel does not wait for `TurnResult.answer` to show it."""
        ...


class NullObserver:
    def step(self, step: TraceStep) -> None:
        pass

    def status(self, stage: str) -> None:
        pass

    def answer_delta(self, text: str) -> None:
        pass


class TurnResult(BaseModel):
    """Everything that happened while answering one user query."""

    query: str
    # ISO 639-1 code of the latest user message (any language, not only it/en).
    language: str
    blocked: bool
    answer: str
    tool: str | None = None
    # Every tool run in the turn, in execution order (`tool` is the first one).
    tools: list[str] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    # The same story the observer showed live (see `presenters/story_view.py`).
    story: list[StoryLine] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    history_compacted: bool = False
    # Web only: raw list references from the final answer call, checked by `web_lists`.
    item_refs: list[Any] = Field(default_factory=list)
