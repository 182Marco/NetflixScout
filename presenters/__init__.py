"""Output layer: the only place that decides how a `TurnResult` is shown."""
from __future__ import annotations

from typing import Any

from turn import TurnResult

from . import terminal, web
from .channel import OutputChannel


def present(turn: TurnResult, channel: OutputChannel) -> dict[str, Any] | None:
    if channel is OutputChannel.terminal:
        return terminal.render(turn)
    return web.to_payload(turn)


__all__ = ["OutputChannel", "present"]
