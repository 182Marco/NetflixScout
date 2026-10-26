"""Qdrant implementation of `VectorStore` (embedded, in-memory or server)."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from qdrant_client import QdrantClient, models

from .base import IndexMeta, StorePoint
from .ids import norm_title, point_uuid, year_int

# Payload keys the store adds; they are not part of the metadata the search results expose.
_RESERVED = ("document", "legacy_id", "title_norm", "release_year_int",
             "version", "write_id", "fetched_ts", "text_hash", "meta_hash", "tmdb_id")
_STRATEGIES = {
    "average_vector": models.RecommendStrategy.AVERAGE_VECTOR,
    "best_score": models.RecommendStrategy.BEST_SCORE,
}
MODES = ("embedded", "memory", "server")


def open_client(
    mode: str, *, path: str | Path | None = None, url: str | None = None, api_key: str | None = None
) -> QdrantClient:
    """Build the client for a mode. Embedded locks its folder: one process at a time."""
    if mode == "memory":
        return QdrantClient(":memory:")
    if mode == "embedded":
        if not path:
            raise ValueError("vectorstore.mode 'embedded' needs vectorstore.path")
        return QdrantClient(path=str(path))
    if mode == "server":
        if not url:
            raise ValueError("vectorstore.mode 'server' needs vectorstore.url")
        return QdrantClient(url=url, api_key=api_key)
    raise ValueError(f"vectorstore.mode {mode!r} unknown: use one of {MODES}")


def _params(exact: bool = False, ef: int | None = None) -> models.SearchParams | None:
    if exact:
        return models.SearchParams(exact=True)
    return models.SearchParams(hnsw_ef=ef) if ef else None


def _row(point) -> dict:
    payload = dict(point.payload or {})
    row = {"id": payload.get("legacy_id"), "testo": payload.get("document", ""), "score": point.score}
    row.update({k: v for k, v in payload.items() if k not in _RESERVED})
    return row


def build_payload(legacy_id: str, metadata: dict, document: str) -> dict:
    """Payload of one point: metadata, document and the derived lookup fields. Shared with the catalog."""
    payload = {**metadata, "document": document, "legacy_id": legacy_id,
               "title_norm": norm_title(metadata.get("title"))}
    year = year_int(metadata.get("release_year"))
    if year is not None:
        payload["release_year_int"] = year
    return payload


class QdrantStore:
    def __init__(self, client: QdrantClient, collection: str, meta: IndexMeta) -> None:
        self.client = client
        self.collection = collection
        self.meta = meta

    # ---- lifecycle
    def create(self) -> None:
        """Create the collection with its index meta; fails if it exists (never replaces)."""
        self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=self.meta.dimension, distance=models.Distance.COSINE),
            metadata={"model": self.meta.model, "dimension": self.meta.dimension, "distance": self.meta.distance},
        )
        self.ensure_payload_indexes()

    def exists(self) -> bool:
        return self.client.collection_exists(self.collection)

    def check_meta(self) -> None:
        """Refuse an index built with another model or dimension than the configuration."""
        info = self.client.get_collection(self.collection)
        found = dict(getattr(info.config, "metadata", None) or {})
        wanted = {"model": self.meta.model, "dimension": self.meta.dimension, "distance": self.meta.distance}
        if found != wanted:
            raise ValueError(
                f"Index {self.collection!r} was built with {found or 'unknown settings'}, "
                f"but the configuration expects {wanted}. Embeddings of different models are not "
                "comparable: rebuild the index or fix CONFIG['rag']['embedding']."
            )

    def ensure_payload_indexes(self) -> None:
        """Indexes matter on a server; embedded mode accepts and ignores them."""
        for field, schema in (
            ("title_norm", models.PayloadSchemaType.KEYWORD),
            ("movie_id", models.PayloadSchemaType.KEYWORD),
            ("release_year_int", models.PayloadSchemaType.INTEGER),
        ):
            self.client.create_payload_index(self.collection, field, schema)

    def close(self) -> None:
        self.client.close()

    # ---- writes / reads
    def count(self) -> int:
        return self.client.count(self.collection).count

    def upsert(self, points: Sequence[StorePoint]) -> None:
        structs = []
        for point in points:
            payload = build_payload(point.id, point.metadata, point.document)
            structs.append(models.PointStruct(id=point_uuid(point.id), vector=list(point.vector), payload=payload))
        self.client.upsert(self.collection, structs)

    @staticmethod
    def _exclusion(exclude_movie_ids: Sequence[str]) -> models.Filter | None:
        if not exclude_movie_ids:
            return None
        return models.Filter(must_not=[models.FieldCondition(
            key="movie_id", match=models.MatchAny(any=[str(m) for m in exclude_movie_ids]))])

    def query(self, vector, limit, *, exclude_movie_ids=(), exact=False, ef=None) -> list[dict]:
        """`exact=True` scans every vector (no HNSW): the reference the approximate search is judged by."""
        found = self.client.query_points(
            self.collection, query=list(vector), limit=limit, with_payload=True,
            query_filter=self._exclusion(exclude_movie_ids),
            search_params=_params(exact, ef),
        ).points
        return [_row(p) for p in found]

    def recommend(self, positive, negative, limit, *, strategy="average_vector", exclude_movie_ids=(),
                  exact=False, ef=None) -> list[dict]:
        if strategy not in _STRATEGIES:
            raise ValueError(f"strategy {strategy!r} unknown: use one of {tuple(_STRATEGIES)}")
        if not positive:
            raise ValueError("recommend needs at least one positive example")
        found = self.client.query_points(
            self.collection,
            query=models.RecommendQuery(recommend=models.RecommendInput(
                positive=[list(v) for v in positive], negative=[list(v) for v in negative],
                strategy=_STRATEGIES[strategy])),
            limit=limit, with_payload=True, query_filter=self._exclusion(exclude_movie_ids),
            search_params=_params(exact, ef),
        ).points
        return [_row(p) for p in found]

    def find_by_title(self, title, year=None, window=1) -> list[dict]:
        must = [models.FieldCondition(key="title_norm", match=models.MatchValue(value=norm_title(title)))]
        if year is not None:
            must.append(models.FieldCondition(
                key="release_year_int", range=models.Range(gte=year - window, lte=year + window)))
        points, _ = self.client.scroll(
            self.collection, scroll_filter=models.Filter(must=must), limit=50, with_payload=True)
        return [{"id": p.payload.get("legacy_id"), "movie_id": p.payload.get("movie_id"),
                 "title": p.payload.get("title"), "release_year": p.payload.get("release_year")}
                for p in points]

    def vector_of(self, legacy_id) -> list[float] | None:
        found = self.client.retrieve(self.collection, ids=[point_uuid(legacy_id)], with_vectors=True)
        return list(found[0].vector) if found else None

    def page(self, limit: int, cursor=None) -> tuple[list[dict], object]:
        """One page of rows in the search shape and the cursor of the next one (None at the end)."""
        points, nxt = self.client.scroll(self.collection, limit=limit, offset=cursor, with_payload=True)
        rows = []
        for p in points:
            payload = dict(p.payload or {})
            rows.append({"id": payload.get("legacy_id"), "testo": payload.get("document", ""),
                         **{k: v for k, v in payload.items() if k not in _RESERVED}})
        return rows, nxt

    def scroll(self, batch_size=5000) -> Iterator[dict]:
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection, limit=batch_size, offset=offset, with_payload=True)
            for p in points:
                payload = dict(p.payload or {})
                yield {"id": payload.get("legacy_id"), "testo": payload.get("document", ""),
                       **{k: v for k, v in payload.items() if k not in _RESERVED}}
            if offset is None:
                return
