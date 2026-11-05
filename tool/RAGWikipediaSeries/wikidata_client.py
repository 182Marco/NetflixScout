"""Wikidata API client backed by a snapshot of the ORIGINAL responses.

Every response body is stored byte for byte (gzip-compressed on disk, SHA-256 of the uncompressed
bytes in the index). Metadata are always derived from the snapshot by pure functions, so a
rebuild with the same snapshot never touches the network and never depends on today's Wikidata.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import WikidataConfig

log = logging.getLogger("ragwiki.wikidata")

Transport = Callable[..., tuple[int, dict[str, str], bytes]]  # (url, headers, timeout, data=None)


class SnapshotMiss(RuntimeError):
    """A response is needed but absent from the snapshot while the mode forbids the network."""


class WikidataError(RuntimeError):
    pass


def request_key(params: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def urllib_transport(
    url: str, headers: dict[str, str], timeout: float, data: bytes | None = None
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers, data=data)  # data given -> POST
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


class Snapshot:
    """Directory with `requests.jsonl` (index) and `bodies/<sha256>.json.gz`."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.index_path = directory / "requests.jsonl"
        self.bodies = directory / "bodies"
        self.index: dict[str, dict] = {}
        if self.index_path.exists():
            for line in self.index_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.index[entry["key"]] = entry

    def has(self, key: str) -> bool:
        return key in self.index

    def read(self, key: str) -> bytes:
        entry = self.index[key]
        data = gzip.decompress((self.bodies / f"{entry['sha256']}.json.gz").read_bytes())
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise WikidataError(f"snapshot body corrupted for request {key[:12]}")
        return data

    def write(self, key: str, endpoint: str, params: dict[str, str], status: int, body: bytes) -> None:
        self.bodies.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(body).hexdigest()
        target = self.bodies / f"{digest}.json.gz"
        if not target.exists():
            target.write_bytes(gzip.compress(body, compresslevel=6, mtime=0))
        entry = {
            "key": key,
            "endpoint": endpoint,
            "params": params,
            "status": status,
            "sha256": digest,
            "bytes": len(body),
            "acquired_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        self.index[key] = entry


class WikidataClient:
    def __init__(
        self,
        cfg: WikidataConfig,
        snapshot: Snapshot,
        *,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cfg.mode not in {"offline", "online"}:
            raise ValueError("wikidata.mode must be 'offline' or 'online'")
        self.cfg, self.snapshot = cfg, snapshot
        self._transport, self._sleep, self._clock = transport, sleep, clock
        self._last_request = float("-inf")
        self.network_requests = 0
        self.snapshot_hits = 0

    def _headers(self) -> dict[str, str]:
        if not self.cfg.contact.strip():
            raise WikidataError(
                "wikidata.contact is empty: the Wikimedia User-Agent policy requires a contact "
                "(URL or e-mail of who runs the pipeline). Set it in a local config override."
            )
        agent = f"{self.cfg.user_agent_name} ({self.cfg.contact.strip()})"
        return {"User-Agent": agent, "Accept-Encoding": "identity"}

    def get_json(self, params: dict[str, str]) -> dict:
        """MediaWiki API request (GET). Snapshot first; the network only in online mode."""
        params = {**params, "format": "json"}
        key = request_key(params)
        cached = self._from_snapshot(key, params)
        if cached is not None:
            return cached
        query = urllib.parse.urlencode({**params, "maxlag": str(self.cfg.maxlag)})
        body = self._send(f"{self.cfg.api_url}?{query}", None, self.cfg.timeout_seconds, _check_api_payload, {})
        self.snapshot.write(key, self.cfg.api_url, params, 200, body)
        return json.loads(body)

    def sparql_json(self, query: str) -> dict:
        """SPARQL request (POST) to the Query Service. The snapshot key covers the full query text."""
        params = {"endpoint": "sparql", "query": query, "format": "json"}
        key = request_key(params)
        cached = self._from_snapshot(key, params)
        if cached is not None:
            return cached
        data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
        extra = {"Accept": "application/sparql-results+json", "Content-Type": "application/x-www-form-urlencoded"}
        body = self._send(self.cfg.sparql_url, data, self.cfg.sparql_timeout_seconds, _check_sparql_payload, extra)
        self.snapshot.write(key, self.cfg.sparql_url, params, 200, body)
        return json.loads(body)

    def _from_snapshot(self, key: str, params: dict[str, str]) -> dict | None:
        if self.snapshot.has(key):
            self.snapshot_hits += 1
            return json.loads(self.snapshot.read(key))
        if self.cfg.mode == "offline":
            what = params.get("action") or params.get("endpoint")
            raise SnapshotMiss(
                f"response {key[:12]} ({what}) is not in snapshot '{self.snapshot.directory.name}' "
                "and mode is offline"
            )
        return None

    def _send(self, url: str, data: bytes | None, timeout: float, check, extra_headers: dict[str, str]) -> bytes:
        headers = {**self._headers(), **extra_headers}
        last = "no attempt"
        for attempt in range(1, self.cfg.max_retries + 1):
            wait = self.cfg.min_interval_seconds - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = self._clock()
            self.network_requests += 1
            try:
                status, response_headers, body = self._transport(url, headers, timeout, data)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as error:
                status, response_headers, body = 0, {}, b""
                last = f"network error: {type(error).__name__}"
            else:
                last = f"HTTP {status}"
                if status == 200:
                    verdict = check(body)  # None = good, "retry:<why>" = transient, anything else = fatal
                    if verdict is None:
                        return body
                    if not verdict.startswith("retry:"):
                        raise WikidataError(f"Wikidata rejected the request: {verdict}") from None
                    last = verdict[6:]
                elif status not in {0, 429} and status < 500:
                    raise WikidataError(f"Wikidata request rejected: HTTP {status}") from None
            retry_after = response_headers.get("retry-after", "")
            delay = float(retry_after) if retry_after.isdigit() else self.cfg.retry_backoff_seconds * 2 ** (attempt - 1)
            log.warning("wikidata attempt %d failed (%s); waiting %.1fs", attempt, last, delay)
            self._sleep(min(delay, 120.0))
        raise WikidataError(f"Wikidata request failed after {self.cfg.max_retries} attempts ({last})") from None


def _check_api_payload(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except ValueError:
        return "retry:invalid JSON"
    code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
    if code is None:
        return None
    return "retry:API error maxlag" if code == "maxlag" else f"API error {code}"


def _check_sparql_payload(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except ValueError:
        return "retry:invalid JSON"
    if isinstance(payload, dict) and isinstance(payload.get("results", {}).get("bindings"), list):
        return None
    return "retry:unexpected SPARQL response"
