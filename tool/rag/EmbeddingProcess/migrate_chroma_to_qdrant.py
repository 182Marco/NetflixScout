"""Copy an existing Chroma index (vectors, documents, metadata) into Qdrant, without re-embedding.

Offline tool. Chroma is only READ and no embedding API is called. The target collection is created
if missing (never replaced or emptied); writes are idempotent upserts keyed by a deterministic
UUID, so a run can be repeated or resumed without duplicating points.

    python -m tool.rag.EmbeddingProcess.migrate_chroma_to_qdrant \
        --chroma-dir COPY --url http://127.0.0.1:6333 --run-dir DIR

`--chroma-dir` must be a COPY of the index: the Chroma client may write bookkeeping rows when it
opens a folder, so the original `dbVettoriale/openai` and any backup folder are refused.
Validation is a separate step (`validate_migration.py`); this script alone never declares success.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tool.rag.FromQueryEmbeddingToRes.store import StorePoint
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

ROOT = Path(__file__).resolve().parents[3]
COLLECTION = "netflix_scout"
MODEL = "text-embedding-3-small"
DIMENSION = 1536
PROTECTED_MARKERS = ("Backups/NetflixScout",)


def check_source(path: Path) -> None:
    """Refuse the live index and any backup: only a disposable copy may be opened."""
    resolved = path.resolve()
    original = (ROOT / "dbVettoriale" / "openai").resolve()
    if resolved == original or original in resolved.parents:
        raise SystemExit(f"refused: {path} is the original index; migrate from a restored copy")
    if any(marker in resolved.as_posix() for marker in PROTECTED_MARKERS):
        raise SystemExit(f"refused: {path} looks like a backup folder; migrate from a restored copy")
    if not resolved.is_dir():
        raise SystemExit(f"refused: {path} is not a folder")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Run:
    """Progress file + log file of one migration run (resumable)."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.progress_path = directory / "progress.json"
        self.log_path = directory / "migration.log"

    def log(self, message: str) -> None:
        line = f"{_utc()} {message}"
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def load(self) -> dict | None:
        if not self.progress_path.exists():
            return None
        return json.loads(self.progress_path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        tmp = self.progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        tmp.replace(self.progress_path)  # atomic: an interruption never leaves a torn file


def _to_points(page: dict) -> list[StorePoint]:
    return [
        StorePoint(
            id=page["ids"][i],
            vector=np.asarray(page["embeddings"][i], dtype=np.float32).tolist(),
            document=page["documents"][i] or "",
            metadata=dict(page["metadatas"][i] or {}),
        )
        for i in range(len(page["ids"]))
    ]


def _upsert_with_retry(store: QdrantStore, points: list[StorePoint], run: Run, retries: int) -> None:
    for attempt in range(1, retries + 1):
        try:
            store.upsert(points)
            return
        except Exception as exc:  # noqa: BLE001  (client errors are not a single type)
            run.log(f"upsert failed (attempt {attempt}/{retries}): {type(exc).__name__}: {str(exc)[:200]}")
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def migrate(
    *,
    chroma_collection,
    store: QdrantStore,
    run: Run,
    batch_size: int = 500,
    max_batches: int | None = None,
    restart: bool = False,
    retries: int = 3,
) -> dict:
    """Copy every point. Returns the final state; `complete` is True only when all were written.

    That is a statement about writing, not about correctness: run the validation afterwards.
    """
    total = chroma_collection.count()
    if total == 0:
        raise SystemExit("refused: the Chroma collection is empty")

    if store.exists():
        store.check_meta()  # refuses another model/dimension
        run.log(f"collection {store.collection!r} exists: resuming with idempotent upserts")
    else:
        store.create()
        run.log(f"collection {store.collection!r} created")

    state = run.load()
    if state and not restart:
        if state.get("source_count") != total or state.get("collection") != store.collection:
            raise SystemExit("progress file belongs to a different source/collection; use --restart")
        offset = int(state["next_offset"])
        run.log(f"resuming from offset {offset}/{total}")
    else:
        offset = 0
        state = {"collection": store.collection, "source_count": total, "next_offset": 0,
                 "started": _utc(), "batches_done": 0, "complete": False}

    batches = 0
    t0 = time.time()
    while offset < total:
        if max_batches is not None and batches >= max_batches:
            run.log(f"stopping after {batches} batches as requested (offset {offset}/{total})")
            break
        page = chroma_collection.get(
            limit=batch_size, offset=offset, include=["embeddings", "documents", "metadatas"])
        n = len(page["ids"])
        if n == 0:
            raise RuntimeError(f"Chroma returned no rows at offset {offset} of {total}")
        _upsert_with_retry(store, _to_points(page), run, retries)
        offset += n
        batches += 1
        state.update(next_offset=offset, batches_done=state["batches_done"] + 1, updated=_utc())
        run.save(state)
        if batches % 10 == 0 or offset >= total:
            run.log(f"written {offset}/{total} ({100 * offset / total:.1f}%) in {time.time() - t0:.0f}s")

    state["complete"] = offset >= total
    run.save(state)
    state["target_count"] = store.count()
    run.log(f"target count = {state['target_count']} (source {total}), writing complete = {state['complete']}")
    return state


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chroma-dir", required=True, help="a COPY of the Chroma index")
    ap.add_argument("--url", required=True, help="Qdrant server, e.g. http://127.0.0.1:6333")
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--run-dir", required=True, help="progress file and log")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--max-batches", type=int, default=None, help="stop early (to test resuming)")
    ap.add_argument("--restart", action="store_true", help="ignore the progress file (upserts stay idempotent)")
    args = ap.parse_args(argv)

    check_source(Path(args.chroma_dir))
    import chromadb  # lazy: only the migration needs it

    run = Run(Path(args.run_dir))
    run.log(f"source={args.chroma_dir} target={args.url} collection={args.collection}")
    collection = chromadb.PersistentClient(path=args.chroma_dir).get_collection(args.collection)
    client = open_client("server", url=args.url)
    store = QdrantStore(client, args.collection, IndexMeta(model=MODEL, dimension=DIMENSION))
    try:
        state = migrate(chroma_collection=collection, store=store, run=run, batch_size=args.batch_size,
                        max_batches=args.max_batches, restart=args.restart)
    finally:
        client.close()
    return 0 if state["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
