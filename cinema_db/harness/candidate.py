"""The one place that names the schema-4 database the validations target, and checks that a file really is it (FASE 21).

A validation must not run on "whatever file the default path points to": `identify` reads the file READ-ONLY, compares schema version and the stored data digest with
`EXPECTED` and raises `CandidateMismatch` otherwise. There is no fallback to another file. `recompute=True` also recomputes the data digest from the rows (about a minute
for 1.1 GB) and compares it with the stored one, which proves the content, not only the label.

When a new candidate is built, change `EXPECTED` here (path, digest) in the same commit that records its verification; every default path of the harness follows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

EXPECTED: dict[str, str] = {
    "path": "cinema_db/data/cinema.v4.candidate6.sqlite3",
    "schema_version": "4",
    "content_sha256": "27d2d09e1c0764b85b5734fc5a5ca7c7001e817f0e240c62775440a89b8147ea",
}
EXPECTED_PATH = ROOT / EXPECTED["path"]


class CandidateMismatch(RuntimeError):
    """The file is missing or is not the expected database."""


def identify(path: Path | str | None = None, *, recompute: bool = False, strict_name: bool = True) -> dict[str, Any]:
    """Path, schema version and data digest of `path` (default: the expected candidate), checked against `EXPECTED`. Read-only. Raises on any difference.
    `strict_name` also requires the file name to be the expected one: the data digest does not cover indexes, so candidate4 and candidate5 share it."""
    target = Path(path) if path is not None else EXPECTED_PATH
    if not target.is_file():
        raise CandidateMismatch(f"{target} does not exist (expected {EXPECTED['path']})")
    conn = sqlite3.connect(f"file:{target}?mode=ro&immutable=1", uri=True)
    try:
        try:
            info = dict(conn.execute("SELECT key, value FROM build_info").fetchall())
        except sqlite3.DatabaseError as exc:
            raise CandidateMismatch(f"{target} has no readable build_info ({type(exc).__name__})") from None
        problems = ([f"file name {target.name!r} != {Path(EXPECTED['path']).name!r}"] if strict_name and target.name != Path(EXPECTED['path']).name else [])
        problems += [f"{key}: {info.get(key)!r} != {want!r}" for key, want in EXPECTED.items() if key != "path" and info.get(key) != want]
        out = {"path": str(target), "schema_version": info.get("schema_version"), "content_sha256": info.get("content_sha256"), "recomputed": None}
        if recompute and not problems:
            from cinema_db.harness.build.build import content_digest
            out["recomputed"] = content_digest(conn)
            if out["recomputed"] != EXPECTED["content_sha256"]:
                problems.append(f"recomputed digest {out['recomputed']} != {EXPECTED['content_sha256']}")
    finally:
        conn.close()
    if problems:
        raise CandidateMismatch(f"{target.name} is not the expected candidate: " + "; ".join(problems))
    return out
