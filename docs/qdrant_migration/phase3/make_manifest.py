"""Write the Phase 3 manifest: versions, configuration, provenance, integrity checks and outcome.

    python docs/qdrant_migration/phase3/make_manifest.py --url http://127.0.0.1:6333 \
        --source COPY --backup ~/Backups/NetflixScout/pre-qdrant-20261026 --storage DIR \
        --reports R1.json R2.json --out manifest.json

Read-only on every data folder. The outcome is derived from the validation reports and the
integrity checks; it is never set by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient  # noqa: E402

from tool.rag.EmbeddingProcess.migrate_chroma_to_qdrant import COLLECTION, DIMENSION, MODEL  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.settings import QDRANT_CLIENT_VERSION, QDRANT_SERVER_VERSION  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree(folder: Path) -> dict[str, str]:
    return {"./" + p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def manifest_of(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


def logical_tables(db: Path) -> dict[str, str]:
    """Row-level digest of every table (read-only, immutable): ignores lock bookkeeping bytes."""
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro&immutable=1", uri=True)
    out = {}
    for (name,) in conn.execute("select name from sqlite_master where type='table' order by 1"):
        digest = hashlib.sha256()
        for row in sorted(conn.execute(f"select * from {name}"), key=repr):
            digest.update(repr(row).encode())
        out[name] = digest.hexdigest()
    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--backup", required=True)
    ap.add_argument("--storage", required=True)
    ap.add_argument("--reports", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    backup = Path(args.backup)
    original = ROOT / "dbVettoriale" / "openai"
    client = QdrantClient(url=args.url)
    info = client.get_collection(COLLECTION)
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.reports]

    backup_ok = tree(backup / "openai") == manifest_of(backup / "openai.copy.sha256")
    original_bytes = tree(original)
    original_bytes_match = original_bytes == manifest_of(backup / "openai.src.sha256")
    original_tables = logical_tables(original / "chroma.sqlite3")
    backup_tables = logical_tables(backup / "openai" / "chroma.sqlite3")
    differing = sorted(t for t in original_tables if original_tables[t] != backup_tables.get(t))
    hnsw_same = all(original_bytes[k] == v for k, v in manifest_of(backup / "openai.src.sha256").items() if k != "./chroma.sqlite3")
    storage = Path(args.storage)
    storage_resolved = storage.resolve()

    integrity = {
        "backup_files_match_manifest": backup_ok,
        "original_bytes_match_pre_migration_manifest": original_bytes_match,
        "original_sqlite_differing_tables": differing,
        "original_non_sqlite_files_unchanged": hnsw_same,
        "original_data_logically_identical_to_backup": not [t for t in differing if t != "acquire_write"],
        "target_is_separate_from_original_and_backup": (
            original.resolve() not in storage_resolved.parents and backup.resolve() not in storage_resolved.parents
            and storage_resolved != original.resolve()
        ),
    }
    all_validations = all(r["passed"] for r in reports)
    outcome = {
        "validation_reports": [Path(p).name for p in args.reports],
        "all_validations_passed": all_validations,
        "points": info.points_count,
        "migration_validated": bool(
            all_validations and info.points_count == reports[-1]["checks"]["count"]["source"]
            and integrity["backup_files_match_manifest"] and integrity["target_is_separate_from_original_and_backup"]
            and integrity["original_data_logically_identical_to_backup"]
        ),
    }
    result = {
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "versions": {
            "qdrant_client_installed": importlib.metadata.version("qdrant-client"),
            "qdrant_client_pinned": QDRANT_CLIENT_VERSION,
            "qdrant_server_pinned": QDRANT_SERVER_VERSION,
            "qdrant_server_running": client.info().version,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "chromadb": importlib.metadata.version("chromadb"),
        },
        "configuration": {
            "collection": COLLECTION, "embedding_model": MODEL, "dimension": DIMENSION, "distance": "cosine",
            "server_url": args.url, "server_binding": "127.0.0.1",
            "server_binary": "official release qdrant-x86_64-apple-darwin v1.20.0 (not the Docker image)",
            "storage_path": storage_resolved.as_posix(), "batch_size": 500,
            "point_id": "uuid5(namespace 6f1c2e1e-0c53-4b57-9d1a-4f5d3c1e7a10, legacy string id)",
            "payload_added": ["document", "legacy_id", "title_norm", "release_year_int"],
            "payload_indexes": sorted(info.payload_schema),
            "vector_tolerance": 1e-6,
        },
        "provenance": {
            "source": "fresh copy restored from the verified backup (restore_chroma.py); Chroma opened only on that copy",
            "source_path": args.source,
            "backup_manifest_files": manifest_of(backup / "openai.copy.sha256"),
        },
        "target_collection": {
            "status": str(info.status), "points": info.points_count, "indexed_vectors": info.indexed_vectors_count,
            "segments": info.segments_count, "storage_size_bytes": sum(p.stat().st_size for p in storage.rglob("*") if p.is_file()),
            "collection_metadata": dict(getattr(info.config, "metadata", None) or {}),
        },
        "integrity": integrity,
        "outcome": outcome,
    }
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps({"integrity": integrity, "outcome": outcome}, indent=1) + "\n")
    client.close()
    return 0 if outcome["migration_validated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
