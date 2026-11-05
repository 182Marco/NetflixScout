"""OpenAI helpers with a disk cache (same input → same stored output), so a run is reproducible and a re-run is free."""
from __future__ import annotations

import hashlib
import json
import os
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "eval" / "cache"
load_dotenv(ROOT.parents[1] / ".env")
LLM_MODEL = "gpt-5.6-luna"          # the model of the whole application (CONFIG["orchestrator"]["llm_model"])
USAGE = {"llm_calls": 0, "llm_tokens": 0, "embed_calls": 0, "embed_tokens": 0}


@lru_cache(maxsize=1)
def client() -> OpenAI:
    return OpenAI(max_retries=4, timeout=180)


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _retry(fn, attempts: int = 6):
    for n in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if n == attempts - 1:
                raise
            time.sleep(min(60, 3 * 2 ** n))


def structured(model_cls: type[BaseModel], instructions: str, text: str, *, model: str = LLM_MODEL, cache: bool = True, effort: str | None = None):
    """One structured call (Responses API, parsed into `model_cls`); cached on (model, schema, instructions, input)."""
    path = CACHE / "llm" / f"{_key(model, model_cls.__name__, json.dumps(model_cls.model_json_schema(), sort_keys=True), instructions, text, effort or '')}.json"
    if cache and path.exists():
        return model_cls.model_validate_json(path.read_text())
    extra = {'reasoning': {'effort': effort}} if effort else {}
    resp = _retry(lambda: client().responses.parse(model=model, instructions=instructions, input=text, text_format=model_cls, **extra))
    out = resp.output_parsed
    if out is None:
        raise RuntimeError("the model returned no parsed output")
    USAGE["llm_calls"] += 1
    USAGE["llm_tokens"] += getattr(resp.usage, "total_tokens", 0) or 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json())
    return out


def plain(instructions: str, text: str, *, model: str = LLM_MODEL, cache: bool = True) -> str:
    path = CACHE / "llm" / f"{_key(model, 'plain', instructions, text)}.txt"
    if cache and path.exists():
        return path.read_text()
    resp = _retry(lambda: client().responses.create(model=model, instructions=instructions, input=text))
    USAGE["llm_calls"] += 1
    USAGE["llm_tokens"] += getattr(resp.usage, "total_tokens", 0) or 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.output_text)
    return resp.output_text


def embed(texts: list[str], model: str, dimensions: int | None) -> np.ndarray:
    """Unit-length float32 vectors, cached per text."""
    out: list[np.ndarray | None] = []
    todo: list[tuple[int, str, Path]] = []
    for i, t in enumerate(texts):
        p = CACHE / "emb" / f"{model}-{dimensions or 0}-{_key(t)}.npy"
        cached = None
        if p.exists():
            try:
                cached = np.load(p)
                if cached.ndim != 1 or cached.size == 0:
                    cached = None
            except Exception:  # noqa: BLE001  (a file half-written by a parallel worker)
                cached = None
        if cached is not None:
            out.append(cached)
        else:
            out.append(None)
            todo.append((i, t, p))
    if todo:
        kw = {"dimensions": dimensions} if dimensions else {}
        resp = _retry(lambda: client().embeddings.create(model=model, input=[t for _, t, _ in todo], **kw))
        USAGE["embed_calls"] += 1
        USAGE["embed_tokens"] += resp.usage.total_tokens
        for (i, _, p), d in zip(todo, resp.data):
            v = np.asarray(d.embedding, dtype=np.float32)
            v = v / np.linalg.norm(v)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + f".{os.getpid()}.{id(v)}.tmp")
            with tmp.open("wb") as fh:
                np.save(fh, v)
            tmp.replace(p)
            out[i] = v
    return np.vstack(out)
