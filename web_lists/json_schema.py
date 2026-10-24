"""`FinalAnswer` as the strict `text.format` of the Responses API."""
from __future__ import annotations

from typing import Any

from .schema.llm.final_answer import FinalAnswer

SCHEMA_NAME = "final_answer_with_lists"
# Pydantic annotations the strict mode does not need.
_DROPPED_KEYWORDS = ("title", "default")


def _strict_fields(properties: dict[str, Any]) -> dict[str, Any]:
    return {name: _strict(value) for name, value in properties.items()}


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(value) for value in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED_KEYWORDS:
            continue
        if key in ("properties", "$defs"):
            out[key] = _strict_fields(value)  # field / model names, not keywords: "title" stays
        else:
            out[key] = _strict(value)
    if "const" in out:
        out["enum"] = [out.pop("const")]
    if "properties" in out:
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out


def json_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": SCHEMA_NAME,
        "strict": True,
        "schema": _strict(FinalAnswer.model_json_schema()),
    }
