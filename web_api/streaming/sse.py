"""Server-Sent Events wire format and the reading of a turn's queue."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from ..schemas.events import END, End, SseEvent

HEARTBEAT = ": ping\n\n"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def format_sse(event: SseEvent) -> str:
    """`id`, `event` and one `data` line of compact JSON (JSON never contains a raw newline)."""
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.id}\nevent: {event.name}\ndata: {data}\n\n"


async def drain(queue: asyncio.Queue[SseEvent | End], heartbeat_seconds: float) -> AsyncIterator[str]:
    """The wire text of the queue until `END`, with a comment line after each silent interval."""
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
        except asyncio.TimeoutError:
            yield HEARTBEAT
            continue
        if item is END:
            return
        if isinstance(item, SseEvent):
            yield format_sse(item)
