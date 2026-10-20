"""Turn a natural language request into a validated `MovieDbQuery`.

The LLM only fills the fields of a closed operation: its output is parsed as JSON and
validated by Pydantic (unknown keys, operations or genres are rejected). It never
produces SQL, so nothing it writes is executed.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from movie_db.config import ParserConfig
from movie_db.schema import GENRES

from .models import MovieDbQuery


class MovieDbParseError(ValueError):
    """The request could not be turned into a whitelisted operation."""


def _instructions(settings: ParserConfig) -> str:
    return settings.instructions.replace("{genres}", ", ".join(GENRES))


def _json_payload(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise MovieDbParseError("Parser output is not a JSON object.")
    return payload


def parse_query(query: str, settings: ParserConfig, client: Any) -> MovieDbQuery:
    try:
        response = client.responses.create(
            model=settings.model,
            instructions=_instructions(settings),
            input=query,
        )
        payload = _json_payload(response.output_text or "")
    except MovieDbParseError:
        raise
    except Exception as exc:
        raise MovieDbParseError(f"Parser call failed: {exc}") from exc

    try:
        return MovieDbQuery.model_validate(payload)
    except ValidationError as exc:
        raise MovieDbParseError(f"Parser output rejected: {exc.error_count()} invalid field(s).") from exc
