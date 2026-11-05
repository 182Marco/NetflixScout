"""The ONLY network code of phase 4: a polite, sequential Wikidata client with checkpointing.

Rules (Wikimedia API etiquette): descriptive User-Agent with the repository (no personal e-mail), one request at a time, at least
`MIN_INTERVAL` seconds between requests, `maxlag` on the MediaWiki API, `Retry-After` honoured on 429/503, a bounded number of retries with
growing waits, and a circuit breaker that stops the whole run after `MAX_CONSECUTIVE_FAILURES` failed requests in a row. Nothing outside
the two allowed endpoints can be requested. The transport is injectable so tests never touch the network.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cinema_db.harness.enrich.store import PhaseStore, request_key

API_URL = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"
ALLOWED = {API_URL, SPARQL_URL}
USER_AGENT = "NetflixScout-cinema-db/1.0 (https://github.com/182Marco/NetflixScout; one-off offline enrichment, sequential) python-urllib"
MIN_INTERVAL = 1.2
TIMEOUT = 70.0
MAX_BYTES = 40_000_000
MAX_ATTEMPTS = 4
BACKOFF = (5.0, 20.0, 60.0)
RETRY_AFTER_MAX = 180.0
MAX_CONSECUTIVE_FAILURES = 4


class CircuitOpen(RuntimeError):
    """Too many failures in a row: the run stops and can be resumed later."""


@dataclass
class Response:
    status: int
    body: bytes
    retry_after: float | None = None


def urllib_transport(method: str, url: str, data: bytes | None, headers: dict[str, str], timeout: float) -> Response:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - allowlisted https endpoints only
            body = r.read(MAX_BYTES + 1)
            return Response(r.status, body)
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        try:
            wait = float(ra) if ra is not None else None
        except ValueError:
            wait = None
        return Response(e.code, b"", wait)


class Client:
    def __init__(self, store: PhaseStore, *, transport: Callable[..., Response] = urllib_transport, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, min_interval: float = MIN_INTERVAL, log: Callable[[str], None] = print) -> None:
        self.store, self.transport, self.sleep, self.clock, self.min_interval, self.log = store, transport, sleep, clock, min_interval, log
        self._last = 0.0
        self.failures_in_a_row = 0
        self.stats = {"sent": 0, "stored": 0, "reused": 0, "retried": 0, "failed": 0, "bytes": 0}

    def _pace(self) -> None:
        wait = self.min_interval - (self.clock() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = self.clock()

    def _once(self, endpoint: str, params: dict[str, Any]) -> tuple[int, bytes, float | None, str | None]:
        self._pace()
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"}
        if endpoint == SPARQL_URL:
            data = urllib.parse.urlencode({k: v for k, v in params.items() if k != "endpoint"}).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = self.transport("POST", endpoint, data, headers, TIMEOUT)
        else:
            r = self.transport("GET", endpoint + "?" + urllib.parse.urlencode({**params, "maxlag": 5}), None, headers, TIMEOUT)
        self.stats["sent"] += 1
        if r.status == 200 and len(r.body) > MAX_BYTES:
            return r.status, b"", None, "response_too_large"
        if r.status == 200 and endpoint == API_URL:
            try:
                err = json.loads(r.body).get("error")
            except ValueError:
                return r.status, b"", None, "not_json"
            if err:
                return r.status, b"", r.retry_after or 5.0, f"api_error:{err.get('code')}"
        if r.status == 200:
            try:
                json.loads(r.body)
            except ValueError:
                return r.status, b"", None, "not_json"
        return r.status, r.body, r.retry_after, None

    def fetch(self, endpoint: str, params: dict[str, Any], meta: dict[str, Any]) -> str | None:
        """Request once (with bounded retries) and store the response; returns the key, or None when it failed for good."""
        if endpoint not in ALLOWED:
            raise ValueError("endpoint not allowed")
        key = request_key(endpoint, params)
        if self.store.has(key):
            self.stats["reused"] += 1
            return key
        reason = "unknown"
        status: int | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                status, body, retry_after, problem = self._once(endpoint, params)
            except (TimeoutError, urllib.error.URLError, OSError) as e:
                status, body, retry_after, problem = None, b"", None, f"network:{type(e).__name__}"
            if status == 200 and problem is None:
                self.store.save(endpoint, params, body, status, meta)
                self.stats["stored"] += 1
                self.stats["bytes"] += len(body)
                self.failures_in_a_row = 0
                return key
            reason = problem or f"http_{status}"
            retryable = status in (None, 429, 500, 502, 503, 504) or (problem or "").startswith("api_error:maxlag") or problem == "network"
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                break
            self.stats["retried"] += 1
            wait = min(retry_after if retry_after is not None else BACKOFF[min(attempt, len(BACKOFF) - 1)], RETRY_AFTER_MAX)
            self.log(f"  retry {attempt + 1} after {wait:.0f}s ({reason})")
            self.sleep(wait)
        self.store.error(endpoint, params, status, reason, meta)
        self.stats["failed"] += 1
        self.failures_in_a_row += 1
        self.log(f"  FAILED {meta.get('category')}/{meta.get('batch')}: {reason}")
        if self.failures_in_a_row >= MAX_CONSECUTIVE_FAILURES:
            raise CircuitOpen(f"{self.failures_in_a_row} failed requests in a row; stopping (resume later, nothing is lost)")
        return None
