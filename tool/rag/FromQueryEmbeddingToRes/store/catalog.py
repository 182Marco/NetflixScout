"""Catalog writes: films cited by the user that the corpus lacks, read from TMDb and stored in Qdrant.

Every write to a TMDb point is a compare-and-set on its `version`: creation only if the point is
absent, an update only if the version read is still the current one. The server does not say
whether a conditional write was applied, so each write carries a random `write_id` and the point is
read back to learn the outcome. That read only reports and lets the caller retry; the guarantee is
the server's atomic evaluation of the condition, which `tests/test_qdrant_catalog_server.py`
checks against a real server (it is not assumed).

CMU points are never rewritten: linking one to a TMDb id only sets `tmdb_id`, and only while it is
empty. No import from `tool.*` or from the retrieval code: the record arrives as a `CatalogRecord`.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from qdrant_client import QdrantClient, models

from .genre_map import corpus_genres
from .ids import norm_name, norm_title, point_uuid, tmdb_legacy_id, year_int
from .qdrant_store import build_payload

MIN_OVERVIEW_CHARS = 100
MAX_ATTEMPTS = 5
MIN_CAST_FOR_VETO = 3
SOURCE = "tmdb"

INSERTED, UPDATED, METADATA_UPDATED, LINKED = "inserted", "updated", "metadata_updated", "linked"
UNCHANGED, SKIPPED, ERROR = "unchanged", "skipped", "error"


@dataclass(frozen=True)
class CatalogRecord:
    """What `film_record` reads from TMDb for one movie, in English (`en-US`)."""

    tmdb_id: int
    title: str
    overview: str | None
    year: int | None
    fetched_ts: int
    original_title: str | None = None
    alternative_titles: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    cast: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    release_date: str = ""
    # Every release year TMDb records (premieres, other countries): a corpus year may match any.
    release_years: tuple[int, ...] = ()


@dataclass(frozen=True)
class CatalogOutcome:
    status: str
    reason: str = ""
    tmdb_id: int | None = None
    attempts: int = 0

    def as_trace(self) -> dict:
        data = {"status": self.status, "tmdb_id": self.tmdb_id}
        if self.reason:
            data["reason"] = self.reason
        return data


@dataclass(frozen=True)
class Candidate:
    """A CMU point that could be the same film (found by title)."""

    point_id: str
    title_norm: str
    year: int | None
    cast: tuple[str, ...]
    tmdb_id: int | None
    via_alternative: bool = False
    title: str = ""  # the corpus title as written (articles kept): tells "Contact" from "The Contact"


@dataclass(frozen=True)
class LinkDecision:
    action: str  # "insert" | "link" | "ambiguous"
    target: Candidate | None = None
    reason: str = ""


# ---- pure: text, metadata, hashes
def embedding_text(record: CatalogRecord) -> str | None:
    """The overview and nothing else; None when it is missing or too short to place in the space."""
    text = (record.overview or "").strip()
    return text if len(text) >= MIN_OVERVIEW_CHARS else None


def metadata_for(record: CatalogRecord) -> dict[str, str]:
    """Metadata as strings in the shape of the corpus (empty values omitted)."""
    values = {
        "source": SOURCE,
        "movie_id": tmdb_legacy_id(record.tmdb_id),
        "title": record.title.strip(),
        "release_date": record.release_date,
        "release_year": str(record.year) if record.year else "",
        "genres": "; ".join(corpus_genres(record.genres)),
        "languages": "; ".join(record.languages),
        "countries": "; ".join(record.countries),
        "cast": "; ".join(record.cast),
    }
    return {key: value for key, value in values.items() if value}


def text_hash(model: str, dimension: int, text: str) -> str:
    return hashlib.sha256(json.dumps([model, dimension, text], ensure_ascii=False).encode()).hexdigest()


def meta_hash(payload: dict) -> str:
    """Hash of what describes the film (everything except document, hashes and write bookkeeping)."""
    skip = {"document", "version", "write_id", "fetched_ts", "text_hash", "meta_hash"}
    body = {k: v for k, v in payload.items() if k not in skip}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def full_payload(record: CatalogRecord, text: str, *, model: str, dimension: int, version: int, write_id: str) -> dict:
    """The only constructor of a catalog payload: deterministic apart from `version` and `write_id`."""
    payload = build_payload(tmdb_legacy_id(record.tmdb_id), metadata_for(record), text)
    payload["tmdb_id"] = int(record.tmdb_id)
    payload["text_hash"] = text_hash(model, dimension, text)
    payload["meta_hash"] = meta_hash(payload)
    payload["fetched_ts"] = int(record.fetched_ts)
    payload["version"] = int(version)
    payload["write_id"] = write_id
    return payload


# ---- pure: duplicates
def cast_overlap(record_cast: Sequence[str], candidate_cast: Sequence[str]) -> bool | None:
    """True/False when both casts are known, None when one of them is missing."""
    mine = {norm_name(n) for n in record_cast} - {""}
    theirs = {norm_name(n) for n in candidate_cast} - {""}
    if not mine or not theirs:
        return None
    return bool(mine & theirs)


def _narrow(record: CatalogRecord, kept: list[tuple["Candidate", int | None]]) -> list[tuple["Candidate", int | None]]:
    """Several corpus films collapse to the same normalised title and year. Two facts the corpus can confirm tell them
    apart: the title exactly as written (articles kept) and, failing that, an actor in common. Anything else stays ambiguous."""
    wanted = {str(t).strip().casefold() for t in (record.title, record.original_title) if t}
    exact = [item for item in kept if item[0].title.strip().casefold() in wanted]
    if len(exact) == 1:
        return exact
    pool = exact or kept
    shared = [item for item in pool if cast_overlap(record.cast, item[0].cast) is True]
    return shared if len(shared) == 1 else kept


def decide_link(record: CatalogRecord, candidates: Sequence[Candidate]) -> LinkDecision:
    """Insert, link to one CMU point, or refuse (never insert when a candidate exists).

    Same year and a single candidate links unless both casts are known (3+ names) and disjoint;
    ±1 year, an unknown CMU year or a match through an alternative title also need a shared actor.
    """
    years = {y for y in (record.year, *record.release_years) if y is not None}
    if not years:
        return LinkDecision("ambiguous", reason="no_year")
    kept: list[tuple[Candidate, int | None]] = []
    for cand in candidates:
        delta = None if cand.year is None else min(abs(cand.year - y) for y in years)
        if delta is None or delta <= 1:
            kept.append((cand, delta))
    if not kept:
        return LinkDecision("insert")
    if len(kept) > 1:
        kept = _narrow(record, kept)
    if len(kept) > 1:
        return LinkDecision("ambiguous", reason="several_candidates")
    cand, delta = kept[0]
    if cand.tmdb_id is not None and cand.tmdb_id != record.tmdb_id:
        return LinkDecision("ambiguous", reason="candidate_linked_elsewhere", target=cand)
    overlap = cast_overlap(record.cast, cand.cast)
    if cand.via_alternative:
        ok = delta == 0 and overlap is True
        return LinkDecision("link" if ok else "ambiguous", cand, "" if ok else "alternative_title_unconfirmed")
    if delta == 0:
        known = len(cand.cast) >= MIN_CAST_FOR_VETO and len(record.cast) >= MIN_CAST_FOR_VETO
        if overlap is False and known:
            return LinkDecision("ambiguous", cand, "cast_mismatch")
        return LinkDecision("link", cand)
    return LinkDecision("link", cand) if overlap is True else LinkDecision("ambiguous", cand, "year_or_cast_unconfirmed")


# ---- store
def _must(*conditions) -> models.Filter:
    return models.Filter(must=list(conditions))


def _version_is(value: int) -> models.FieldCondition:
    return models.FieldCondition(key="version", match=models.MatchValue(value=int(value)))


@dataclass
class CatalogStore:
    """Reads and conditional writes of catalog points on one Qdrant collection."""

    client: QdrantClient
    collection: str
    model: str
    dimension: int
    timeout: int | None = None
    wait: bool = True  # False only in the concurrency stress test: production writes always wait
    new_write_id: Callable[[], str] = field(default=lambda: uuid.uuid4().hex)

    # -- setup
    def ensure_indexes(self) -> None:
        """Integer indexes for the catalog fields; safe to repeat, needed on an existing collection."""
        for name in ("tmdb_id", "version"):
            self.client.create_payload_index(self.collection, name, models.PayloadSchemaType.INTEGER)

    # -- reads
    def read_by_tmdb_id(self, tmdb_id: int) -> models.Record | None:
        points, _ = self.client.scroll(
            self.collection, limit=2, with_payload=True, with_vectors=False, timeout=self.timeout,
            scroll_filter=_must(models.FieldCondition(key="tmdb_id", match=models.MatchValue(value=int(tmdb_id)))))
        return points[0] if points else None

    def read_point(self, legacy_id: str) -> models.Record | None:
        found = self.client.retrieve(
            self.collection, ids=[point_uuid(legacy_id)], with_payload=True, with_vectors=False,
            timeout=self.timeout)
        return found[0] if found else None

    def find_candidates(self, record: CatalogRecord) -> list[Candidate]:
        """CMU points whose normalised title equals one of the film's titles (any year, none dropped)."""
        main = {norm_title(t) for t in (record.title, record.original_title) if t} - {""}
        alt = {norm_title(t) for t in record.alternative_titles} - {""} - main
        if not main and not alt:
            return []
        points, _ = self.client.scroll(
            self.collection, limit=100, with_payload=True, timeout=self.timeout,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="title_norm", match=models.MatchAny(any=sorted(main | alt)))],
                must_not=[models.FieldCondition(key="source", match=models.MatchValue(value=SOURCE))]))
        found = []
        for p in points:
            payload = p.payload or {}
            found.append(Candidate(
                point_id=str(p.id), title_norm=payload.get("title_norm", ""),
                year=payload.get("release_year_int") if isinstance(payload.get("release_year_int"), int)
                else year_int(payload.get("release_year")),
                cast=tuple(n.strip() for n in str(payload.get("cast") or "").split(";") if n.strip()),
                tmdb_id=payload.get("tmdb_id") if isinstance(payload.get("tmdb_id"), int) else None,
                via_alternative=payload.get("title_norm", "") not in main,
                title=str(payload.get("title") or "")))
        return found

    # -- the one entry point
    def sync(self, record: CatalogRecord, embed_text: Callable[[str], Sequence[float]]) -> CatalogOutcome:
        """Bring the catalog in line with `record`. Never raises for an expected refusal."""
        tmdb_id = record.tmdb_id
        text = embedding_text(record)
        if text is None:
            reason = "no_english_overview" if not (record.overview or "").strip() else "overview_too_short"
            return CatalogOutcome(SKIPPED, reason, tmdb_id)
        legacy_id = tmdb_legacy_id(tmdb_id)
        vector: list[float] | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            existing = self.read_by_tmdb_id(tmdb_id)
            if existing is None:
                decision = decide_link(record, self.find_candidates(record))
                if decision.action == "ambiguous":
                    return CatalogOutcome(SKIPPED, "ambiguous:" + decision.reason, tmdb_id, attempt)
                if decision.action == "link":
                    result = self._link(decision.target, tmdb_id)
                    if result is not None:
                        return CatalogOutcome(result[0], result[1], tmdb_id, attempt)
                    continue
                vector = vector or list(embed_text(text))
                if self._create(record, text, vector):
                    return CatalogOutcome(INSERTED, "", tmdb_id, attempt)
                continue
            payload = existing.payload or {}
            if payload.get("source") != SOURCE:  # a CMU point already linked to this film
                return CatalogOutcome(UNCHANGED, "linked_to_corpus", tmdb_id, attempt)
            if str(existing.id) != point_uuid(legacy_id):
                return CatalogOutcome(ERROR, "unexpected_point", tmdb_id, attempt)
            if record.fetched_ts <= int(payload.get("fetched_ts") or 0):
                return CatalogOutcome(SKIPPED, "stale", tmdb_id, attempt)
            wanted_text = text_hash(self.model, self.dimension, text)
            wanted_meta = meta_hash(full_payload(
                record, text, model=self.model, dimension=self.dimension, version=0, write_id=""))
            if payload.get("text_hash") == wanted_text and payload.get("meta_hash") == wanted_meta:
                return CatalogOutcome(UNCHANGED, "", tmdb_id, attempt)
            read_version = int(payload.get("version") or 0)
            if payload.get("text_hash") != wanted_text:
                vector = vector or list(embed_text(text))
                status = UPDATED if self._replace(record, text, vector, read_version) else None
            else:
                status = METADATA_UPDATED if self._replace_metadata(record, text, read_version) else None
            if status:
                return CatalogOutcome(status, "", tmdb_id, attempt)
        return CatalogOutcome(ERROR, "contention", tmdb_id, MAX_ATTEMPTS)

    # -- writes: each returns whether MY write is the one now stored
    def _applied(self, legacy_id: str, write_id: str) -> bool:
        point = self.read_point(legacy_id)
        return bool(point and (point.payload or {}).get("write_id") == write_id)

    def _create(self, record, text, vector) -> bool:
        write_id = self.new_write_id()
        payload = full_payload(record, text, model=self.model, dimension=self.dimension, version=1, write_id=write_id)
        self.client.upsert(
            self.collection, [models.PointStruct(id=point_uuid(payload["legacy_id"]), vector=vector, payload=payload)],
            update_filter=_must(models.FieldCondition(key="version", range=models.Range(lt=1))),
            wait=self.wait, timeout=self.timeout)
        return self._applied(payload["legacy_id"], write_id)

    def _replace(self, record, text, vector, read_version: int) -> bool:
        write_id = self.new_write_id()
        payload = full_payload(
            record, text, model=self.model, dimension=self.dimension, version=read_version + 1, write_id=write_id)
        self.client.upsert(
            self.collection, [models.PointStruct(id=point_uuid(payload["legacy_id"]), vector=vector, payload=payload)],
            update_filter=_must(_version_is(read_version)), wait=self.wait, timeout=self.timeout)
        return self._applied(payload["legacy_id"], write_id)

    def _replace_metadata(self, record, text, read_version: int) -> bool:
        """Whole payload replaced (no stale field survives); the vector is not touched."""
        write_id = self.new_write_id()
        payload = full_payload(
            record, text, model=self.model, dimension=self.dimension, version=read_version + 1, write_id=write_id)
        self.client.overwrite_payload(
            self.collection, payload,
            points=_must(models.HasIdCondition(has_id=[point_uuid(payload["legacy_id"])]), _version_is(read_version)),
            wait=self.wait, timeout=self.timeout)
        return self._applied(payload["legacy_id"], write_id)

    def _link(self, target: Candidate, tmdb_id: int) -> tuple[str, str] | None:
        """Set `tmdb_id` on a CMU point only while it is empty. None = lost a race: decide again."""
        self.client.set_payload(
            self.collection, {"tmdb_id": int(tmdb_id)},
            points=_must(models.HasIdCondition(has_id=[target.point_id]),
                         models.IsEmptyCondition(is_empty=models.PayloadField(key="tmdb_id"))),
            wait=self.wait, timeout=self.timeout)
        found = self.client.retrieve(self.collection, ids=[target.point_id], with_payload=["tmdb_id"], timeout=self.timeout)
        current = (found[0].payload or {}).get("tmdb_id") if found else None
        if current == int(tmdb_id):
            return LINKED, ""
        if current is None:
            return None
        return SKIPPED, "ambiguous:candidate_linked_elsewhere"
