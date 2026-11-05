"""Builds and checks the dedicated Qdrant collection `wikipedia_films_it`.

Same server and same configuration style as the existing RAG (1536 dims, cosine, payload on disk, keyword/integer payload
indexes) but a separate collection with its own deterministic point ids. The old collection is only READ (point count, for
the "untouched" check), never written. One point per embedding unit: one for every film, several for the 5 exceptional ones.

Rebuild:  python -m tool.RAGWikipediaFilm.indexing index --recreate     (drops and rebuilds ONLY `wikipedia_films_it`)"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.request
import uuid

import numpy as np
from qdrant_client import QdrantClient, models

from . import settings as S
from .units import Unit, build_units, read_films
from .verify_embeddings import load_all, verify

PAYLOAD_INDEXES = [
    ("film_id", models.PayloadSchemaType.KEYWORD), ("wikipedia_page_id", models.PayloadSchemaType.INTEGER),
    ("year", models.PayloadSchemaType.INTEGER), ("genres", models.PayloadSchemaType.KEYWORD),
    ("country", models.PayloadSchemaType.KEYWORD), ("language", models.PayloadSchemaType.KEYWORD),
    ("director_names", models.PayloadSchemaType.KEYWORD), ("imdb_id", models.PayloadSchemaType.KEYWORD),
    ("title_norm", models.PayloadSchemaType.KEYWORD), ("chunked", models.PayloadSchemaType.BOOL),
]


def point_id(film_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(S.QDRANT_NAMESPACE, f"{film_id}:{chunk_index}"))


def norm_title(title: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def build_payload(film: dict, unit: Unit) -> dict:
    """The whole film record (nothing is lost) plus flat helper fields and the chunk coordinates."""
    payload = dict(film)
    payload.update({
        "unit_id": unit.unit_id, "chunk_index": unit.chunk_index, "chunk_count": unit.chunk_count,
        "chunked": unit.chunk_count > 1, "title_norm": norm_title(film["title"]),
        "director_names": [d["name"] for d in film.get("director", [])],
        "actor_names": [a["name"] for a in film.get("actors", [])],
    })
    if unit.chunk_count > 1:
        payload["chunk_text"] = unit.text  # the synopsis is the complete text, chunk_text is the part this vector represents
    return payload


def make_client(url: str | None = None) -> QdrantClient:
    return QdrantClient(url=url or S.QDRANT_URL, timeout=180)


def server_version(url: str | None = None) -> str | None:
    try:
        with urllib.request.urlopen(url or S.QDRANT_URL, timeout=5) as r:
            return json.loads(r.read())["version"]
    except Exception:
        return None


def other_collections(client: QdrantClient) -> dict[str, int]:
    return {c.name: client.count(c.name, exact=True).count for c in client.get_collections().collections if c.name != S.COLLECTION
            and not c.name.startswith(S.TEST_PREFIX)}


def wait_green(client: QdrantClient, collection: str, timeout: float = 900) -> dict:
    t0 = time.time()
    while True:
        info = client.get_collection(collection)
        if str(info.status).lower().endswith("green"):
            return {"status": "green", "indexed_vectors": info.indexed_vectors_count, "seconds": round(time.time() - t0, 1)}
        if time.time() - t0 > timeout:
            return {"status": str(info.status), "indexed_vectors": info.indexed_vectors_count, "seconds": round(time.time() - t0, 1)}
        time.sleep(2)


def create_collection(client: QdrantClient, collection: str) -> None:
    client.create_collection(
        collection,
        vectors_config=models.VectorParams(size=S.DIMENSIONS, distance=models.Distance.COSINE),
        on_disk_payload=True,
    )
    for field, schema in PAYLOAD_INDEXES:
        client.create_payload_index(collection, field, schema)


def build_index(*, recreate: bool = False, client: QdrantClient | None = None, collection: str = S.COLLECTION,
                units: list[Unit] | None = None, vectors: np.ndarray | None = None, films: dict[str, dict] | None = None,
                skip_verify: bool = False) -> dict:
    S.assert_own_collection(collection)
    client = client or make_client()
    started = time.time()
    if units is None:
        report = verify(write_manifest=False)
        if not report["ok"]:
            raise SystemExit("embeddings do not verify, refusing to index (run `verify` and read the report)")
        units = build_units()
        vectors, _ = load_all(units)
    films = films or {f["film_id"]: f for f in read_films()}
    baseline = other_collections(client)
    exists = collection in {c.name for c in client.get_collections().collections}
    if exists and recreate:
        S.assert_own_collection(collection)
        client.delete_collection(collection)
        exists = False
    if not exists:
        create_collection(client, collection)
    done = 0
    for i in range(0, len(units), S.UPSERT_BATCH):
        batch = units[i:i + S.UPSERT_BATCH]
        client.upsert(collection, wait=True, points=[
            models.PointStruct(id=point_id(u.film_id, u.chunk_index), vector=vectors[i + k].tolist(),
                               payload=build_payload(films[u.film_id], u))
            for k, u in enumerate(batch)])
        done += len(batch)
    health = wait_green(client, collection)
    count = client.count(collection, exact=True).count
    return {"collection": collection, "points_upserted": done, "points_in_collection": count, "expected": len(units),
            "count_ok": count == len(units), "resumed_existing": exists, "index": health,
            "other_collections_before": baseline, "other_collections_after": other_collections(client),
            "seconds": round(time.time() - started, 1)}


def check_index(*, client: QdrantClient | None = None, collection: str = S.COLLECTION, units: list[Unit] | None = None,
                vectors: np.ndarray | None = None, films: dict[str, dict] | None = None, sample: int = 300,
                expected_other: dict[str, int] | None = None) -> dict:
    """Coherence between source dataset, embeddings and Qdrant (reads only)."""
    client = client or make_client()
    if units is None:
        units = build_units()
        vectors, _ = load_all(units)
    films = films or {f["film_id"]: f for f in read_films()}
    info = client.get_collection(collection)
    params = info.config.params.vectors
    ids, film_ids = set(), set()
    offset = None
    while True:  # all ids and film_ids (payload limited to film_id and chunk_index)
        pts, offset = client.scroll(collection, limit=2000, offset=offset, with_payload=["film_id", "chunk_index"], with_vectors=False)
        for p in pts:
            ids.add(str(p.id)); film_ids.add(p.payload["film_id"])
        if offset is None:
            break
    expected_ids = {point_id(u.film_id, u.chunk_index) for u in units}
    rng = np.random.default_rng(7)
    picks = rng.choice(len(units), size=min(sample, len(units)), replace=False)
    wrong_vec = wrong_payload = 0
    got = client.retrieve(collection, ids=[point_id(units[i].film_id, units[i].chunk_index) for i in picks], with_payload=True, with_vectors=True)
    by_id = {str(p.id): p for p in got}
    for i in picks:
        u = units[i]
        p = by_id.get(point_id(u.film_id, u.chunk_index))
        # Qdrant stores cosine vectors L2-normalised (the API's are within 1e-3 of unit norm): compare with the normalised source
        want = vectors[i] / np.linalg.norm(vectors[i])
        if p is None or not np.allclose(np.asarray(p.vector, dtype=np.float32), want, atol=1e-6):
            wrong_vec += 1
        f = films[u.film_id]
        if p is None or p.payload.get("film_id") != u.film_id or p.payload.get("synopsis") != f["synopsis"] or p.payload.get("title") != f["title"]:
            wrong_payload += 1
    chunked = {}
    for fid in sorted({u.film_id for u in units if u.chunk_count > 1}):
        pts, _ = client.scroll(collection, scroll_filter=models.Filter(must=[models.FieldCondition(key="film_id", match=models.MatchValue(value=fid))]),
                               limit=100, with_payload=["chunk_index", "chunk_count"], with_vectors=False)
        chunked[fid] = {"points": len(pts), "expected": next(u.chunk_count for u in units if u.film_id == fid)}
    other = other_collections(client)
    res = {
        "points": client.count(collection, exact=True).count, "expected_points": len(units),
        "distinct_films": len(film_ids), "expected_films": len({u.film_id for u in units}),
        "vector_size": params.size, "distance": str(params.distance), "ids_match_plan": ids == expected_ids,
        "sampled": len(picks), "sample_vector_mismatch": wrong_vec, "sample_payload_mismatch": wrong_payload,
        "chunked_films": chunked, "status": str(info.status), "indexed_vectors": info.indexed_vectors_count,
        "other_collections": other,
    }
    res["ok"] = bool(res["points"] == res["expected_points"] and res["distinct_films"] == res["expected_films"]
                     and res["vector_size"] == S.DIMENSIONS and "cosine" in res["distance"].lower() and res["ids_match_plan"]
                     and wrong_vec == 0 and wrong_payload == 0 and all(c["points"] == c["expected"] for c in chunked.values())
                     and (expected_other is None or other == expected_other))
    return res
