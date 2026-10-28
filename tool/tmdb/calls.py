"""Executed calls as shown to the user: the request actually sent, credential masked.

`http_call` (turn.py) records method and the full URL (path and every query parameter) at the point
where `http.py` builds it; only the value of the API key is replaced by `***`. With Bearer
authentication there is no credential in the URL at all (the token travels in a header that is
never recorded).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallRecorder:
    calls: list[dict[str, str]] = field(default_factory=list)

    def record(self, call: dict[str, str]) -> None:
        self.calls.append(call)
