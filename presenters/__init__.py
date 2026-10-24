"""Output layer: the only place that decides how a `TurnResult` is shown."""
from __future__ import annotations

from typing import Any

from turn import TurnResult

from . import terminal, web
from .channel import OutputChannel


def present(turn: TurnResult, channel: OutputChannel, *, streamed: bool = False) -> dict[str, Any] | None:
    """Show a finished turn. `streamed`: the channel's observer already showed the steps live,
    so only the end of the turn (answer, compaction notice) is left to show."""
    if channel is OutputChannel.terminal:
        return terminal.render(turn, streamed=streamed)
    return web.to_payload(turn)


__all__ = ["OutputChannel", "present"]
