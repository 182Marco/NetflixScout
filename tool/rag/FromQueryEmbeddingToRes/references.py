"""Reference films ("like X, not like Y"): deterministic resolution against the index.

A reference is looked up by normalised title (and year when given) in the vector store; the index
vector of the film it resolves to becomes a positive or negative example of a steered search.
Nothing is guessed: ambiguous or missing films give NO vector and are reported as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .store import norm_title, year_int

STATUSES = ("resolved", "ambiguous", "not_in_index", "estimated", "ignored_over_limit")
YEAR_WINDOW = 1


@dataclass(frozen=True)
class ReferenceInput:
    title: str
    year: int | None = None


@dataclass
class ResolvedReference:
    title: str
    year: int | None
    role: str  # "positive" | "negative"
    status: str
    source: str | None = None  # "index" for a real film, "estimated" for a generated description
    legacy_id: str | None = None
    movie_id: str | None = None
    matched_title: str | None = None
    matched_year: int | None = None
    candidates: list[dict] = field(default_factory=list)
    vector: list[float] | None = field(default=None, repr=False)
    homonym_movie_ids: list[str] = field(default_factory=list)

    def trace(self) -> dict:
        """What a presenter may show: never a vector."""
        out = {"title": self.title, "year": self.year, "role": self.role, "status": self.status}
        if self.source:
            out["source"] = self.source
        if self.status == "resolved":
            out.update(matched_title=self.matched_title, matched_year=self.matched_year, movie_id=self.movie_id)
        if self.candidates:
            out["candidates"] = [{k: c.get(k) for k in ("title", "release_year", "movie_id")} for c in self.candidates]
        return out


@dataclass
class ReferenceSet:
    entries: list[ResolvedReference]
    strategy: str = "average_vector"
    text_repeat: int = 1  # how many times the text vector enters the positive examples
    removed: list[dict] = field(default_factory=list)  # filled by `drop_references`

    @property
    def usable(self) -> list[ResolvedReference]:
        return [e for e in self.entries if e.vector is not None and e.status in ("resolved", "estimated")]

    @property
    def active(self) -> bool:
        """Steering happens only if at least one reference gave a real vector."""
        return bool(self.usable)

    def positives(self) -> list[list[float]]:
        return [e.vector for e in self.usable if e.role == "positive"]

    def negatives(self) -> list[list[float]]:
        return [e.vector for e in self.usable if e.role == "negative"]

    def excluded_movie_ids(self) -> list[str]:
        """Resolved references and their homonyms (decision: remakes sharing the title are excluded)."""
        ids: list[str] = []
        for e in self.entries:
            if e.status == "resolved":
                ids.extend([e.movie_id, *e.homonym_movie_ids])
        return sorted({str(i) for i in ids if i})

    def excluded_titles(self) -> list[tuple[str, int | None]]:
        """Title-based exclusion for references with no index point (not_in_index / estimated)."""
        return [(norm_title(e.title), e.year) for e in self.entries if e.status in ("not_in_index", "estimated")]

    def trace(self) -> dict:
        same_title = [{"reference": e.title, "title": c.get("title"), "release_year": c.get("release_year"),
                       "movie_id": c.get("movie_id")}
                      for e in self.entries if e.status == "resolved" for c in e.candidates]
        return {"strategy": self.strategy, "active": self.active, "references": [e.trace() for e in self.entries],
                # films sharing a resolved reference's title: excluded by id before the search (decision)
                "excluded_same_title": same_title,
                # anything the final guard still had to remove from a branch's results
                "excluded_by_guard": list(self.removed)}


def _closest(candidates: list[dict], year: int) -> list[dict]:
    dated = [(abs(year_int(c.get("release_year")) - year), c) for c in candidates if year_int(c.get("release_year")) is not None]
    if not dated:
        return []
    best = min(d for d, _ in dated)
    return [c for d, c in dated if d == best]


def resolve_reference(store, ref: ReferenceInput, role: str) -> ResolvedReference:
    out = ResolvedReference(title=ref.title, year=ref.year, role=role, status="not_in_index")
    if not norm_title(ref.title):
        return out
    same_title = store.find_by_title(ref.title, None)  # every film sharing the title
    if ref.year is None:
        matches = same_title
    else:
        matches = store.find_by_title(ref.title, ref.year, window=YEAR_WINDOW)
    if not matches:
        # nothing within the year window: a different film of the same title is NOT used
        out.candidates = same_title[:5]
        return out
    chosen = matches
    if len(matches) > 1:
        chosen = _closest(matches, ref.year) if ref.year is not None else []
    if len(chosen) != 1:
        out.status = "ambiguous"
        out.candidates = matches[:5]
        return out
    hit = chosen[0]
    vector = store.vector_of(hit["id"])
    if vector is None:  # an index inconsistency must not become a silent guess
        out.status = "not_in_index"
        return out
    out.status, out.source = "resolved", "index"
    out.legacy_id, out.movie_id = hit["id"], hit.get("movie_id")
    out.matched_title, out.matched_year = hit.get("title"), year_int(hit.get("release_year"))
    out.vector = vector
    out.homonym_movie_ids = [h["movie_id"] for h in same_title if h.get("movie_id") and h["id"] != hit["id"]]
    out.candidates = [h for h in same_title if h["id"] != hit["id"]][:5]
    return out


def resolve_references(store, like: list[ReferenceInput], avoid: list[ReferenceInput], *,
                       max_positive: int = 3, max_negative: int = 3, strategy: str = "average_vector",
                       text_repeat: int = 1) -> ReferenceSet:
    entries: list[ResolvedReference] = []
    for refs, role, limit in ((like or [], "positive", max_positive), (avoid or [], "negative", max_negative)):
        for n, ref in enumerate(refs):
            if n >= limit:
                entries.append(ResolvedReference(ref.title, ref.year, role, "ignored_over_limit"))
                continue
            entries.append(resolve_reference(store, ref, role))
    return ReferenceSet(entries, strategy=strategy, text_repeat=max(1, int(text_repeat)))


def drop_references(rows: list[dict], refs: ReferenceSet) -> list[dict]:
    """Final guard on whatever a search branch returned: no reference may appear in the results.

    Resolved references (and their same-title films) go by movie id; references with no index point
    go by exact normalised title, with the year when it is known. Ambiguous ones exclude nothing.
    """
    ids = set(refs.excluded_movie_ids())
    titles = refs.excluded_titles()
    resolved_titles = {norm_title(e.matched_title): e for e in refs.entries if e.status == "resolved"}
    kept = []
    for row in rows:
        movie_id, title = str(row.get("movie_id") or ""), norm_title(row.get("title"))
        year = year_int(row.get("release_year"))
        reason = None
        if movie_id and movie_id in ids:
            owner = resolved_titles.get(title)
            reason = "same_title" if title in resolved_titles and owner and movie_id != owner.movie_id else "reference"
        else:
            for t, y in titles:
                if t and t == title and (y is None or (year is not None and abs(year - y) <= YEAR_WINDOW)):
                    reason = "reference_title"
                    break
        if reason:
            refs.removed.append({"reason": reason, "title": row.get("title"), "year": row.get("release_year"),
                                 "movie_id": row.get("movie_id")})
        else:
            kept.append(row)
    return kept
