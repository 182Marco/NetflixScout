"""One shard = one API request = one .npz file (float32 vectors + unit ids + meta). Written atomically, validated on read."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .settings import DIMENSIONS, MODEL, SHARDS


def shard_path(index: int, directory: Path | None = None) -> Path:
    return (directory or SHARDS) / f"shard_{index:05d}.npz"


@dataclass
class Shard:
    index: int
    unit_ids: list[str]
    vectors: np.ndarray
    tokens: np.ndarray       # tiktoken count per unit
    meta: dict               # usage_tokens, plan_hash, model, dimensions, created_at, request_id


def write_shard(path: Path, index: int, unit_ids: list[str], vectors: np.ndarray, tokens: list[int], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        np.savez(f, vectors=vectors.astype(np.float32), unit_ids=np.array(unit_ids), tokens=np.array(tokens, dtype=np.int32),
                 meta=np.array(json.dumps({**meta, "index": index, "model": MODEL, "dimensions": DIMENSIONS})))
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic: a shard file is either complete or absent


def read_shard(path: Path) -> Shard:
    with np.load(path, allow_pickle=False) as z:
        meta = json.loads(str(z["meta"]))
        return Shard(meta["index"], [str(x) for x in z["unit_ids"]], z["vectors"], z["tokens"], meta)
