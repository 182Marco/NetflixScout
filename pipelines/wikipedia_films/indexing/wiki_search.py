"""Search in the Wikipedia collection with ONE result per film: chunked films (5) can match through several chunks, the
groups API keeps the best chunk of each film, so a film is never duplicated in the results."""
from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from . import settings as S


@dataclass
class FilmHit:
    film_id: str
    score: float
    chunk_index: int
    payload: dict   # the whole film record (+ chunk fields): title, year, director, actors, genres, synopsis, wikipedia_url...


def embed_query(text: str, client=None) -> list[float]:
    """Query embedding with the same model and dimensions as the index (one small API call)."""
    if client is None:
        from .embed_run import make_client
        client = make_client()
    r = client.embeddings.create(model=S.MODEL, input=[text], dimensions=S.DIMENSIONS, encoding_format="float")
    return r.data[0].embedding


def search_films(qdrant: QdrantClient, vector, *, limit: int = 10, collection: str = S.COLLECTION,
                 query_filter: models.Filter | None = None, hnsw_ef: int | None = None) -> list[FilmHit]:
    res = qdrant.query_points_groups(
        collection, query=list(map(float, vector)), group_by="film_id", limit=limit, group_size=1,
        with_payload=True, query_filter=query_filter,
        search_params=models.SearchParams(hnsw_ef=hnsw_ef) if hnsw_ef else None)
    hits = []
    for g in res.groups:
        h = g.hits[0]
        hits.append(FilmHit(str(g.id), float(h.score), int(h.payload.get("chunk_index", 0)), h.payload))
    return hits


def get_film(qdrant: QdrantClient, film_id: str, collection: str = S.COLLECTION) -> dict | None:
    """The film record and all its chunk points (one for ordinary films)."""
    pts, _ = qdrant.scroll(collection, scroll_filter=models.Filter(must=[
        models.FieldCondition(key="film_id", match=models.MatchValue(value=film_id))]), limit=200, with_payload=True)
    if not pts:
        return None
    pts.sort(key=lambda p: p.payload["chunk_index"])
    return {"film": pts[0].payload, "chunks": [p.payload.get("chunk_text") or p.payload["synopsis"] for p in pts],
            "point_ids": [str(p.id) for p in pts]}
