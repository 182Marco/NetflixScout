"""Read-only access to the Qdrant collection: points as `Item`, payload lookups, parent/children navigation. Nothing here writes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from qdrant_client import QdrantClient, models

from .constants import COLLECTION, SUBTYPES, URL
from .countries import country_variants
from .signals import SeriesSignals
from .text import norm, unit


@dataclass
class Item:
    point_id: str
    record_id: str
    entity_type: str
    title: str
    year: int | None
    subtype: str | None
    text: str
    series_id: str | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    url: str | None = None
    country: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    default_search_eligible: bool = True
    ids_reliable: bool | None = None
    text_kind: str | None = None
    score: float = 0.0
    vector: np.ndarray | None = field(default=None, repr=False)
    imdb_id: str | None = None  # only a reliable, well-formed IMDb id (series and TV films); the planner may hand it to cinema_sql

    def label(self) -> str:
        if self.entity_type == "episode":
            s = f"{self.series_title or '?'} S{self.season_number or '?'}E{self.episode_number or '?'} – {self.title}"
            return s
        return self.title + (f" ({self.year})" if self.year else "")


def item_from_point(pt) -> Item:
    p = pt.payload or {}
    vec = unit(pt.vector) if getattr(pt, "vector", None) is not None else None
    text = p.get("plot_text") or p.get("lead_text") or ""
    imdb = str(p.get("imdb_id") or "")
    item = Item(str(pt.id), p.get("record_id", ""), p.get("entity_type", ""), p.get("title", ""), p.get("year"), p.get("subtype"), text,
                p.get("series_id"), p.get("series_title"), p.get("season_number"), p.get("episode_number"), p.get("wikipedia_url"),
                list(p.get("country") or []), list(p.get("genres") or []), list(p.get("flags") or []),
                bool(p.get("default_search_eligible", True)), p.get("ids_reliable"), p.get("text_kind"),
                float(getattr(pt, "score", 0) or 0), vec)
    if p.get("ids_reliable") is not False and re.fullmatch(r"tt\d{7,9}", imdb):
        item.imdb_id = imdb
    return item


def _eq(key, value):
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


class SeriesIndex:
    def __init__(self, *, url: str = URL, collection: str = COLLECTION, client: QdrantClient | None = None):
        self.collection = collection
        self.client = client or QdrantClient(url=url, timeout=60)

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    def query(self, vector, *, limit: int, flt: models.Filter | None) -> list[Item]:
        r = self.client.query_points(self.collection, query=[float(x) for x in vector], limit=limit, query_filter=flt,
                                     with_payload=True, with_vectors=True)
        return [item_from_point(p) for p in r.points]

    def lookup(self, flt: models.Filter, *, limit: int = 200, vectors: bool = False) -> list[Item]:
        out, off = [], None
        while len(out) < limit:
            pts, off = self.client.scroll(self.collection, scroll_filter=flt, limit=min(256, limit - len(out)), offset=off,
                                          with_payload=True, with_vectors=vectors)
            out += [item_from_point(p) for p in pts]
            if off is None:
                break
        return out

    # --- by title (no embedding) and navigation (no vectors)
    def find_titles(self, title: str, *, levels=("series", "tv_movie"), eligible_only: bool = False) -> list[Item]:
        k = norm(title)
        if not k:
            return []
        must = [models.FieldCondition(key="entity_type", match=models.MatchAny(any=list(levels)))]
        if eligible_only:
            must.append(_eq("default_search_eligible", True))
        found = self.lookup(models.Filter(must=must + [models.Filter(should=[_eq("title_norm", k), _eq("original_title_norm", k),
                                                                              _eq("title_base_norm", k)])]), limit=60)
        return sorted(found, key=lambda i: (i.year or 9999, i.title))

    def seasons_of(self, series_id: str) -> list[Item]:
        its = self.lookup(models.Filter(must=[_eq("entity_type", "season"), _eq("series_id", series_id)]), limit=500)
        return sorted(its, key=lambda i: (i.season_number or 0))

    def episodes_of(self, series_id: str, season_number: int | None = None) -> list[Item]:
        must = [_eq("entity_type", "episode"), _eq("series_id", series_id)]
        if season_number is not None:
            must.append(_eq("season_number", season_number))
        its = self.lookup(models.Filter(must=must), limit=3000)
        return sorted(its, key=lambda i: (i.season_number or 0, i.episode_number if i.episode_number is not None else 9999, i.title))

    def parent_of(self, item: Item) -> Item | None:
        if not item.series_id:
            return None
        got = self.lookup(models.Filter(must=[_eq("record_id", item.series_id)]), limit=1)
        return got[0] if got else None

    def positive_filter(self, sg: SeriesSignals, *, series_ids: list[str] | None = None) -> models.Filter:
        must: list = [_eq("entity_type", sg.level)]
        if sg.level in ("series", "tv_movie") and not sg.about_manga_or_original_work:
            must.append(_eq("default_search_eligible", True))
        if series_ids is not None:
            must.append(models.FieldCondition(key="series_id", match=models.MatchAny(any=series_ids)))
        if sg.season_number is not None and sg.level in ("season", "episode"):
            must.append(_eq("season_number", sg.season_number))
        if sg.episode_number is not None and sg.level == "episode":
            must.append(_eq("episode_number", sg.episode_number))
        subs = [s for s in sg.subtypes if s in SUBTYPES]
        if subs and sg.level == "series":
            must.append(models.FieldCondition(key="subtype", match=models.MatchAny(any=subs)))
        if (sg.year_from is not None or sg.year_to is not None) and sg.level in ("series", "tv_movie"):
            must.append(models.FieldCondition(key="year", range=models.Range(gte=sg.year_from, lte=sg.year_to)))
        if sg.countries and sg.level in ("series", "tv_movie"):
            must.append(models.FieldCondition(key="country", match=models.MatchAny(any=country_variants(list(sg.countries)))))
        for name in sg.cast_names:
            must.append(models.FieldCondition(key="cast", match=models.MatchText(text=name)))
        for name in sg.creator_names:
            must.append(models.Filter(should=[models.FieldCondition(key="creators", match=models.MatchText(text=name)),
                                              models.FieldCondition(key="director", match=models.MatchText(text=name))]))
        for term in sg.rare_terms:
            must.append(models.FieldCondition(key="plot_text", match=models.MatchText(text=term)))
        return models.Filter(must=must)
