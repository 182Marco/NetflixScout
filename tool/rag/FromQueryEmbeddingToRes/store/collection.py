"""Read surface over a `QdrantStore` for the retrieval code.

`vectorstore.search` and the BM25 builder only need `count`, `query` and `get`, returning plain dicts of
parallel lists (`ids`, `documents`, `distances`, `metadatas`), so their logic (filters, boosts, penalties,
ranking) does not depend on the vector store. Distances are `1 - cosine`.
"""
from __future__ import annotations

import os
import threading

from qdrant_client import QdrantClient

from .base import IndexMeta
from .qdrant_store import QdrantStore, open_client
from .settings import DEFAULT_DIMENSION, DEFAULT_EMBEDDING_MODEL

_CLIENTS: dict[tuple, QdrantClient] = {}
_VERIFIED: set[tuple] = set()
_LOCK = threading.Lock()
ENV_API_KEY = "QDRANT_API_KEY"  # read only here; never stored in the config, traces or errors
_END = object()  # cursor value meaning "no page after this one" (Qdrant's own end marker is None)


class QdrantUnavailable(RuntimeError):
    """The Qdrant server cannot be reached (down, wrong URL, locked folder). The message tells what to do."""


class QdrantCollection:
    def __init__(self, store: QdrantStore, *, exact: bool = False, ef: int | None = None) -> None:
        self.store = store
        self.exact = exact  # diagnostic: full scan instead of HNSW
        self.ef = ef  # HNSW search breadth (None = server default)
        self.name = store.collection
        self._cursors: dict[tuple[int, int], object] = {}

    def count(self) -> int:
        return self.store.count()

    def query(self, query_embeddings, n_results, include=None, exclude_movie_ids=()) -> dict:
        if len(query_embeddings) != 1:
            raise ValueError("QdrantCollection.query takes exactly one query embedding")
        rows = self.store.query(query_embeddings[0], int(n_results), exclude_movie_ids=exclude_movie_ids,
                                exact=self.exact, ef=self.ef)
        metas = [{k: v for k, v in r.items() if k not in ("id", "testo", "score")} for r in rows]
        return {
            "ids": [[r["id"] for r in rows]],
            "documents": [[r["testo"] for r in rows]],
            "distances": [[1.0 - r["score"] for r in rows]],
            "metadatas": [metas],
        }

    def recommend(self, positive, negative, n_results, *, strategy="average_vector", exclude_movie_ids=()) -> dict:
        """Steered search, same return shape as `query`. The "distance" is `1 - score` so that
        `search` can keep reading `score = 1 - distance`: for `best_score` the score is NOT a cosine."""
        rows = self.store.recommend(positive, negative, int(n_results), strategy=strategy,
                                    exclude_movie_ids=exclude_movie_ids, exact=self.exact, ef=self.ef)
        metas = [{k: v for k, v in r.items() if k not in ("id", "testo", "score")} for r in rows]
        return {
            "ids": [[r["id"] for r in rows]],
            "documents": [[r["testo"] for r in rows]],
            "distances": [[1.0 - r["score"] for r in rows]],
            "metadatas": [metas],
        }

    def get(self, limit, offset=0, include=None) -> dict:
        """Offset paging. Qdrant pages by cursor, so sequential offsets reuse the cursor of
        the previous page; any other offset is reached by walking from the start."""
        limit, offset = int(limit), int(offset)
        empty = {"ids": [], "documents": [], "metadatas": []}
        if offset == 0:
            cursor = None
        elif (limit, offset) in self._cursors:
            cursor = self._cursors[(limit, offset)]
        else:
            cursor, skipped = None, 0
            while skipped < offset:
                step = min(limit, offset - skipped)
                points, cursor = self.store.client.scroll(
                    self.store.collection, limit=step, offset=cursor, with_payload=False)
                skipped += len(points)
                if cursor is None:
                    break
            if cursor is None:
                cursor = _END
        if cursor is _END:  # the previous page was the last one: nothing at or after this offset
            return empty
        rows, nxt = self.store.page(limit, cursor)
        self._cursors[(limit, offset + len(rows))] = _END if nxt is None else nxt
        return {
            "ids": [r["id"] for r in rows],
            "documents": [r["testo"] for r in rows],
            "metadatas": [{k: v for k, v in r.items() if k not in ("id", "testo")} for r in rows],
        }


def open_collection(name: str, store_config: dict, *, client: QdrantClient | None = None) -> QdrantCollection:
    """Open the Qdrant collection described by `CONFIG['rag']['vectorstore']` (cached client).

    Embedded mode locks its folder, so one client per location is shared by the whole process.
    """
    q = dict(store_config.get("qdrant") or {})
    meta = IndexMeta(
        model=q.get("model") or DEFAULT_EMBEDDING_MODEL, dimension=int(q.get("dimension") or DEFAULT_DIMENSION))
    where = str(q.get("url") or q.get("path") or "")
    key = (q.get("mode"), where)
    if client is None:
        with _LOCK:
            if key not in _CLIENTS:
                _CLIENTS[key] = open_client(q.get("mode", "server"), path=q.get("path"), url=q.get("url"),
                                            api_key=os.getenv(ENV_API_KEY) or None)
            client = _CLIENTS[key]
    store = QdrantStore(client, name, meta)
    try:
        present = store.exists()
    except Exception as exc:  # noqa: BLE001  (connection errors come in many client-specific types)
        raise QdrantUnavailable(
            f"Cannot reach Qdrant at {where or q.get('mode')} ({type(exc).__name__}). Start the server "
            "(`./scripts/start_qdrant.sh`, or set VECTORSTORE_QDRANT_URL to the right address).") from None
    if not present:
        raise RuntimeError(
            f"Qdrant collection {name!r} not found at {where or q.get('mode')}. Run "
            "`python buildSemanticDb.py ...` first (it creates a new collection).")
    verified = (key, name, meta.model, meta.dimension)
    if verified not in _VERIFIED:
        store.check_meta()
        _VERIFIED.add(verified)
    return QdrantCollection(store, exact=bool(q.get("exact")), ef=q.get("ef"))


def new_store(name: str, qdrant_config: dict, meta: IndexMeta) -> QdrantStore:
    """A store on a collection that does NOT exist yet (index building). Never replaces one: the caller
    checks `exists()`. Uses its own client (not the cached runtime ones) and the same key reader as
    `open_collection`; close it with `store.close()`."""
    q = dict(qdrant_config or {})
    client = open_client(q.get("mode", "server"), path=q.get("path"), url=q.get("url"),
                         api_key=os.getenv(ENV_API_KEY) or None)
    return QdrantStore(client, name, meta)


def close_clients() -> None:
    """Close every cached client (tests, shutdown)."""
    with _LOCK:
        for client in _CLIENTS.values():
            client.close()
        _CLIENTS.clear()
        _VERIFIED.clear()
