"""Complete RAG results with TMDb metadata for the movies the RAG selected.

The RAG decides which movies are relevant; this module only looks up the selected
candidates (the final, reranked chunks, at most `max_candidates`, in RAG order) and
attaches what TMDb returns for each of them. Chunks and their ranking are never changed.

A candidate gets metadata only when the TMDb movie matches it: same title or original
title (case, spaces and punctuation ignored; never a title merely contained in the other)
and, when the RAG year is known, a TMDb year within ±1. The lookup runs with
`strict_identity`, so several equally good TMDb matches are refused instead of ranked by
popularity. A movie TMDb knows under another title is accepted only if the RAG title is
one of that same work's translated or alternative titles (see `operations/resolve.py`),
the year matches and, when both casts are known, at least one actor is shared; such rows
say `matched_by: alternative_title`. Otherwise its status says why (`unverified`,
`not_found`, `skipped`, `error`) and nothing is attributed. Lookups run in English (`REFERENCE_LANGUAGE`) because corpus titles are
English. One `CallBudget` per enrichment: in a `rag_search` turn `tmdb_search` does not
run, so the TMDb budget stays per turn.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .errors import TmdbConfigError
from .models.enums import TmdbOperation
from .models.requests import TmdbRequest
from .models.results import Entity, RequestOutcome
from .operations.resolve import ALTERNATIVE_TITLE_MATCH, YEAR_FROM_RELEASE_DATES
from .normalize.common import clean_text, normalize_name, positive_minutes, truncate, year_of
from .runner import run_requests
from .settings import REFERENCE_LANGUAGE
from .tool import TmdbTool
from .trace import build_tmdb_trace

ENRICHMENT_KEY = "tmdb_enrichment"
OVERVIEW_CHARS = 400
_SKIPPED_ERRORS = {"call_limit_reached", "rate_limited"}


@dataclass(frozen=True)
class Candidate:
    rank: int
    title: str
    year: int | None
    # Actor names from the corpus metadata (";"-separated in the chunk), when present.
    cast: tuple[str, ...] = ()


def select_candidates(chunks: list[Any], max_candidates: int) -> list[Candidate]:
    """Distinct (title, year) of the final chunks, in RAG order; chunks without a title are skipped."""
    seen: set[tuple[str, int | None]] = set()
    selected: list[Candidate] = []
    for chunk in chunks:
        if len(selected) >= max_candidates:
            break
        if not isinstance(chunk, dict):
            continue
        title = clean_text(chunk.get("title"))
        if not title:
            continue
        year = year_of(str(chunk.get("release_year") or chunk.get("release_date") or ""))
        key = (normalize_name(title), year)
        if key in seen:
            continue
        seen.add(key)
        cast = tuple(name.strip() for name in str(chunk.get("cast") or "").split(";") if name.strip())
        selected.append(Candidate(rank=len(selected) + 1, title=title, year=year, cast=cast))
    return selected


def titles_match(wanted: str, entity: Entity) -> bool:
    """Same title or original title; "The Sinner" never matches "The Sinners"."""
    target = normalize_name(wanted)
    names = {normalize_name(entity.title), normalize_name(entity.original_title)} - {""}
    return bool(target) and target in names


def casts_overlap(candidate_cast: tuple[str, ...], entity: Entity) -> bool | None:
    """True/False when both casts are known, None when one of them is missing."""
    tmdb_cast = {normalize_name(name) for name in entity.essentials.get("top_cast") or []} - {""}
    corpus_cast = {normalize_name(name) for name in candidate_cast} - {""}
    if not tmdb_cast or not corpus_cast:
        return None
    return bool(tmdb_cast & corpus_cast)


def years_match(candidate_year: int | None, entity_year: int | None) -> bool:
    """A known RAG year must be confirmed by a TMDb year within ±1; no RAG year, no check."""
    if candidate_year is None:
        return True
    return entity_year is not None and abs(candidate_year - entity_year) <= 1


def _metadata(entity: Entity) -> dict[str, Any]:
    essentials = entity.essentials
    values = {
        "title": entity.title,
        "original_title": entity.original_title,
        "year": entity.year,
        "directors": essentials.get("directors"),
        "top_cast": essentials.get("top_cast"),
        "overview": truncate(essentials.get("overview"), OVERVIEW_CHARS),
        "runtime_minutes": positive_minutes(essentials.get("runtime_minutes")),
        "genres": entity.genres,
        "tmdb_vote_average": essentials.get("vote_average"),
        "tmdb_vote_count": essentials.get("vote_count"),
        "tmdb_url": essentials.get("tmdb_url"),
    }
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def _candidate_result(candidate: Candidate, outcome: RequestOutcome | None) -> dict[str, Any]:
    row: dict[str, Any] = {"rank": candidate.rank, "rag_title": candidate.title, "rag_year": candidate.year}
    if outcome is None:
        return {**row, "status": "error", "reason": "invalid_request"}
    if outcome.error:
        if outcome.error == "not_found":
            return {**row, "status": "not_found"}
        if outcome.error == "unverified_match":
            reason = outcome.notes[0] if outcome.notes else "unverified_match"
            return {**row, "status": "unverified", "reason": reason}
        if outcome.error in _SKIPPED_ERRORS:
            return {**row, "status": "skipped", "reason": outcome.error}
        return {**row, "status": "error", "reason": outcome.error}
    entity = next(iter(outcome.entities), None)
    if entity is None:
        return {**row, "status": "not_found"}
    # The resolver may have confirmed the year with a secondary TMDb release date.
    if YEAR_FROM_RELEASE_DATES not in outcome.notes and not years_match(candidate.year, entity.year):
        return {**row, "status": "unverified", "reason": "year_mismatch"}
    if ALTERNATIVE_TITLE_MATCH in outcome.notes:
        # Weaker evidence than an exact title: a known cast must confirm the identity.
        if casts_overlap(candidate.cast, entity) is False:
            return {**row, "status": "unverified", "reason": "cast_mismatch"}
        return {**row, "status": "matched", "matched_by": "alternative_title", "tmdb": _metadata(entity),
                **({"year_note": "release_date"} if YEAR_FROM_RELEASE_DATES in outcome.notes else {})}
    if not titles_match(candidate.title, entity):
        return {**row, "status": "unverified", "reason": "title_mismatch"}
    return {**row, "status": "matched", "tmdb": _metadata(entity),
            **({"year_note": "release_date"} if YEAR_FROM_RELEASE_DATES in outcome.notes else {})}


def _attach(tool_result: dict[str, Any], enrichment: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Copy of the result with the enrichment in `metadata` and the calls in `trace`; chunks untouched."""
    return {
        **tool_result,
        "metadata": {**(tool_result.get("metadata") or {}), ENRICHMENT_KEY: enrichment},
        "trace": [*(tool_result.get("trace") or []), *trace],
    }


@dataclass(kw_only=True)
class TmdbRagEnricher:
    """Adds TMDb metadata (title, year, director, cast, overview…) to the movies the RAG selected."""

    tool: TmdbTool
    max_candidates: int

    def enrich(self, *, tool_result: dict[str, Any]) -> dict[str, Any]:
        candidates = select_candidates(tool_result.get("chunks") or [], self.max_candidates)
        if not candidates:
            return tool_result
        try:
            credentials = self.tool._credentials()
        except TmdbConfigError as exc:
            rows = [{"rank": c.rank, "rag_title": c.title, "rag_year": c.year, "status": "skipped", "reason": exc.code} for c in candidates]
            return _attach(tool_result, {"source": "TMDb", "status": "error", "error": exc.code, "candidates": rows}, [])

        # The orchestrator puts the turn id in the result so the enrichment shares the turn budget.
        ctx = self.tool.new_context(
            credentials,
            api_language=REFERENCE_LANGUAGE,
            turn_id=tool_result.get("turn_id"),
        )
        ctx.strict_identity = True
        requests: list[TmdbRequest] = []
        positions: list[int | None] = []
        for candidate in candidates:
            try:
                requests.append(
                    TmdbRequest(operation=TmdbOperation.movie_details, title=candidate.title[:200], year=candidate.year)
                )
                positions.append(len(requests) - 1)
            except ValidationError:
                positions.append(None)
        outcomes = run_requests(ctx, requests) if requests else []
        rows = [
            _candidate_result(candidate, outcomes[position] if position is not None else None)
            for candidate, position in zip(candidates, positions)
        ]
        matched = sum(row["status"] == "matched" for row in rows)
        enrichment = {
            "source": "TMDb",
            "language": REFERENCE_LANGUAGE,
            "status": "ok" if matched == len(rows) else "partial" if matched else "none",
            "candidates": rows,
        }
        return _attach(tool_result, enrichment, build_tmdb_trace(ctx.recorder.calls, []))
