"""Deterministic packing of TMDb results into the LLM context.

`LLMOrchestrator._build_final_context` puts `metadata` in the prompt whole and shows only
`chunks[:10]`, each cut to 600 characters; there is no global limit. The TMDb tool bounds
itself here, without touching the orchestrator or the other tools:

- P0 identity (kind, IDs, title, original title and language, year) opens every chunk
  card and is never cut;
- P1 essentials of detail entities are always kept, each fitted to `ESSENTIALS_CHARS`;
- P2 facet lists, reference lists and extra list results go in, in request order, while
  space remains; every list shown partially is reported in `omitted` as shown/total.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from .models.results import Entity, RequestOutcome
from .normalize.common import truncate
from .operations.reference import JUSTWATCH

MAX_TMDB_CONTEXT_CHARS = 12_000
MAX_CHUNKS = 10  # mirrors `chunks[:10]` in LLMOrchestrator._build_final_context
CARD_CHARS = 400
CARD_TITLE_CHARS = 120
ESSENTIALS_CHARS = 1_000
MIN_TEXT_CHARS = 150
ROW_CHARS = 120
# Room for the omission flags and the `omitted` key itself.
FLAGS_RESERVE = 120

KIND_LABELS = {
    "movie": "Film",
    "tv": "Serie TV",
    "season": "Stagione",
    "episode": "Episodio",
    "person": "Persona",
    "collection": "Raccolta",
    "company": "Casa di produzione",
    "keyword": "Keyword",
}
_LONG_TEXT_FIELDS = ("overview", "biography")
_LOW_PRIORITY_FIELDS = (
    "tagline",
    "also_known_as",
    "poster_url",
    "profile_url",
    "still_url",
    "logo_url",
    "homepage",
    "networks",
    "tmdb_url",
)
_TRIMMABLE_LISTS = ("top_cast", "directors", "created_by", "guest_stars", "genres")


@dataclass(frozen=True)
class PackedContext:
    chunks: list[dict[str, Any]]
    metadata: dict[str, Any]
    attributions: list[str]


def json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


# Operations whose answer depends on the current date.
DATED_OPERATIONS = frozenset({"chart", "discover_movies", "discover_tv"})


def card_text(entity: Entity) -> str:
    """P0 head, never cut; list items add a short summary when there is room."""
    title = truncate(entity.title, CARD_TITLE_CHARS)
    head = [KIND_LABELS.get(entity.kind, entity.kind), f"{title} ({entity.year})" if entity.year else title]
    original = truncate(entity.original_title, CARD_TITLE_CHARS)
    language = f" [{entity.original_language}]" if entity.original_language else ""
    if original and original != entity.title:
        head.append(f"titolo originale: {original}{language}")
    elif entity.original_language:
        head.append(f"lingua originale: {entity.original_language}")
    head.append(f"TMDb {entity.kind}/{entity.tmdb_id}")
    if entity.imdb_id:
        head.append(f"IMDb {entity.imdb_id}")
    if entity.score:
        head.append(f"voto TMDb {entity.score:.1f}/10")
    # List items have no essentials (detail cards carry `release_date` there): without the date a chart of
    # upcoming films cannot answer "what comes out this month".
    if entity.release_date and not entity.essentials:
        head.append(f"uscita {entity.release_date}")
    text = " · ".join(head)
    room = CARD_CHARS - len(text) - 3
    # Detail entities carry their overview in the essentials: no duplicate in the card.
    if entity.summary and not entity.essentials and room > 40:
        text = f"{text} — {truncate(entity.summary, room)}"
    return text


def _chunk(entity: Entity) -> dict[str, Any]:
    return {
        "id": f"tmdb:{entity.key}",
        "testo": card_text(entity),
        "score": float(entity.score or 0.0),
        "source": "tmdb",
        "title": entity.title,
        "release_year": str(entity.year) if entity.year else None,
        "genres": ", ".join(entity.genres) or None,
        "kind": entity.kind,
        "tmdb_id": entity.tmdb_id,
    }


def _chunk_cost(chunk: dict[str, Any]) -> int:
    # What `_build_final_context` prints for one chunk.
    return len(chunk["testo"]) + len(chunk["title"]) + len(chunk["genres"] or "") + 40


def fit_essentials(essentials: dict[str, Any]) -> dict[str, Any]:
    """Shrink P1 to `ESSENTIALS_CHARS`: drop decorations, shorten long texts, trim name lists."""
    fitted = dict(essentials)
    for field in _LOW_PRIORITY_FIELDS:
        if json_size(fitted) <= ESSENTIALS_CHARS:
            break
        fitted.pop(field, None)
    for field in _LONG_TEXT_FIELDS:
        excess = json_size(fitted) - ESSENTIALS_CHARS
        if excess > 0 and isinstance(fitted.get(field), str):
            fitted[field] = truncate(fitted[field], max(MIN_TEXT_CHARS, len(fitted[field]) - excess - 2))
    for field in _TRIMMABLE_LISTS:
        if json_size(fitted) <= ESSENTIALS_CHARS:
            break
        if isinstance(fitted.get(field), list):
            fitted[field] = fitted[field][:3]
    providers = fitted.get("watch_providers")
    if json_size(fitted) > ESSENTIALS_CHARS and isinstance(providers, dict):
        fitted["watch_providers"] = {k: v[:3] if isinstance(v, list) else v for k, v in providers.items()}
    return fitted


def _request_meta(outcome: RequestOutcome) -> dict[str, Any]:
    meta: dict[str, Any] = {"index": outcome.index, "operation": outcome.operation, "status": outcome.status}
    optional = {
        "error": outcome.error,
        "total_results": outcome.total_results,
        "reference_total": outcome.reference_total,
        "candidates": outcome.candidates,
        "skipped_for_budget": outcome.skipped_for_budget,
        "notes": outcome.notes,
        "applied_filters": outcome.applied_filters,
    }
    meta.update({key: value for key, value in optional.items() if value not in (None, [])})
    essentials = {entity.key: {"essentials": fit_essentials(entity.essentials)} for entity in outcome.entities}
    if essentials:
        meta["entities"] = essentials
    return meta


def _row(outcome: RequestOutcome, entity: Entity) -> str:
    year = f" ({entity.year})" if entity.year else ""
    text = f"r{outcome.index} {KIND_LABELS.get(entity.kind, entity.kind)} {entity.title}{year} · TMDb {entity.key}"
    return truncate(text, ROW_CHARS)


class _Packer:
    def __init__(self, metadata: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        self.metadata = metadata
        self.chunks = chunks
        self.used = json_size(metadata) + sum(_chunk_cost(chunk) for chunk in chunks)
        self.limit = MAX_TMDB_CONTEXT_CHARS - FLAGS_RESERVE
        self.omitted: list[str] = []
        self.truncated = False
        self.added: list[tuple[dict[str, Any], str, int, str]] = []

    def add_list(self, container: dict[str, Any], name: str, items: list[Any], total: int, label: str) -> int:
        """Add the longest prefix of `items` that fits; note what is left out. Returns items kept."""
        note_cost = len(f"{label} {name}: {total}/{total}") + 3
        budget = self.limit - note_cost
        kept: list[Any] = []
        header = len(name) + 6
        for item in items:
            cost = json_size(item) + 1 + (0 if kept else header)
            if self.used + cost > budget:
                break
            kept.append(item)
            self.used += cost
        if kept:
            container[name] = kept
            self.added.append((container, name, total, label))
        if len(kept) < len(items):
            self.truncated = True
        if len(kept) < total:
            self.omitted.append(f"{label} {name}: {len(kept)}/{total}")
            self.used += note_cost
        return len(kept)

    def total(self) -> int:
        return json_size(self.metadata) + sum(_chunk_cost(chunk) for chunk in self.chunks)

    def shrink_to_fit(self) -> None:
        """Safety net for estimate drift: drop the last P2 lists until the exact size fits."""
        while self.total() > MAX_TMDB_CONTEXT_CHARS and self.added:
            container, name, total, label = self.added.pop()
            container.pop(name, None)
            prefix = f"{label} {name}:"
            self.omitted = [note for note in self.omitted if not note.startswith(prefix)]
            self.omitted.append(f"{prefix} 0/{total}")
            self.truncated = True
            self.metadata["omitted"] = self.omitted
            self.metadata["context_truncated"] = True


def pack_context(outcomes: list[RequestOutcome], *, api_language: str, status: str) -> PackedContext:
    detail = [(outcome, entity) for outcome in outcomes for entity in outcome.entities]
    listed = [(outcome, entity) for outcome in outcomes for entity in outcome.items]
    # Detail entities first: at most one per request, so always within `MAX_CHUNKS`.
    cards = detail + listed
    shown, overflow = cards[:MAX_CHUNKS], cards[MAX_CHUNKS:]
    chunks = [_chunk(entity) for _, entity in shown]
    requests_meta = [_request_meta(outcome) for outcome in outcomes]
    metadata: dict[str, Any] = {"status": status, "language": api_language, "requests": requests_meta}
    if any(outcome.operation in DATED_OPERATIONS for outcome in outcomes):
        # Charts and discoveries answer "this month" / "recent": the model has no clock of its own.
        metadata["today"] = date.today().isoformat()
    packer = _Packer(metadata, chunks)
    with_data = {outcome.index for outcome, _ in shown}

    for outcome, meta in zip(outcomes, requests_meta):
        for entity in outcome.entities:
            target: dict[str, Any] = {}
            for name, items in entity.facets.items():
                total = entity.facet_totals.get(name, len(items))
                packer.add_list(target, name, items, total, f"r{outcome.index} {entity.key}")
            if target:
                meta["entities"][entity.key]["facets"] = target
    for outcome, meta in zip(outcomes, requests_meta):
        if outcome.reference:
            total = outcome.reference_total or len(outcome.reference)
            if packer.add_list(meta, "reference", outcome.reference, total, f"r{outcome.index}"):
                with_data.add(outcome.index)

    rows: list[str] = []
    for outcome, entity in overflow:
        row = _row(outcome, entity)
        if packer.used + len(row) + 3 > packer.limit:
            break
        rows.append(row)
        packer.used += len(row) + 3
        with_data.add(outcome.index)
    if rows:
        metadata["more_results"] = rows
    if len(rows) < len(overflow):
        packer.omitted.append(f"more_results: {len(rows)}/{len(overflow)}")
        packer.truncated = True

    if packer.omitted:
        metadata["omitted"] = packer.omitted
    metadata["context_truncated"] = packer.truncated
    packer.shrink_to_fit()

    providers_shown = any(
        (entity.essentials.get("watch_providers") or {}).get("available") for _, entity in detail
    )
    credited = any(outcome.attribution == JUSTWATCH and outcome.index in with_data for outcome in outcomes)
    attributions = [JUSTWATCH] if providers_shown or credited else []
    return PackedContext(chunks=chunks, metadata=metadata, attributions=attributions)
