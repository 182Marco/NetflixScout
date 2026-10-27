"""User settings applied per turn: public field definitions, validation and prompt composition.

`fields.json` is the one source of ids, options and defaults (and is what the client receives);
`behavior.py` holds the private instructions; `resolve.py` validates a raw request value; `compose.py`
turns the result into the two plain-text prompt parts the orchestrator receives.
"""
from .compose import build_prompt_parts
from .models import Preferences, defaults
from .public import public_schema
from .resolve import Issue, Resolution, resolve_preferences

__all__ = [
    "Issue",
    "Preferences",
    "Resolution",
    "build_prompt_parts",
    "defaults",
    "public_schema",
    "resolve_preferences",
]
