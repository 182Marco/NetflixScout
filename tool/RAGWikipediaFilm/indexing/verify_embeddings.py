"""Offline verification of the embedding shards against films.jsonl (no API call). Also writes manifests/embeddings_manifest.json."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter

import numpy as np

from . import settings as S
from .embed_run import usd
from .shardio import read_shard, shard_path
from .units import Unit, build_units, make_shards, plan_hash


def _file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_all(units: list[Unit], directory=None):
    """(vectors in unit order, list of shard metas). Raises if a shard is missing or does not match the plan."""
    shards = make_shards(units)
    phash = plan_hash(units)
    blocks, metas = [], []
    for i, sh in enumerate(shards):
        p = shard_path(i, directory)
        if not p.exists():
            raise FileNotFoundError(f"missing shard {i}: {p.name}")
        s = read_shard(p)
        if s.unit_ids != [u.unit_id for u in sh] or s.meta.get("plan_hash") != phash:
            raise ValueError(f"shard {i} does not match films.jsonl / the plan")
        blocks.append(s.vectors); metas.append(s.meta)
    return np.concatenate(blocks), metas


def verify(write_manifest: bool = True, directory=None) -> dict:
    directory = directory or S.SHARDS
    units = build_units()
    vectors, metas = load_all(units, directory)
    ids = [u.unit_id for u in units]
    norms = np.linalg.norm(vectors, axis=1)
    per_film = Counter(u.film_id for u in units)
    chunked = {f: n for f, n in per_film.items() if n > 1}
    files = sorted(directory.glob("shard_*.npz"))
    api_tokens = sum(int(m["usage_tokens"]) for m in metas)
    checks = {
        "films_in_source": len(per_film),
        "units": len(units),
        "vectors": int(vectors.shape[0]),
        "vectors_equal_units": vectors.shape[0] == len(units),
        "dimension": int(vectors.shape[1]),
        "dimension_ok": vectors.shape[1] == S.DIMENSIONS,
        "nan": int(np.isnan(vectors).sum()),
        "inf": int(np.isinf(vectors).sum()),
        "zero_vectors": int((norms == 0).sum()),
        "norm_min": float(norms.min()), "norm_max": float(norms.max()),
        "duplicate_unit_ids": len(ids) - len(set(ids)),
        "duplicate_vectors": int(len(vectors) - len({v.tobytes() for v in vectors})),
        "films_without_vector": len(set(per_film) - {i.split("#")[0] for i in ids}),
        "chunked_films": {f: n for f, n in sorted(chunked.items())},
        "extra_shard_files": len(files) - len(metas),
        "shard_files": len(files),
        "shard_bytes": sum(p.stat().st_size for p in files),
        "api_tokens": api_tokens,
        "local_tokens": sum(u.tokens for u in units),
        "api_usd": round(usd(api_tokens), 4),
        "models": sorted({m["model"] for m in metas}), "dimensions_requested": sorted({m["dimensions"] for m in metas}),
    }
    checks["ok"] = bool(
        checks["vectors_equal_units"] and checks["dimension_ok"] and checks["nan"] == 0 and checks["inf"] == 0
        and checks["zero_vectors"] == 0 and checks["duplicate_unit_ids"] == 0 and checks["films_without_vector"] == 0
        and checks["extra_shard_files"] == 0 and abs(checks["norm_min"] - 1) < 1e-2 and abs(checks["norm_max"] - 1) < 1e-2
    )
    if write_manifest and checks["ok"]:
        manifest = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "run_id": S.RUN_ID, "model": S.MODEL,
                    "dimensions": S.DIMENSIONS, "plan_hash": plan_hash(units), "films_jsonl_sha256": _file_sha256(S.FILMS),
                    "checks": checks, "shards": {p.name: _file_sha256(p) for p in files}}
        S.MANIFEST.parent.mkdir(exist_ok=True)
        S.MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return checks
