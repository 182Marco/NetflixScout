"""Access to a film corpus in Qdrant behind one interface, so the SAME strategies run on the old index and on v3.

NEW  = `wikipedia_films_it_v3`  (Italian Wikipedia plots, text-embedding-3-large @1536)
OLD  = `netflix_scout`          (CMU 2012 plots in English, text-embedding-3-small)
Read-only: nothing here writes to Qdrant."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
from qdrant_client import QdrantClient, models

from . import llm

QDRANT_URL = "http://127.0.0.1:6333"


def norm(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t.lower())).strip()


@dataclass
class Film:
    point_id: str
    title: str
    original_title: str | None
    year: int | None
    genres: list[str]
    plot: str
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    franchise_ids: list[str] = field(default_factory=list)
    work_format: str | None = None
    unverified: bool = False
    score: float = 0.0
    vector: np.ndarray | None = field(default=None, repr=False)

    def label(self) -> str:
        return f"{self.title}" + (f" ({self.year})" if self.year else "")

    def brief(self) -> dict:
        return {"point_id": self.point_id, "title": self.title, "original_title": self.original_title, "year": self.year,
                "genres": self.genres, "score": round(float(self.score), 4), "franchise_ids": self.franchise_ids,
                "work_format": self.work_format}


class Corpus:
    def __init__(self, key: str, collection: str, embed_model: str, dims: int | None, lang: str, client: QdrantClient | None = None):
        self.key, self.collection, self.embed_model, self.dims, self.lang = key, collection, embed_model, dims, lang
        self.client = client or QdrantClient(url=QDRANT_URL, timeout=120)
        self._vocab: list[str] | None = None

    # ---- embedding
    def embed(self, texts: list[str]) -> np.ndarray:
        return llm.embed(texts, self.embed_model, self.dims)

    # ---- payload -> Film
    def film(self, pt) -> Film:
        p = pt.payload or {}
        vec = np.asarray(pt.vector, dtype=np.float32) if getattr(pt, "vector", None) is not None else None
        if vec is not None:
            vec = vec / (np.linalg.norm(vec) or 1.0)
        if self.key == "new":
            return Film(str(pt.id), p.get("title", ""), p.get("original_title"), p.get("year"), list(p.get("genres") or []),
                        p.get("synopsis", ""), [d.get("name") for d in p.get("director") or []],
                        [a.get("name") for a in (p.get("actors") or [])[:8]], list(p.get("franchise_ids") or []),
                        p.get("work_format"), bool(p.get("unverified")), float(getattr(pt, "score", 0) or 0), vec)
        year = p.get("release_year_int") or p.get("release_year")
        try:
            year = int(str(year)[:4]) if year else None
        except ValueError:
            year = None
        return Film(str(pt.id), p.get("title", ""), None, year, [g.strip() for g in str(p.get("genres") or "").split(";") if g.strip()],
                    p.get("document", ""), [], [c.strip() for c in str(p.get("cast") or "").split(";")[:8] if c.strip()], [], None, False,
                    float(getattr(pt, "score", 0) or 0), vec)

    # ---- search
    def search(self, vector, *, limit: int, flt: models.Filter | None = None, with_vectors: bool = False) -> list[Film]:
        r = self.client.query_points(self.collection, query=[float(x) for x in vector], limit=limit, query_filter=flt,
                                     with_payload=True, with_vectors=with_vectors)
        return [self.film(p) for p in r.points]

    def get(self, point_ids: list[str], with_vectors: bool = True) -> list[Film]:
        return [self.film(p) for p in self.client.retrieve(self.collection, ids=point_ids, with_payload=True, with_vectors=with_vectors)]

    # ---- title resolution
    def resolve(self, title_it: str, title_original: str, year: int | None) -> Film | None:
        """The film a title names in THIS corpus, or None (the reference is not in the index)."""
        cands = {norm(title_it), norm(title_original)} - {""}
        if self.key == "old":
            cands |= {re.sub(r"^(the|a|an) ", "", c) for c in cands}
            conds = [models.FieldCondition(key="title_norm", match=models.MatchAny(any=sorted(cands)))]
        else:
            conds = [models.FieldCondition(key="title_norm", match=models.MatchAny(any=sorted(cands))),
                     models.FieldCondition(key="original_title_norm", match=models.MatchAny(any=sorted(cands)))]
        pts, _ = self.client.scroll(self.collection, scroll_filter=models.Filter(should=conds), limit=30, with_payload=True, with_vectors=True)
        films = [self.film(p) for p in pts]
        if year:
            near = [f for f in films if f.year and abs(f.year - year) <= 1]
            return near[0] if near else None
        # without a year: prefer the best-known exact title, i.e. the earliest film whose title is exactly the one asked
        exact = [f for f in films if norm(f.title) in cands or norm(f.original_title) in cands]
        pool = exact or films
        return sorted(pool, key=lambda f: (f.year or 9999))[0] if pool else None

    def positive_filter(self, sg) -> models.Filter | None:
        """Filters the request states as WANTED (year range, countries, directors, actors, rare plot words), evaluated by Qdrant."""
        must = []
        if sg.year_from is not None or sg.year_to is not None:
            key = "year" if self.key == "new" else "release_year_int"
            must.append(models.FieldCondition(key=key, range=models.Range(gte=sg.year_from, lte=sg.year_to)))
        if self.key == "new":
            if sg.countries:
                must.append(models.FieldCondition(key="country", match=models.MatchAny(any=list(sg.countries))))
            if sg.directors:
                must.append(models.FieldCondition(key="director_names_norm", match=models.MatchAny(any=[norm(d) for d in sg.directors])))
            if sg.actors:
                must.append(models.FieldCondition(key="actor_names_norm", match=models.MatchAny(any=[norm(a) for a in sg.actors])))
            for term in sg.rare_terms:
                must.append(models.FieldCondition(key="synopsis", match=models.MatchText(text=term)))
        else:
            for a in sg.actors:
                must.append(models.FieldCondition(key="cast", match=models.MatchText(text=a)))
            for term in sg.rare_terms:
                must.append(models.FieldCondition(key="document", match=models.MatchText(text=term)))
        return models.Filter(must=must) if must else None

    # ---- genre vocabulary
    def vocab(self) -> list[str]:
        if self._vocab is None:
            path = llm.CACHE / f"vocab_{self.key}.json"
            if path.exists():
                self._vocab = json.loads(path.read_text())
            else:
                seen: set[str] = set()
                offset = None
                while True:
                    pts, offset = self.client.scroll(self.collection, limit=5000, offset=offset, with_payload=["genres"], with_vectors=False)
                    for p in pts:
                        g = (p.payload or {}).get("genres")
                        for x in (g if isinstance(g, list) else str(g or "").split(";")):
                            if x and x.strip():
                                seen.add(x.strip())
                    if offset is None:
                        break
                self._vocab = sorted(seen)
                path.write_text(json.dumps(self._vocab, ensure_ascii=False))
        return self._vocab

    def genre_terms(self, signals_terms_en: list[str], signals_terms_it: list[str]) -> list[str]:
        return signals_terms_it if self.key == "new" else signals_terms_en


def new_corpus(client=None) -> Corpus:
    return Corpus("new", "wikipedia_films_it_v3", "text-embedding-3-large", 1536, "it", client)


def old_corpus(client=None) -> Corpus:
    return Corpus("old", "netflix_scout", "text-embedding-3-small", None, "en", client)
