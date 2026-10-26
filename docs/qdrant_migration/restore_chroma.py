"""Restore the Chroma index backup into a NEW folder and verify it (no overwrite, no API calls).

    python docs/qdrant_migration/restore_chroma.py --backup DIR --dest NEW_DIR \
        [--baseline DIR --query-id q01]

Safety rules, enforced in code:
- `--dest` must not exist (the script creates it), so nothing is ever replaced;
- `--dest` must not be, or be inside, the repo's `dbVettoriale/` (resolved paths, symlinks followed);
- the backup is only read; every file is re-hashed against `openai.copy.sha256` and
  `openai.src.sha256` (both must agree) before and after the copy;
- the optional query check replays a saved query vector against the restored copy and compares
  it with the baseline top-50: no OpenAI/Cohere call is made.

Putting the restored folder back into use is a manual, separate decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


def tree_hashes(folder: Path) -> dict[str, str]:
    return {
        "./" + p.relative_to(folder).as_posix(): sha256(p)
        for p in sorted(folder.rglob("*")) if p.is_file()
    }


def check_destination(dest: Path) -> None:
    resolved = dest.resolve()
    protected = (ROOT / "dbVettoriale").resolve()
    if resolved == protected or protected in resolved.parents:
        raise SystemExit(f"refused: destination is inside {protected}")
    if dest.exists():
        raise SystemExit(f"refused: destination already exists: {dest}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--query-id", default="q01")
    args = parser.parse_args()

    backup = Path(args.backup)
    dest = Path(args.dest)
    check_destination(dest)

    copy_manifest = read_manifest(backup / "openai.copy.sha256")
    src_manifest = read_manifest(backup / "openai.src.sha256")
    if copy_manifest != src_manifest:
        raise SystemExit("backup manifests disagree: original and copy hashes differ")
    if tree_hashes(backup / "openai") != copy_manifest:
        raise SystemExit("backup content does not match its manifest")
    print(f"backup verified: {len(copy_manifest)} files")

    shutil.copytree(backup / "openai", dest)
    restored = tree_hashes(dest)
    if restored != copy_manifest:
        raise SystemExit("restored content does not match the manifest")
    print(f"restore verified: {len(restored)} files identical to the manifest")

    if args.baseline:
        import numpy as np

        sys.path.insert(0, str(ROOT))
        from tool.rag.FromQueryEmbeddingToRes import vectorstore

        base = Path(args.baseline)
        record = json.loads((base / f"{args.query_id}.json").read_text(encoding="utf-8"))
        vector = np.load(base / f"{args.query_id}.vec.npy")
        collection = vectorstore.apri_collection("netflix_scout", db_dir=dest)
        raw = collection.query(query_embeddings=[vector.tolist()], n_results=50)
        ids = raw["ids"][0]
        expected = [row["id"] for row in record["chroma_raw_top50"]]
        if ids != expected:
            raise SystemExit("restored index answers differently from the baseline")
        print(f"query replay: top-50 of {args.query_id} identical to the baseline, count={collection.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
