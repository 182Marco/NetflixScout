"""Phase S7: embeds the units of `data/s6/units.jsonl.gz` with text-embedding-3-large at 1536 dimensions.

Same method as the film project (copied, no import between the two): shards of one API request each, written atomically
as `.npz`, resumable (a valid shard is never requested again), shared pause on rate limits, hard budget. The API key
stays inside the openai library. A paid run needs `SERIES_EMBED_AUTHORIZED=yes` in the environment (never in `.env`).

    python -m pipelines.wikipedia_series.embed plan      # offline: shards, tokens, cost, how many are already done
    python -m pipelines.wikipedia_series.embed run       # PAID: requests the missing shards (resumable)
    python -m pipelines.wikipedia_series.embed verify    # offline: every shard against the plan, finite, right size
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .common import DATA_DIR

MODEL = "text-embedding-3-large"
DIMENSIONS = 1536
PRICE_PER_M = 0.13
MAX_USD = 6.0                      # authorised ceiling (estimate 4.77)
REQUEST_MAX_INPUTS = 128
REQUEST_MAX_TOKENS = 120_000
WORKERS = 6
MAX_ATTEMPTS = 8
UNITS = DATA_DIR / "s6" / "units.jsonl.gz"
OUT = DATA_DIR / "s7"
SHARDS = OUT / "shards"
REPO = Path(__file__).resolve().parents[2]
log = logging.getLogger("series.embed")


@dataclass(frozen=True)
class Unit:
    unit_id: str
    entity_type: str
    text: str
    text_sha256: str
    tokens: int


def read_units(path: Path = UNITS) -> list[Unit]:
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out.append(Unit(d["unit_id"], d["entity_type"], d["text"], d["text_sha256"], int(d["tokens"])))
    assert len({u.unit_id for u in out}) == len(out), "duplicate unit ids"
    return out


def make_shards(units: list[Unit]) -> list[list[Unit]]:
    shards, cur, tok = [], [], 0
    for u in units:
        if cur and (len(cur) >= REQUEST_MAX_INPUTS or tok + u.tokens > REQUEST_MAX_TOKENS):
            shards.append(cur); cur, tok = [], 0
        cur.append(u); tok += u.tokens
    if cur:
        shards.append(cur)
    return shards


def plan_hash(units: list[Unit]) -> str:
    h = hashlib.sha256(f"{MODEL}|{DIMENSIONS}".encode())
    for u in units:
        h.update(f"{u.unit_id}|{u.text_sha256}\n".encode())
    return h.hexdigest()


def usd(tokens: int) -> float:
    return tokens * PRICE_PER_M / 1e6


def shard_path(i: int, directory: Path = SHARDS) -> Path:
    return directory / f"shard_{i:05d}.npz"


def write_shard(path: Path, i: int, ids: list[str], vec: np.ndarray, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        np.savez(f, vectors=vec.astype(np.float32), unit_ids=np.array(ids),
                 meta=np.array(json.dumps({**meta, "index": i, "model": MODEL, "dimensions": DIMENSIONS})))
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def read_shard(path: Path) -> tuple[list[str], np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as z:
        return [str(x) for x in z["unit_ids"]], z["vectors"], json.loads(str(z["meta"]))


def valid_shard(i: int, shard: list[Unit], phash: str, directory: Path = SHARDS) -> dict | None:
    p = shard_path(i, directory)
    if not p.exists():
        return None
    try:
        ids, vec, meta = read_shard(p)
    except Exception:
        return None
    ok = (ids == [u.unit_id for u in shard] and vec.shape == (len(shard), DIMENSIONS) and meta.get("plan_hash") == phash
          and bool(np.isfinite(vec).all()))
    return meta if ok else None


def plan(units: list[Unit] | None = None, directory: Path = SHARDS) -> dict:
    units = units or read_units()
    shards = make_shards(units)
    ph = plan_hash(units)
    done = [i for i, s in enumerate(shards) if valid_shard(i, s, ph, directory)]
    tokens = sum(u.tokens for u in units)
    return {"units": len(units), "shards": len(shards), "shards_done": len(done), "tokens": tokens,
            "estimated_usd": round(usd(tokens), 4), "plan_hash": ph, "budget_usd": MAX_USD}


class _Pause:
    def __init__(self) -> None:
        self.until, self.lock = 0.0, threading.Lock()

    def wait(self) -> None:
        while (d := self.until - time.monotonic()) > 0:
            time.sleep(min(d, 5))

    def trip(self, s: float) -> None:
        with self.lock:
            self.until = max(self.until, time.monotonic() + s)


def _request(client, shard: list[Unit], pause: _Pause):
    import openai
    transient = (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        pause.wait()
        try:
            r = client.embeddings.create(model=MODEL, input=[u.text for u in shard], dimensions=DIMENSIONS,
                                         encoding_format="float")
            data = sorted(r.data, key=lambda d: d.index)
            vec = np.asarray([d.embedding for d in data], dtype=np.float32)
            if vec.shape != (len(shard), DIMENSIONS):
                raise RuntimeError(f"unexpected embedding shape {vec.shape}")
            return vec, int(r.usage.total_tokens), getattr(r, "_request_id", None)
        except transient as e:
            if attempt == MAX_ATTEMPTS:
                raise
            delay = min(120.0, 2.0 ** attempt) + random.uniform(0, 1.5)
            if isinstance(e, openai.RateLimitError):
                pause.trip(delay)
            else:
                time.sleep(delay)
    raise AssertionError("unreachable")


def run(client=None, *, units: list[Unit] | None = None, directory: Path = SHARDS, max_usd: float = MAX_USD,
        workers: int = WORKERS) -> dict:
    units = units or read_units()
    if usd(sum(u.tokens for u in units)) > max_usd:
        raise RuntimeError("estimated cost exceeds the budget")
    shards, ph = make_shards(units), plan_hash(units)
    todo, spent = [], 0
    for i, s in enumerate(shards):
        meta = valid_shard(i, s, ph, directory)
        if meta is None:
            todo.append(i)
        else:
            spent += int(meta["usage_tokens"])
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI
        load_dotenv(REPO / ".env")
        client = OpenAI(max_retries=0, timeout=120)
    pause, lock = _Pause(), threading.Lock()
    st = {"tokens": spent, "done": 0, "stop": False}
    t0 = time.monotonic()

    def work(i: int) -> None:
        sh = shards[i]
        with lock:
            if st["stop"]:
                return
            if usd(st["tokens"] + sum(u.tokens for u in sh)) > max_usd:
                st["stop"] = True
                raise RuntimeError(f"budget {max_usd} USD would be exceeded at shard {i}")
        vec, used, rid = _request(client, sh, pause)
        write_shard(shard_path(i, directory), i, [u.unit_id for u in sh], vec,
                    {"usage_tokens": used, "plan_hash": ph, "request_id": rid,
                     "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        with lock:
            st["tokens"] += used; st["done"] += 1
            if st["done"] % 20 == 0:
                log.info("%d/%d shards, %.4f USD, %.0fs", st["done"], len(todo), usd(st["tokens"]), time.monotonic() - t0)

    errors = []
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(work, i) for i in todo]):
            try:
                f.result()
            except Exception as e:
                st["stop"] = True
                errors.append(f"{type(e).__name__}: {str(e)[:200]}")
    res = {**plan(units, directory), "requested_now": st["done"], "reused": len(shards) - len(todo),
           "api_tokens": st["tokens"], "api_usd": round(usd(st["tokens"]), 4), "seconds": round(time.monotonic() - t0, 1),
           "errors": errors}
    if errors:
        raise RuntimeError(f"{len(errors)} shard(s) failed, rerun to resume: {errors[:3]}")
    return res


def load_all(units: list[Unit], directory: Path = SHARDS) -> np.ndarray:
    shards, ph = make_shards(units), plan_hash(units)
    parts = []
    for i, s in enumerate(shards):
        if valid_shard(i, s, ph, directory) is None:
            raise RuntimeError(f"shard {i} missing or invalid")
        parts.append(read_shard(shard_path(i, directory))[1])
    return np.vstack(parts)


def verify(units: list[Unit] | None = None, directory: Path = SHARDS) -> dict:
    units = units or read_units()
    vec = load_all(units, directory)
    norms = np.linalg.norm(vec, axis=1)
    tokens = sum(int(read_shard(p)[2]["usage_tokens"]) for p in sorted(directory.glob("shard_*.npz")))
    res = {"vectors": int(vec.shape[0]), "units": len(units), "dims": int(vec.shape[1]), "finite": bool(np.isfinite(vec).all()),
           "norm_min": float(norms.min()), "norm_max": float(norms.max()), "zero_vectors": int((norms == 0).sum()),
           "duplicate_vectors": int(len(vec) - len({hash(v.tobytes()) for v in vec})), "api_tokens": tokens,
           "api_usd": round(usd(tokens), 4)}
    res["ok"] = bool(res["vectors"] == res["units"] and res["dims"] == DIMENSIONS and res["finite"]
                     and res["zero_vectors"] == 0 and 0.99 < res["norm_min"] and res["norm_max"] < 1.01)
    return res


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cmd = argv[0] if argv else "plan"
    if cmd == "run" and os.environ.get("SERIES_EMBED_AUTHORIZED") != "yes":
        print("refusing: paid run, set SERIES_EMBED_AUTHORIZED=yes for this command only"); return 2
    fn = {"plan": plan, "run": run, "verify": verify}.get(cmd)
    if not fn:
        print(__doc__); return 2
    res = fn()
    print(json.dumps(res, indent=1))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
