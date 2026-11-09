"""Helper for the tests about the SOURCES part of the planner prompt."""
from __future__ import annotations

from preferences import behavior


def without_content_text(text: str) -> str:
    """The planner prompt without the content-type block, which names the tools on purpose (film / series / both)."""
    for block in behavior.CONTENT_PLANNER.values():
        text = text.replace(block, "")
    return text
