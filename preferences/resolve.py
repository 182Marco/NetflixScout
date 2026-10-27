"""Validation of the settings a request carries. Pure: it never raises and never logs.

Rules: nothing sent means every default; a missing field, a wrong type or a value that is not an
option falls back to the default of that field alone, the other valid fields are kept; fields the
server does not know are ignored. Every fallback is reported as an `Issue` for the caller to log.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Preferences, defaults
from .public import field_definitions

CODE_NOT_OBJECT = "not_object"
CODE_INVALID_TYPE = "invalid_type"
CODE_UNKNOWN_VALUE = "unknown_value"
CODE_UNKNOWN_FIELD = "unknown_field"

MAX_REPORTED_CHARS = 40


@dataclass(frozen=True)
class Issue:
    """`field` is the field id (or the unknown key); `value` is a short, escaped copy for logs."""

    field: str
    code: str
    value: str = ""


@dataclass(frozen=True)
class Resolution:
    preferences: Preferences
    issues: list[Issue] = field(default_factory=list)

    @property
    def ignored(self) -> list[str]:
        """Names of the known fields that fell back to their default (not the unknown keys)."""
        known = {f["id"] for f in field_definitions()}
        return [issue.field for issue in self.issues if issue.field in known]


def _shown(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= MAX_REPORTED_CHARS else text[:MAX_REPORTED_CHARS] + "…"


def _check(definition: dict[str, Any], value: Any) -> str | None:
    """The code of the problem with `value`, or None if it is valid for the field."""
    if definition["type"] == "boolean":
        return None if isinstance(value, bool) else CODE_INVALID_TYPE
    if not isinstance(value, str):
        return CODE_INVALID_TYPE
    allowed = {option["value"] for option in definition["options"]}
    return None if value in allowed else CODE_UNKNOWN_VALUE


def resolve_preferences(raw: Any) -> Resolution:
    """`raw` is whatever the request carried under `preferences` (absent: `None`)."""
    base = defaults().as_dict()
    if raw is None:
        return Resolution(Preferences(base))
    if not isinstance(raw, dict):
        return Resolution(Preferences(base), [Issue("preferences", CODE_NOT_OBJECT, _shown(raw))])

    values = dict(base)
    issues: list[Issue] = []
    known = set()
    for definition in field_definitions():
        field_id = definition["id"]
        known.add(field_id)
        if field_id not in raw:
            continue
        problem = _check(definition, raw[field_id])
        if problem is None:
            values[field_id] = raw[field_id]
        else:
            issues.append(Issue(field_id, problem, _shown(raw[field_id])))
    issues.extend(Issue(_shown(key), CODE_UNKNOWN_FIELD) for key in raw if key not in known)
    return Resolution(Preferences(values), issues)
