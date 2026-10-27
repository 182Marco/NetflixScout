"""Reference films ("like X, not like Y") represented by REAL vectors: from the index, or from their TMDb plot.

For each cited movie, in this order:

1. the index: `resolve_reference` finds it by title (+ year) and its stored vector is reused (no external call, no
   embedding). Movies added before by this very flow are found the same way, so a repeated request costs nothing;
2. TMDb: a movie the index does not know is resolved by title and year with a verified identity (several equally
   good works are refused, never guessed), its English plot is read, embedded ONCE and stored as a persistent point
   (`CatalogStore.sync`: stable id, version, hashes; a point of the corpus for the same work is linked instead of
   duplicated). A movie without a usable plot gets NO vector (`no_plot`): nothing is invented.

Whatever fails leaves the reference without a vector and says why in the trace; the search then goes on with the
description of the query alone, as before. The vectors become positive / negative examples of the Qdrant search
(`vectorstore.search(references=)`); this module only produces them.

The TMDb reader and the embedding function are injected (`app.py` wires them): this package never imports another
tool domain.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from .references import ReferenceInput, ReferenceSet, ResolvedReference, resolve_reference
from .store import norm_title
from .store.catalog import ERROR, INSERTED, LINKED, METADATA_UPDATED, SKIPPED, UNCHANGED, UPDATED, CatalogRecord, CatalogStore
from .store.qdrant_store import QdrantStore

SOURCE_INDEX, SOURCE_INSERTED, SOURCE_LINKED, SOURCE_REUSED = "index", "tmdb_inserted", "tmdb_linked", "tmdb_reused"
_WRITES = (INSERTED, UPDATED, METADATA_UPDATED)
_DAY_MS = 86_400_000


class ReferenceFlow:
    def __init__(
        self,
        *,
        store: QdrantStore,
        catalog: CatalogStore,
        read_film: Callable[..., Any],
        embed_text: Callable[[str], Sequence[float]],
        strategy: str = "best_score",
        text_repeat: int = 1,
        max_positive: int = 2,
        max_negative: int = 2,
        max_lookups: int = 4,
        refresh_days: int = 180,
        persist: bool = True,
        invalidate: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store, self.catalog = store, catalog
        self.read_film, self.embed_text = read_film, embed_text
        self.strategy, self.text_repeat = strategy, text_repeat
        self.max_positive, self.max_negative = max_positive, max_negative
        self.max_lookups, self.refresh_days, self.persist = max_lookups, refresh_days, persist
        self.invalidate, self.clock = invalidate, clock

    # ---- public
    def resolve(
        self, like: Sequence[ReferenceInput], avoid: Sequence[ReferenceInput], *, turn_id: str | None = None
    ) -> ReferenceSet:
        entries: list[ResolvedReference] = []
        lookups = [0]  # external reads allowed in this turn (new films and refreshes together)
        seen: set[tuple[str, int | None]] = set()
        for refs, role, limit in ((like, "positive", self.max_positive), (avoid, "negative", self.max_negative)):
            used = 0
            for ref in refs:
                key = (norm_title(ref.title), ref.year)
                if key in seen:
                    entries.append(ResolvedReference(ref.title, ref.year, role, "duplicate"))
                    continue
                seen.add(key)
                if used >= limit:
                    entries.append(ResolvedReference(ref.title, ref.year, role, "ignored_over_limit"))
                    continue
                used += 1
                entries.append(self._one(ref, role, turn_id, lookups))
        return ReferenceSet(entries, strategy=self.strategy, text_repeat=max(1, int(self.text_repeat)))

    # ---- one reference
    def _one(self, ref: ReferenceInput, role: str, turn_id: str | None, lookups: list[int]) -> ResolvedReference:
        try:
            entry = resolve_reference(self.store, ref, role)
        except Exception as exc:  # noqa: BLE001  (an index error must not break the search)
            entry = ResolvedReference(ref.title, ref.year, role, "unavailable")
            entry.detail = {"reason": f"index_error:{type(exc).__name__}"}
            return entry
        if entry.status == "resolved":
            entry.detail = {"origin": "catalog" if str(entry.legacy_id).startswith("tmdb:") else "corpus",
                            "tmdb_calls": 0, "embedding_created": False}
            self._maybe_refresh(entry, turn_id, lookups)
            return entry
        if entry.status in ("not_in_index", "ambiguous") and self.persist and lookups[0] < self.max_lookups:
            lookups[0] += 1
            return self._acquire(entry, ref, turn_id)
        entry.detail = {"reason": "lookup_limit" if self.persist else "persistence_off", "tmdb_calls": 0,
                        "embedding_created": False}
        return entry

    def _acquire(self, entry: ResolvedReference, ref: ReferenceInput, turn_id: str | None) -> ResolvedReference:
        read = self.read_film(title=ref.title, year=ref.year, tmdb_id=None, turn_id=turn_id)
        detail: dict[str, Any] = {"tmdb_calls": read.calls, "embedding_created": False}
        entry.detail = detail
        if read.record is None:
            entry.status = "ambiguous" if str(read.reason).endswith("ambiguous") else "unavailable"
            detail["reason"] = read.reason
            return entry
        embeds = [0]

        def counting_embed(text: str):
            embeds[0] += 1
            return self.embed_text(text)

        try:
            outcome = self.catalog.sync(CatalogRecord(**read.record), counting_embed)
        except Exception as exc:  # noqa: BLE001  (embedding / Qdrant failures: no vector, search goes on)
            entry.status, detail["reason"] = "unavailable", f"sync_error:{type(exc).__name__}"
            return entry
        detail.update(outcome=outcome.status, tmdb_id=read.tmdb_id, embedding_created=embeds[0] > 0)
        if outcome.reason:
            detail["reason"] = outcome.reason
        if outcome.status == SKIPPED:
            if outcome.reason in ("no_english_overview", "overview_too_short"):
                entry.status = "no_plot"
            else:
                entry.status = "ambiguous" if outcome.reason.startswith("ambiguous") else "unavailable"
            return entry
        if outcome.status == ERROR:
            entry.status = "unavailable"
            return entry
        record = self.catalog.read_by_tmdb_id(read.tmdb_id) if read.tmdb_id is not None else None
        payload = (record.payload or {}) if record else {}
        legacy_id = payload.get("legacy_id")
        vector = self.store.vector_of(legacy_id) if legacy_id else None
        if vector is None:
            entry.status, detail["reason"] = "unavailable", "point_not_found_after_write"
            return entry
        if outcome.status in _WRITES and self.invalidate:
            try:
                self.invalidate()
            except Exception:  # noqa: BLE001
                detail["bm25"] = "not_invalidated"
        homonyms = [c.get("movie_id") for c in entry.candidates if c.get("movie_id")]
        entry.status, entry.vector = "resolved", vector
        entry.legacy_id, entry.movie_id = legacy_id, payload.get("movie_id")
        entry.matched_title, entry.matched_year = payload.get("title"), _year(payload.get("release_year"))
        entry.homonym_movie_ids = homonyms
        entry.source = (SOURCE_LINKED if outcome.status == LINKED or payload.get("source") != "tmdb"
                        else SOURCE_INSERTED if outcome.status in _WRITES else SOURCE_REUSED)
        return entry

    def _maybe_refresh(self, entry: ResolvedReference, turn_id: str | None, lookups: list[int]) -> None:
        """A plot read from TMDb long ago is read again (best effort): TMDb summaries get corrected."""
        legacy_id = str(entry.legacy_id or "")
        if not legacy_id.startswith("tmdb:movie:") or self.refresh_days <= 0 or lookups[0] >= self.max_lookups:
            return
        try:
            point = self.catalog.read_point(legacy_id)
            fetched = int((point.payload or {}).get("fetched_ts") or 0) if point else 0
            if fetched and (self.clock() * 1000 - fetched) / _DAY_MS < self.refresh_days:
                return
            lookups[0] += 1
            read = self.read_film(title=None, year=None, tmdb_id=int(legacy_id.rsplit(":", 1)[1]), turn_id=turn_id)
            entry.detail["tmdb_calls"] = read.calls
            if read.record is None:
                entry.detail["refresh"] = f"failed:{read.reason}"
                return
            embeds = [0]

            def counting_embed(text: str):
                embeds[0] += 1
                return self.embed_text(text)

            outcome = self.catalog.sync(CatalogRecord(**read.record), counting_embed)
            entry.detail.update(refresh=outcome.status, embedding_created=embeds[0] > 0)
            if outcome.status in _WRITES:
                entry.vector = self.store.vector_of(legacy_id) or entry.vector
                if self.invalidate:
                    self.invalidate()
        except Exception as exc:  # noqa: BLE001  (the stored vector keeps being used)
            entry.detail["refresh"] = f"error:{type(exc).__name__}"


def _year(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() and len(text) == 4 else None


def references_summary(refs: ReferenceSet | None) -> list[str]:
    """One readable line per reference for the final prompt: what was really used, and what was not."""
    if refs is None:
        return []
    lines = []
    for e in refs.entries:
        role = "like" if e.role == "positive" else "avoid"
        if e.status == "resolved":
            how = {"index": "its vector from the index", SOURCE_INSERTED: "a vector made from its TMDb plot (new)",
                   SOURCE_LINKED: "its corpus vector, linked to TMDb", SOURCE_REUSED: "its stored TMDb-plot vector"
                   }.get(e.source or "", "a stored vector")
            lines.append(f"{role} '{e.title}': used, {how}")
        else:
            lines.append(f"{role} '{e.title}': NOT used as a vector ({e.status}"
                         + (f": {e.detail.get('reason')}" if e.detail.get("reason") else "") + ")")
    return lines
