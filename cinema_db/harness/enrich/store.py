"""Append-only snapshot of the phase-4 Wikidata responses, in the SAME format the film and series projects use
(`requests.jsonl` + `bodies/<sha256>.json.gz`), so `build.snapshot.Snapshot` reads it unchanged.

Every response is stored byte for byte and verified by its sha256 on read. A request is identified by `key` (sha256 of its endpoint and
canonical parameters): a stored key is never requested again (resume), and a failed request is recorded in `errors.jsonl`, never as data.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "cinema_db/data/wikidata_phase4"


def request_key(endpoint: str, params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class PhaseStore:
    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = Path(root)
        (self.root / "bodies").mkdir(parents=True, exist_ok=True)
        self.index = self.root / "requests.jsonl"
        self.errors = self.root / "errors.jsonl"
        self.keys: set[str] = set()
        if self.index.is_file():
            for line in self.index.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.keys.add(json.loads(line)["key"])

    def has(self, key: str) -> bool:
        return key in self.keys

    def save(self, endpoint: str, params: dict[str, Any], body: bytes, status: int, meta: dict[str, Any]) -> str:
        key = request_key(endpoint, params)
        sha = hashlib.sha256(body).hexdigest()
        path = self.root / "bodies" / f"{sha}.json.gz"
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(body, 6, mtime=0))
            os.replace(tmp, path)
        record = {"acquired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bytes": len(body), "endpoint": endpoint, "key": key, "params": params,
                  "sha256": sha, "status": status, **meta}
        with self.index.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.keys.add(key)
        return key

    def error(self, endpoint: str, params: dict[str, Any], status: int | None, reason: str, meta: dict[str, Any]) -> None:
        record = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": request_key(endpoint, params), "endpoint": endpoint, "status": status, "reason": reason, **meta}
        with self.errors.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
