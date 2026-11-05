"""Shared helpers of the Phase 2 benchmark: paths, token counting, cost ledger with a hard cap,
cached embeddings, LLM calls. Nothing here touches the Phase 1 pipeline or the application."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import tiktoken

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
FILMS = ROOT / "data" / "processed" / "films.jsonl"
RESULTS = HERE / "results"
CACHE = RESULTS / "cache"
LEDGER = RESULTS / "cost_ledger.jsonl"
RESULTS.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

BUDGET_CAP_USD = 4.0  # hard stop; the authorised experimental budget is 5 USD
SEED = 20261104

# USD per 1M tokens (standard prices read on developers.openai.com/api/docs/pricing, 2026-11-04)
PRICES = {
    "gpt-5.6-luna": {"in": 0.20, "cached": 0.02, "out": 1.20},
    "text-embedding-3-small": {"in": 0.02, "out": 0.0},
    "text-embedding-3-large": {"in": 0.13, "out": 0.0},
}
LLM_MODEL = "gpt-5.6-luna"
ENC = tiktoken.get_encoding("cl100k_base")


def ntok(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


def load_films() -> dict[str, dict]:
    films = {}
    for line in FILMS.open(encoding="utf-8"):
        r = json.loads(line)
        films[r["film_id"]] = r
    return films


# ---------------------------------------------------------------- cost ledger
def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in LEDGER.open())


def record_cost(label: str, model: str, tokens_in: int, tokens_out: int, cached: int = 0) -> float:
    p = PRICES[model]
    usd = ((tokens_in - cached) * p["in"] + cached * p.get("cached", p["in"]) + tokens_out * p["out"]) / 1e6
    with LEDGER.open("a") as f:
        f.write(json.dumps({"label": label, "model": model, "in": tokens_in, "out": tokens_out,
                            "cached": cached, "usd": usd, "t": int(time.time())}) + "\n")
    return usd


def guard(extra: float = 0.0) -> None:
    total = spent() + extra
    if total > BUDGET_CAP_USD:
        raise SystemExit(f"BUDGET CAP: {total:.3f} USD > {BUDGET_CAP_USD} USD, stopping")


def ledger_summary() -> dict:
    out: dict[str, dict] = {}
    if LEDGER.exists():
        for l in LEDGER.open():
            e = json.loads(l)
            k = e["label"].split(":")[0]
            d = out.setdefault(k, {"usd": 0.0, "in": 0, "out": 0, "calls": 0})
            d["usd"] += e["usd"]; d["in"] += e["in"]; d["out"] += e["out"]; d["calls"] += 1
    out["TOTAL"] = {"usd": sum(v["usd"] for v in out.values())}
    return out


# ---------------------------------------------------------------- OpenAI client
_client = None


def client():
    global _client
    if _client is None:
        from dotenv import load_dotenv  # the key is read by the library, never printed
        from openai import OpenAI

        load_dotenv(REPO / ".env")
        _client = OpenAI(max_retries=3, timeout=180)
    return _client


def llm(label: str, instructions: str, user: str) -> str:
    """One Responses API call with the project's model; cost is written to the ledger."""
    guard()
    r = client().responses.create(model=LLM_MODEL, instructions=instructions, input=user)
    u = r.usage
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    record_cost(label, LLM_MODEL, u.input_tokens, u.output_tokens, cached)
    return r.output_text


def llm_json(label: str, instructions: str, user: str, tries: int = 3):
    last = ""
    for _ in range(tries):
        text = llm(label, instructions, user).strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except ValueError:
            last = text
    raise RuntimeError(f"{label}: invalid JSON after {tries} tries: {last[:200]}")


# ---------------------------------------------------------------- embeddings (cached on disk)
def _key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode()).hexdigest()


def embed(label: str, model: str, texts: list[str], batch: int = 64, dimensions: int | None = None) -> np.ndarray:
    """Embeddings of `texts`, one vector per text, cached by (model, dimensions, text)."""
    tag = model if dimensions is None else f"{model}@{dimensions}"
    cache_file = CACHE / f"emb_{tag.replace('/', '_')}.npz"
    store: dict[str, np.ndarray] = {}
    if cache_file.exists():
        z = np.load(cache_file)
        store = {k: z[k] for k in z.files}
    todo = sorted({_key(tag, t): t for t in texts}.items())
    todo = [(k, t) for k, t in todo if k not in store]
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        guard(extra=sum(ntok(t) for _, t in part) * PRICES[model]["in"] / 1e6)
        kwargs = {"model": model, "input": [t for _, t in part]}
        if dimensions:
            kwargs["dimensions"] = dimensions
        r = client().embeddings.create(**kwargs)
        record_cost(f"embed:{label}", model, r.usage.total_tokens, 0)
        for (k, _), d in zip(part, r.data):
            store[k] = np.asarray(d.embedding, dtype=np.float32)
        if (i // batch) % 10 == 0 or i + batch >= len(todo):
            np.savez(cache_file, **store)
    if todo:
        np.savez(cache_file, **store)
    return np.stack([store[_key(tag, t)] for t in texts])
