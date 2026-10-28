"""Executed calls as shown to the user: the request actually sent, key masked.

`http_call` (turn.py) records method and the full URL (path and every query parameter, the search
`q` included) where `http.py` builds it; only the value of the key is replaced by `***`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallRecorder:
    calls: list[dict[str, str]] = field(default_factory=list)

    def record(self, call: dict[str, str]) -> None:
        self.calls.append(call)
