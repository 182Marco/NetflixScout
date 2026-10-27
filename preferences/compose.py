"""Composition of the prompt parts of one turn from the (valid) settings. Pure.

The planner part holds only what steers routing (content type, preferred sources); the answer part
holds everything. Each fragment appears once, so nothing accumulates across turns and nothing is
repeated. The text never leaves the server.
"""
from __future__ import annotations

from . import behavior as b
from .models import Preferences


def _planner_lines(prefs: Preferences) -> list[str]:
    lines: list[str] = []
    content = b.CONTENT_PLANNER.get(prefs["content_type"])
    if content:
        lines.append(content)
    lines.append(b.SOURCES_PLANNER[prefs["preferred_sources"]])
    return lines


def _answer_lines(prefs: Preferences) -> list[str]:
    return [
        b.SPOILER[prefs["spoiler_plot"]],
        b.LENGTH[prefs["response_length"]],
        b.TONE[prefs["response_tone"]],
        b.APPROACH[prefs["approach"]],
        b.CONTENT_ANSWER[prefs["content_type"]],
        b.SOURCES_ANSWER[prefs["preferred_sources"]],
        b.SOURCES_COMMON,
    ]


def build_prompt_parts(prefs: Preferences) -> dict[str, str]:
    """`{"planner": str, "answer": str}`, both non-empty for valid preferences."""
    return {
        "planner": " ".join([b.PLANNER_INTRO, *_planner_lines(prefs)]),
        "answer": " ".join([b.ANSWER_INTRO, *_answer_lines(prefs)]),
    }
