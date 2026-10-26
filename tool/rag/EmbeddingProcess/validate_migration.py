"""Validate a Chroma -> Qdrant migration point by point (the only thing that can call it done).

    python -m tool.rag.EmbeddingProcess.validate_migration \
        --chroma-dir COPY --url http://127.0.0.1:6333 --report FILE

Mandatory checks (all must pass): count, identifiers, dimension, metadata, documents, vectors
(inf-norm distance between the Qdrant vector and the normalised Chroma vector <= 1e-6, the tolerance
fixed in docs/qdrant_migration/protocol.md), derived fields (`title_norm`, `release_year_int`),
duplicates, and the index meta. Values that cannot be converted are reported, never invented.

Perimeter with the catalog (movies added from TMDb): points whose id starts with `tmdb:` are not part
of the migration and are only counted; on a corpus point exactly one extra key, an integer `tmdb_id`,
is accepted (a link). Everything else about corpus points - document, vector, every other metadata
key - is checked as before, so an altered corpus point or any other extra key still fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from tool.rag.EmbeddingProcess.migrate_chroma_to_qdrant import (
    COLLECTION, DIMENSION, MODEL, _utc, check_source)
from tool.rag.FromQueryEmbeddingToRes.store import norm_title, point_uuid, year_int
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

TOLERANCE = 1e-6  # fixed in protocol.md before the migration
RESERVED = ("document", "legacy_id", "title_norm", "release_year_int")
CATALOG_PREFIX = "tmdb:"  # ids of catalog points
LINK_KEY = "tmdb_id"  # the only key a corpus point may carry beyond the Chroma metadata
SAMPLE = 10  # anomalies listed per category; counts are always complete


class _Anomalies:
    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.samples: dict[str, list] = {}

    def add(self, kind: str, detail) -> None:
        self.counts[kind] += 1
        bucket = self.samples.setdefault(kind, [])
        if len(bucket) < SAMPLE:
            bucket.append(detail)


def _load_qdrant(store: QdrantStore, page: int) -> tuple[dict[str, dict], list[str], list[dict]]:
    """Corpus points of the target keyed by the stable string id, the ids seen twice, and the payloads
    of catalog points (kept apart: they are not part of the migration)."""
    points: dict[str, dict] = {}
    catalog: list[dict] = []
    offset = None
    duplicates = []
    while True:
        batch, offset = store.client.scroll(
            store.collection, limit=page, offset=offset, with_payload=True, with_vectors=True)
        for p in batch:
            payload = dict(p.payload or {})
            legacy = payload.get("legacy_id")
            if isinstance(legacy, str) and legacy.startswith(CATALOG_PREFIX):
                catalog.append(payload)
                continue
            if legacy in points:
                duplicates.append(legacy)
            points[legacy] = {"point_id": str(p.id), "payload": payload,
                              "vector": np.asarray(p.vector, dtype=np.float32)}
        if offset is None:
            break
    return points, duplicates, catalog


def validate(chroma_collection, store: QdrantStore, *, page: int = 500) -> dict:
    anomalies = _Anomalies()
    checks: dict[str, dict] = {}

    source_count = chroma_collection.count()
    target_count = store.count()
    qdrant, duplicates, catalog = _load_qdrant(store, page)

    try:
        store.check_meta()
        meta_ok, meta_detail = True, {"model": MODEL, "dimension": DIMENSION, "distance": "cosine"}
    except Exception as exc:  # noqa: BLE001
        meta_ok, meta_detail = False, str(exc)

    seen_ids: set[str] = set()
    max_err = 0.0
    worst_id = None
    id_digest, doc_digest = hashlib.sha256(), hashlib.sha256()
    missing = 0
    year_missing = year_converted = 0
    unconvertible: list[tuple[str, str]] = []
    unconvertible_count = 0
    non_string_meta = 0
    linked = 0

    offset = 0
    while offset < source_count:
        got = chroma_collection.get(
            limit=page, offset=offset, include=["embeddings", "documents", "metadatas"])
        n = len(got["ids"])
        if n == 0:
            anomalies.add("chroma_short_read", offset)
            break
        for i in range(n):
            lid = got["ids"][i]
            if lid in seen_ids:
                anomalies.add("duplicate_source_id", lid)
            seen_ids.add(lid)
            id_digest.update(lid.encode())
            doc = got["documents"][i] or ""
            doc_digest.update(doc.encode())
            meta = dict(got["metadatas"][i] or {})
            target = qdrant.get(lid)
            if target is None:
                missing += 1
                anomalies.add("missing_in_qdrant", lid)
                continue
            payload = target["payload"]

            if target["point_id"] != point_uuid(lid):
                anomalies.add("point_id_mismatch", lid)
            if payload.get("document") != doc:
                anomalies.add("document_mismatch", lid)

            if any(not isinstance(v, str) for v in meta.values()):
                non_string_meta += 1
                anomalies.add("non_string_chroma_metadata", lid)
            if LINK_KEY in payload:
                linked += 1
                if not isinstance(payload[LINK_KEY], int) or isinstance(payload[LINK_KEY], bool):
                    anomalies.add("tmdb_link_invalid", lid)
            carried = {k: v for k, v in payload.items() if k not in RESERVED and k != LINK_KEY}
            if carried != meta:
                anomalies.add("metadata_mismatch", {"id": lid, "only_chroma": sorted(set(meta) - set(carried)),
                                                    "only_qdrant": sorted(set(carried) - set(meta)),
                                                    "different": sorted(k for k in meta if k in carried and meta[k] != carried[k])})

            if payload.get("title_norm") != norm_title(meta.get("title")):
                anomalies.add("title_norm_mismatch", lid)

            raw_year = meta.get("release_year")
            expected = year_int(raw_year)
            if raw_year in (None, ""):
                year_missing += 1
                if "release_year_int" in payload:
                    anomalies.add("release_year_int_unexpected", lid)
            elif expected is None:
                unconvertible_count += 1
                if len(unconvertible) < 50:
                    unconvertible.append((lid, str(raw_year)))
                if "release_year_int" in payload:
                    anomalies.add("release_year_int_invented", lid)
            else:
                year_converted += 1
                if payload.get("release_year_int") != expected:
                    anomalies.add("release_year_int_mismatch", {"id": lid, "expected": expected,
                                                                "found": payload.get("release_year_int")})

            c_vec = np.asarray(got["embeddings"][i], dtype=np.float32)
            q_vec = target["vector"]
            if c_vec.shape != (DIMENSION,) or q_vec.shape != (DIMENSION,):
                anomalies.add("dimension_mismatch", {"id": lid, "chroma": list(c_vec.shape), "qdrant": list(q_vec.shape)})
                continue
            norm = float(np.linalg.norm(c_vec))
            if norm == 0.0 or not np.isfinite(norm):
                anomalies.add("unusable_chroma_vector", lid)
                continue
            err = float(np.abs(c_vec / norm - q_vec).max())
            if err > max_err:
                max_err, worst_id = err, lid
            if err > TOLERANCE:
                anomalies.add("vector_out_of_tolerance", {"id": lid, "error": err})
        offset += n

    extras = [lid for lid in qdrant if lid not in seen_ids]
    for lid in extras[:SAMPLE]:
        anomalies.add("extra_in_qdrant", lid)
    anomalies.counts["extra_in_qdrant"] = len(extras)

    def passed(*kinds: str) -> bool:
        return all(anomalies.counts.get(k, 0) == 0 for k in kinds)

    for payload in catalog:
        if payload.get("source") != "tmdb" or not isinstance(payload.get(LINK_KEY), int):
            anomalies.add("catalog_point_malformed", payload.get("legacy_id"))
    checks["count"] = {"ok": source_count == target_count - len(catalog) == len(seen_ids) == len(qdrant),
                       "source": source_count, "target": target_count, "catalog_points": len(catalog),
                       "corpus_points_linked_to_tmdb": linked,
                       "unique_source_ids": len(seen_ids), "unique_target_ids": len(qdrant)}
    checks["identifiers"] = {"ok": passed("missing_in_qdrant", "extra_in_qdrant", "point_id_mismatch",
                                          "duplicate_source_id") and not duplicates,
                             "qdrant_duplicates": len(duplicates)}
    checks["dimension"] = {"ok": passed("dimension_mismatch", "unusable_chroma_vector"), "expected": DIMENSION}
    checks["metadata"] = {"ok": passed("metadata_mismatch", "non_string_chroma_metadata")}
    checks["documents"] = {"ok": passed("document_mismatch")}
    checks["vectors"] = {"ok": passed("vector_out_of_tolerance", "dimension_mismatch", "unusable_chroma_vector")
                         and missing == 0,
                         "tolerance": TOLERANCE, "max_error": max_err, "worst_id": worst_id}
    checks["title_norm"] = {"ok": passed("title_norm_mismatch")}
    checks["release_year_int"] = {
        "ok": passed("release_year_int_mismatch", "release_year_int_unexpected", "release_year_int_invented"),
        "converted": year_converted, "no_year_in_source": year_missing,
        "not_convertible": unconvertible_count, "not_convertible_values": unconvertible,
    }
    checks["catalog_perimeter"] = {"ok": passed("tmdb_link_invalid", "catalog_point_malformed"),
                                   "catalog_points": len(catalog), "linked": linked}
    checks["index_meta"] = {"ok": meta_ok, "detail": meta_detail}

    all_ok = all(c["ok"] for c in checks.values())
    return {
        "validated_at": _utc(),
        "passed": all_ok,
        "checks": checks,
        "anomaly_counts": dict(anomalies.counts),
        "anomaly_samples": anomalies.samples,
        "digests": {"sorted_order_ids_sha256": id_digest.hexdigest(), "documents_in_source_order_sha256": doc_digest.hexdigest()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chroma-dir", required=True, help="a COPY of the Chroma index")
    ap.add_argument("--url", required=True)
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--report", required=True)
    args = ap.parse_args(argv)

    check_source(Path(args.chroma_dir))
    import chromadb

    collection = chromadb.PersistentClient(path=args.chroma_dir).get_collection(args.collection)
    client = open_client("server", url=args.url)
    store = QdrantStore(client, args.collection, IndexMeta(model=MODEL, dimension=DIMENSION))
    try:
        report = validate(collection, store)
        report["server_version"] = client.info().version
    finally:
        client.close()
    Path(args.report).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps({k: report[k] for k in ("passed", "anomaly_counts")}, indent=1) + "\n")
    for name, check in report["checks"].items():
        sys.stdout.write(f"  {'OK  ' if check['ok'] else 'FAIL'} {name}\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
