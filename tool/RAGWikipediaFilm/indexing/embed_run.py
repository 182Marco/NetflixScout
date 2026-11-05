"""Embeds every unit with text-embedding-3-large at 1536 dimensions (API `dimensions`), shard by shard.

Resumable: a shard whose file exists, parses and matches the plan is never requested again. Retries with exponential
backoff and a pause shared by all workers on rate limits. Nothing about the API key is logged."""
from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from . import settings as S
from .shardio import read_shard, shard_path, write_shard
from .units import Unit, build_units, make_shards, plan_hash

log = logging.getLogger("ragwiki.embed")


class BudgetExceeded(RuntimeError):
    pass


def usd(tokens: int) -> float:
    return tokens * S.PRICE_PER_M_TOKENS / 1e6


def make_client():
    from dotenv import load_dotenv  # the key stays inside the library; it is never read into a log
    from openai import OpenAI

    load_dotenv(S.REPO / ".env")
    return OpenAI(max_retries=0, timeout=120)  # retries are handled here, with the shared pause


def preflight(units: list[Unit]) -> dict:
    tokens = sum(u.tokens for u in units)
    shards = make_shards(units)
    films = len({u.film_id for u in units})
    return {"units": len(units), "films": films, "chunked_films": len({u.film_id for u in units if u.chunk_count > 1}),
            "tokens": tokens, "estimated_usd": round(usd(tokens), 4), "requests": len(shards), "plan_hash": plan_hash(units),
            "budget_usd": S.MAX_USD, "within_budget": usd(tokens) <= S.MAX_USD}


def _valid_existing(index: int, shard: list[Unit], phash: str, directory) -> dict | None:
    path = shard_path(index, directory)
    if not path.exists():
        return None
    try:
        s = read_shard(path)
    except Exception:  # unreadable / truncated: it will be requested again
        log.warning("shard %d unreadable, will be regenerated", index)
        return None
    ok = (s.unit_ids == [u.unit_id for u in shard] and s.vectors.shape == (len(shard), S.DIMENSIONS)
          and s.meta.get("plan_hash") == phash and np.isfinite(s.vectors).all())
    return s.meta if ok else None


class _Pause:
    """Shared rate-limit pause: when one worker is limited, every worker waits."""

    def __init__(self) -> None:
        self.until = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        while (d := self.until - time.monotonic()) > 0:
            time.sleep(min(d, 5))

    def trip(self, seconds: float) -> None:
        with self.lock:
            self.until = max(self.until, time.monotonic() + seconds)


def _request(client, shard: list[Unit], pause: _Pause, sleep=None) -> tuple[np.ndarray, int, str | None]:
    import openai

    transient = (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError)
    for attempt in range(1, S.MAX_ATTEMPTS + 1):
        pause.wait()
        try:
            r = client.embeddings.create(model=S.MODEL, input=[u.text for u in shard], dimensions=S.DIMENSIONS,
                                         encoding_format="float")
            data = sorted(r.data, key=lambda d: d.index)
            vec = np.asarray([d.embedding for d in data], dtype=np.float32)
            if vec.shape != (len(shard), S.DIMENSIONS):
                raise RuntimeError(f"unexpected embedding shape {vec.shape}")
            return vec, int(r.usage.total_tokens), getattr(r, "_request_id", None)
        except transient as e:
            if attempt == S.MAX_ATTEMPTS:
                raise
            delay = min(120.0, 2.0 ** attempt) + random.uniform(0, 1.5)
            if isinstance(e, openai.RateLimitError):
                pause.trip(delay)
            log.warning("transient %s (attempt %d/%d), waiting %.1fs", type(e).__name__, attempt, S.MAX_ATTEMPTS, delay)
            if not isinstance(e, openai.RateLimitError):
                (sleep or time.sleep)(delay)
    raise AssertionError("unreachable")


def run(client=None, *, units: list[Unit] | None = None, directory=None, max_usd: float = S.MAX_USD, workers: int = S.WORKERS) -> dict:
    units = units if units is not None else build_units()
    info = preflight(units)
    if usd(sum(u.tokens for u in units)) > max_usd:
        raise BudgetExceeded(f"estimated cost {info['estimated_usd']} USD exceeds the budget of {max_usd} USD")
    shards = make_shards(units)
    phash = info["plan_hash"]
    directory = directory or S.SHARDS
    done_tokens = 0
    todo = []
    for i, sh in enumerate(shards):
        meta = _valid_existing(i, sh, phash, directory)
        if meta is None:
            todo.append(i)
        else:
            done_tokens += int(meta["usage_tokens"])
    log.info("plan: %d units, %d shards, %d already complete, %d to request; spent so far %.4f USD",
             len(units), len(shards), len(shards) - len(todo), len(todo), usd(done_tokens))
    client = client or make_client()
    pause, lock = _Pause(), threading.Lock()
    state = {"tokens": done_tokens, "done": 0, "requests": 0, "stop": False}
    started = time.monotonic()

    def work(i: int) -> int:
        sh = shards[i]
        with lock:
            if state["stop"]:
                return 0
            if usd(state["tokens"] + sum(u.tokens for u in sh)) > max_usd:
                state["stop"] = True
                raise BudgetExceeded(f"budget {max_usd} USD would be exceeded at shard {i}")
        vec, used, rid = _request(client, sh, pause)
        write_shard(shard_path(i, directory), i, [u.unit_id for u in sh], vec, [u.tokens for u in sh],
                    {"usage_tokens": used, "plan_hash": phash, "request_id": rid,
                     "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        with lock:
            state["tokens"] += used; state["done"] += 1; state["requests"] += 1
            if state["done"] % 10 == 0 or state["done"] == len(todo):
                log.info("%d/%d shards, %.4f USD, %.0fs", state["done"], len(todo), usd(state["tokens"]),
                         time.monotonic() - started)
        return used

    errors = []
    with ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(work, i) for i in todo]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:  # keep the other shards going; report at the end
                state["stop"] = isinstance(e, BudgetExceeded) or state["stop"]
                errors.append(f"{type(e).__name__}: {str(e)[:200]}")
    result = {**info, "shards": len(shards), "requested_now": state["requests"], "reused": len(shards) - len(todo),
              "api_tokens": state["tokens"], "api_usd": round(usd(state["tokens"]), 4),
              "seconds": round(time.monotonic() - started, 1), "errors": errors}
    log.info("finished: %s", {k: v for k, v in result.items() if k != "errors"})
    if errors:
        raise RuntimeError(f"{len(errors)} shard(s) failed, rerun to resume: {errors[:3]}")
    return result
