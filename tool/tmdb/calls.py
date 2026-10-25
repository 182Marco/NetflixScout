"""Executed calls as shown to the user: endpoint URL only, credential masked.

The display URL is rebuilt from the base URL and the endpoint path, never from the URL
actually sent: search parameters and `append_to_response` are left out, and with Bearer
authentication there is no credential in the URL at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .auth import AuthMode, TmdbCredentials

MASK = "***"


def display_url(credentials: TmdbCredentials, path: str) -> str:
    url = f"{credentials.base_url}{path}"
    if credentials.mode is AuthMode.query:
        return f"{url}?api_key={MASK}"
    return url


@dataclass
class CallRecorder:
    calls: list[str] = field(default_factory=list)

    def record(self, url: str) -> None:
        self.calls.append(url)
