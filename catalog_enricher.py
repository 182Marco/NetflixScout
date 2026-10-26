"""Add to the vector catalog the movies a `tmdb_search` turn has just verified on TMDb.

A neutral bridge between two domains that must not know each other: it imports nothing from `tool/`
and receives what it needs as functions (`app.py` wires them). It only acts on `movie_details`
requests that TMDb answered cleanly and with a verified identity, at most `max_per_turn` movies per
turn, and records the outcome only in the trace of the tool (never in `metadata`, which reaches the
final prompt). Whatever happens inside, the tool result comes back unchanged apart from that
trace entry: an error here must never become `enrichment_error` in the prompt.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

TRACE_KIND = "tmdb_calls"
TRACE_KEY = "catalog"
OPERATION = "movie_details"
MAX_TURNS_REMEMBERED = 64

ReadRecord = Callable[[int, "str | None"], "tuple[dict[str, Any] | None, str]"]
Sync = Callable[[dict[str, Any]], Any]


class CatalogEnricher:
    def __init__(
        self,
        *,
        read_record: ReadRecord,
        sync: Sync,
        invalidate: Callable[[], None] | None = None,
        blocking_notes: Iterable[str] = (),
        max_per_turn: int = 2,
        budget_seconds: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.read_record = read_record
        self.sync = sync
        self.invalidate = invalidate
        self.blocking_notes = frozenset(blocking_notes)
        self.max_per_turn = max_per_turn
        self.budget_seconds = budget_seconds
        self.clock = clock
        self._done: OrderedDict[str, set[int]] = OrderedDict()
        self._lock = threading.Lock()

    # ---- selection
    def eligible(self, tool_result: dict[str, Any]) -> list[int]:
        """TMDb ids of clean `movie_details` requests (verified identity, no error, nothing skipped)."""
        requests = ((tool_result.get("metadata") or {}).get("tmdb") or {}).get("requests") or []
        found: list[int] = []
        for req in requests:
            if not isinstance(req, dict) or req.get("operation") != OPERATION or req.get("status") != "ok":
                continue
            if req.get("error") or req.get("candidates") or req.get("skipped_for_budget"):
                continue
            if self.blocking_notes & set(req.get("notes") or []):
                continue
            for key in (req.get("entities") or {}):
                kind, _, raw = str(key).partition(":")
                if kind == "movie" and raw.isdigit() and int(raw) not in found:
                    found.append(int(raw))
        return found

    def _claim(self, turn_id: str | None, ids: list[int]) -> list[int]:
        """Ids still allowed in this turn (cap and repeats), remembered per turn."""
        key = turn_id or ""
        with self._lock:
            done = self._done.setdefault(key, set())
            self._done.move_to_end(key)
            while len(self._done) > MAX_TURNS_REMEMBERED:
                self._done.popitem(last=False)
            chosen = []
            for tmdb_id in ids:
                if tmdb_id in done or len(done) >= self.max_per_turn:
                    continue
                done.add(tmdb_id)
                chosen.append(tmdb_id)
            return chosen

    # ---- the Enricher contract
    def enrich(self, *, tool_result: dict[str, Any]) -> dict[str, Any]:
        try:
            ids = self._claim(tool_result.get("turn_id"), self.eligible(tool_result))
            if not ids:
                return tool_result
            started = self.clock()
            outcomes = [self._one(tmdb_id, tool_result.get("turn_id"), started) for tmdb_id in ids]
            return self._with_trace(tool_result, outcomes)
        except Exception:  # noqa: BLE001  (never let the bridge break or poison the turn)
            return tool_result

    def _one(self, tmdb_id: int, turn_id: str | None, started: float) -> dict[str, Any]:
        def over() -> bool:
            return self.clock() - started > self.budget_seconds

        try:
            if over():
                return {"status": "error", "reason": "timeout", "tmdb_id": tmdb_id}
            record, reason = self.read_record(tmdb_id, turn_id)
            if record is None:
                return {"status": "skipped", "reason": reason or "no_record", "tmdb_id": tmdb_id}
            if over():
                return {"status": "error", "reason": "timeout", "tmdb_id": tmdb_id}
            outcome = self.sync(record)
            data = outcome.as_trace() if hasattr(outcome, "as_trace") else dict(outcome)
            data.setdefault("tmdb_id", tmdb_id)
            if data.get("status") in ("inserted", "updated", "metadata_updated") and self.invalidate:
                try:
                    self.invalidate()
                except Exception:  # noqa: BLE001
                    data["bm25"] = "not_invalidated"
            return data
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": type(exc).__name__, "tmdb_id": tmdb_id}

    @staticmethod
    def _with_trace(tool_result: dict[str, Any], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        """A copy of the trace with the outcomes in the existing TMDb step; no step, no diagnostics."""
        trace = []
        placed = False
        for step in tool_result.get("trace") or []:
            if not placed and isinstance(step, dict) and step.get("kind") == TRACE_KIND:
                step = {**step, "data": {**(step.get("data") or {}), TRACE_KEY: outcomes}}
                placed = True
            trace.append(step)
        return {**tool_result, "trace": trace} if placed else tool_result
