"""Verified copy of a Qdrant storage folder, to make before the catalog is ever switched on.

    python docs/qdrant_migration/catalog/backup_storage.py backup --storage DIR --dest NEWDIR
    python docs/qdrant_migration/catalog/backup_storage.py verify --storage DIR --dest DIR2

TMDb films are not rebuildable from Chroma, so a copy is the only way back. Rules: the server must be
stopped (a live storage is not a consistent copy: the script refuses when a lock/port is detected via
`--url` being reachable); the destination must not exist (nothing is ever overwritten) and must not
be inside the source; the source is only read. `backup` writes a SHA-256 manifest of every file and
re-reads the copy against it; `verify` compares two folders (or a copy against its manifest) later.
No network call is made except the optional reachability check of `--url`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

MANIFEST = "MANIFEST.sha256.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_of(folder: Path) -> dict[str, dict]:
    return {p.relative_to(folder).as_posix(): {"sha256": digest(p), "bytes": p.stat().st_size}
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name != MANIFEST}


def server_is_up(url: str | None) -> bool:
    if not url:
        return False
    try:
        urllib.request.urlopen(url, timeout=2).close()
        return True
    except Exception:  # noqa: BLE001  (any failure means nothing is answering)
        return False


def check_paths(storage: Path, dest: Path) -> str | None:
    storage, dest = storage.resolve(), dest.resolve()
    if not storage.is_dir():
        return f"source {storage} is not a folder"
    if dest.exists():
        return f"destination {dest} already exists: nothing is overwritten"
    if dest == storage or storage in dest.parents or dest in storage.parents:
        return "destination and source must be separate folders"
    return None


def backup(storage: Path, dest: Path, url: str | None = None) -> dict:
    problem = check_paths(storage, dest)
    if problem:
        raise SystemExit(f"Refused: {problem}")
    if server_is_up(url):
        raise SystemExit(f"Refused: a server answers at {url}; stop it before copying the storage")
    source = manifest_of(storage)
    shutil.copytree(storage, dest)
    copy = manifest_of(dest)
    after = manifest_of(storage)  # a source that moved during the copy makes the copy untrustworthy
    if after != source:
        moved = sorted(k for k in set(source) | set(after) if source.get(k) != after.get(k))
        raise SystemExit(f"Refused: the source changed during the copy ({len(moved)} files, e.g. {moved[:3]}); "
                         f"is the server really stopped? {dest} is NOT a valid copy: leave it unused and retry into a new folder")
    if copy != source:
        bad = sorted(k for k in set(source) | set(copy) if source.get(k) != copy.get(k))
        raise SystemExit(f"Copy does not match the source ({len(bad)} files, e.g. {bad[:3]}); {dest} is NOT a valid copy: leave it unused and retry into a new folder")
    if any(p.is_symlink() for p in dest.rglob("*")):
        raise SystemExit(f"Refused: the copy contains symbolic links; {dest} is NOT a valid copy")
    (dest / MANIFEST).write_text(json.dumps({"files": copy}, indent=1), encoding="utf-8")
    return {"files": len(copy), "bytes": sum(v["bytes"] for v in copy.values())}


def verify(storage: Path, dest: Path) -> dict:
    """Recomputes the hashes of both folders (a stored manifest is only a record, never trusted)."""
    left, right = manifest_of(storage), manifest_of(dest)
    different = sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))
    recorded = json.loads((dest / MANIFEST).read_text())["files"] if (dest / MANIFEST).exists() else None
    drift = None if recorded is None else sorted(k for k in set(recorded) | set(right) if recorded.get(k) != right.get(k))
    return {"identical": not different and not drift, "different": different[:20],
            "changed_since_backup": drift[:20] if drift else [], "files": len(left)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup"); b.add_argument("--storage", required=True); b.add_argument("--dest", required=True); b.add_argument("--url")
    v = sub.add_parser("verify"); v.add_argument("--storage", required=True); v.add_argument("--dest", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "backup":
        result = backup(Path(args.storage), Path(args.dest), args.url)
    else:
        result = verify(Path(args.storage), Path(args.dest))
    sys.stdout.write(json.dumps(result, indent=1) + "\n")
    return 0 if result.get("identical", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
