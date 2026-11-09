"""Acquisition of the IMDb bulk datasets (A1). The ONLY network code of this step; one dataset per invocation.

    python -m cinema_db.harness.acquire.imdb fetch title.basics
    python -m cinema_db.harness.acquire.imdb status

Only the six datasets approved by the owner can be fetched, only from the official host. Each file is streamed to a
`.part`, hashed while it arrives, checked against Content-Length, renamed, made read-only (0444), and recorded in
`manifest.json` (URL, final URL, HTTP status, Last-Modified, bytes, sha256, UTC time). A dataset already in the manifest
is never downloaded again (idempotent); a file whose bytes or hash do not match the manifest is reported, never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = ROOT / "cinema_db/data/imdb_snapshot"
BASE_URL = "https://datasets.imdbws.com/"
ALLOWED_HOST = "datasets.imdbws.com"
APPROVED = ("title.basics", "name.basics", "title.principals", "title.crew", "title.ratings", "title.episode")  # ratings and episode: owner, 2026-11-08
USER_AGENT = "NetflixScout-A1/1.0 (personal research; python-urllib)"
CHUNK = 1 << 20


class AcquisitionError(RuntimeError):
    pass


def _manifest_path(directory: Path) -> Path:
    return directory / "manifest.json"


def read_manifest(directory: Path) -> dict:
    path = _manifest_path(directory)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"datasets": {}}


def _write_manifest(directory: Path, manifest: dict) -> None:
    tmp = _manifest_path(directory).with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(_manifest_path(directory))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(name: str, directory: Path = SNAPSHOT_DIR, *, base_url: str = BASE_URL, allowed_host: str | None = ALLOWED_HOST,
          log=sys.stderr) -> dict:
    if name not in APPROVED:
        raise AcquisitionError(f"{name!r} is not one of the approved datasets {APPROVED}")
    url = f"{base_url}{name}.tsv.gz"
    if allowed_host and urllib.parse.urlparse(url).hostname != allowed_host:
        raise AcquisitionError("host not allowed")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(directory)
    target = directory / f"{name}.tsv.gz"
    known = manifest["datasets"].get(name)
    if known:
        if not target.is_file() or target.stat().st_size != known["bytes"]:
            raise AcquisitionError(f"{target} does not match the manifest; refusing to overwrite")
        print(f"{name}: already acquired ({known['bytes']} bytes, sha256 {known['sha256'][:16]}…), nothing downloaded", file=log)
        return known
    if target.exists():
        raise AcquisitionError(f"{target} exists but is not in the manifest; refusing to overwrite")
    part = target.with_suffix(".gz.part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = datetime.now(timezone.utc)
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:  # noqa: S310 (host checked above)
        status = getattr(response, "status", 200)
        expected = response.headers.get("Content-Length")
        last_modified = response.headers.get("Last-Modified")
        final_url = response.geturl()
        if allowed_host and urllib.parse.urlparse(final_url).hostname != allowed_host:
            raise AcquisitionError("redirected to a host that is not allowed")
        for chunk in iter(lambda: response.read(CHUNK), b""):
            out.write(chunk)
            digest.update(chunk)
            total += len(chunk)
    if expected is not None and int(expected) != total:
        part.unlink(missing_ok=True)
        raise AcquisitionError(f"{name}: received {total} bytes, Content-Length said {expected}")
    part.replace(target)
    os.chmod(target, 0o444)
    entry = {"url": url, "final_url": final_url, "http_status": status, "last_modified": last_modified, "bytes": total,
             "sha256": digest.hexdigest(), "retrieved_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "file": target.name, "client": USER_AGENT}
    manifest["datasets"][name] = entry
    _write_manifest(directory, manifest)
    print(f"{name}: {total} bytes, sha256 {entry['sha256'][:16]}…", file=log)
    return entry


def verify(directory: Path = SNAPSHOT_DIR) -> dict[str, str]:
    """Re-hashes every archived file against the manifest (offline)."""
    out = {}
    for name, entry in read_manifest(directory)["datasets"].items():
        path = directory / entry["file"]
        out[name] = "ok" if path.is_file() and path.stat().st_size == entry["bytes"] and sha256_file(path) == entry["sha256"] else "MISMATCH"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("name", choices=APPROVED)
    f.add_argument("--dir", type=Path, default=None, help="snapshot folder (default: cinema_db/data/imdb_snapshot/<today UTC>)")
    sub.add_parser("status").add_argument("--dir", type=Path, default=None)
    sub.add_parser("verify").add_argument("--dir", type=Path, default=None)
    args = parser.parse_args(argv)
    directory = args.dir or (SNAPSHOT_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if args.cmd == "fetch":
        fetch(args.name, directory)
    elif args.cmd == "status":
        print(json.dumps(read_manifest(directory), indent=1, sort_keys=True))
    else:
        print(json.dumps(verify(directory), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
