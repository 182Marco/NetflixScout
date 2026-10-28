"""Executed calls as shown to the user: the request actually sent, key masked.

`http_call` (turn.py) records method and the full URL (every query parameter: the title searched, the
IMDb ID) where `http.py` builds it; only the value of `apikey` is replaced by `***`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallRecorder:
    calls: list[dict[str, str]] = field(default_factory=list)

    def record(self, call: dict[str, str]) -> None:
        self.calls.append(call)
