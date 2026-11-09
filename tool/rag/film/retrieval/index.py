"""Read-only access to the film collection in Qdrant."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from qdrant_client import QdrantClient, models

from ...shared.text import norm, unit
from .models import Signals


@dataclass
class Film:
    point_id: str
    film_id: str | None
    title: str
    original_title: str | None
    year: int | None
    genres: list[str]
    plot: str
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    duration_minutes: int | None = None
    imdb_id: str | None = None
    wikipedia_url: str | None = None
    franchise_ids: list[str] = field(default_factory=list)
    work_format: str | None = None
    unverified: bool = False
    score: float = 0.0
    vector: np.ndarray | None = field(default=None, repr=False)

    def label(self) -> str:
        return self.title + (f" ({self.year})" if self.year else "")


def film_from_point(pt) -> Film:
    p = pt.payload or {}
    vec = unit(pt.vector) if getattr(pt, "vector", None) is not None else None
    return Film(
        str(pt.id), p.get("film_id"), p.get("title", ""), p.get("original_title"), p.get("year"), list(p.get("genres") or []),
        p.get("synopsis", ""), [d.get("name") for d in p.get("director") or [] if d.get("name")],
        [a.get("name") for a in (p.get("actors") or [])[:8] if a.get("name")], list(p.get("country") or []), p.get("duration_minutes"),
        p.get("imdb_id"), p.get("wikipedia_url"), list(p.get("franchise_ids") or []), p.get("work_format"), bool(p.get("unverified")),
        float(getattr(pt, "score", 0) or 0), vec)


class FilmIndex:
    def __init__(self, *, url: str, collection: str, client: QdrantClient | None = None, timeout: float = 30.0):
        self.collection = collection
        self.client = client or QdrantClient(url=url, timeout=timeout)
        self._genre_labels: dict[str, int] | None = None

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    def search(self, vector, *, limit: int, flt: models.Filter | None = None, with_vectors: bool = True) -> list[Film]:
        r = self.client.query_points(self.collection, query=[float(x) for x in vector], limit=limit, query_filter=flt,
                                     with_payload=True, with_vectors=with_vectors)
        return [film_from_point(p) for p in r.points]

    def resolve(self, title_it: str, title_original: str, year: int | None) -> Film | None:
        """The film a title names in the index, or None (the reference is not in the catalogue)."""
        cands = sorted({norm(title_it), norm(title_original)} - {""})
        if not cands:
            return None
        flt = models.Filter(should=[models.FieldCondition(key="title_norm", match=models.MatchAny(any=cands)),
                                    models.FieldCondition(key="original_title_norm", match=models.MatchAny(any=cands))])
        pts, _ = self.client.scroll(self.collection, scroll_filter=flt, limit=30, with_payload=True, with_vectors=True)
        films = [film_from_point(p) for p in pts]
        if year:
            near = [f for f in films if f.year and abs(f.year - year) <= 1]
            return near[0] if near else None
        exact = [f for f in films if {norm(f.title), norm(f.original_title)} & set(cands)]
        pool = exact or films
        return sorted(pool, key=lambda f: f.year or 9999)[0] if pool else None

    def positive_filter(self, sg: Signals) -> models.Filter | None:
        """Filters the request states as WANTED, evaluated by Qdrant."""
        must = []
        if sg.year_from is not None or sg.year_to is not None:
            must.append(models.FieldCondition(key="year", range=models.Range(gte=sg.year_from, lte=sg.year_to)))
        if sg.countries:
            must.append(models.FieldCondition(key="country", match=models.MatchAny(any=list(sg.countries))))
        if sg.directors:
            must.append(models.FieldCondition(key="director_names_norm", match=models.MatchAny(any=[norm(d) for d in sg.directors])))
        if sg.actors:
            must.append(models.FieldCondition(key="actor_names_norm", match=models.MatchAny(any=[norm(a) for a in sg.actors])))
        for term in sg.rare_terms:
            must.append(models.FieldCondition(key="synopsis", match=models.MatchText(text=term)))
        return models.Filter(must=must) if must else None

    def genre_share(self, term: str) -> float:
        """Upper bound of the share of the catalogue whose genre labels contain `term` (guards against a too-wide genre filter)."""
        if self._genre_labels is None:
            try:
                r = self.client.facet(self.collection, key="genres_norm", limit=3000)
                self._genre_labels = {h.value: h.count for h in r.hits}
            except Exception:  # noqa: BLE001  (an unknown share must not block the turn: treated as 0)
                self._genre_labels = {}
        total = max(self.count(), 1)
        t = norm(term)
        return sum(c for g, c in self._genre_labels.items() if t and t in g) / total
