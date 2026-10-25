"""Executed calls as shown to the user: endpoint URL only, key masked.

The display URL is rebuilt from `BASE_URL` and the endpoint path, never from the URL
actually sent: search parameters are left out and the key is always `***`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .settings import BASE_URL

MASK = "***"


def display_url(path: str) -> str:
    return f"{BASE_URL}{path}?key={MASK}"


@dataclass
class CallRecorder:
    calls: list[str] = field(default_factory=list)

    def record(self, url: str) -> None:
        self.calls.append(url)
