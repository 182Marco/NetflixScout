"""Embedding units: one per film (the whole synopsis), except the plots over the model's input limit, which are split
in several chunks that all keep the same film_id. No other film is chunked and nothing is truncated or summarised."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterator

import tiktoken

from .settings import EXCEPTION_CHUNK_TOKENS, FILMS, MAX_INPUT_TOKENS, REQUEST_MAX_INPUTS, REQUEST_MAX_TOKENS

ENC = tiktoken.get_encoding("cl100k_base")


def ntok(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


@dataclass(frozen=True)
class Unit:
    unit_id: str          # "<film_id>#<chunk_index>"
    film_id: str
    chunk_index: int
    chunk_count: int
    text: str
    tokens: int
    text_sha256: str


def sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        parts = re.split(r"(?<=[.!?…»”\"])\s+(?=[A-ZÀ-Ý«“\"'(\d])", para.strip())
        out += [p for p in parts if p.strip()]
    return out


def split_text(text: str, target: int) -> list[str]:
    """Sentence-aware greedy packing up to ~`target` tokens, one sentence of overlap, no tiny tail. Every sentence is kept."""
    sents: list[str] = []
    for s in sentences(text):
        if ntok(s) <= 1.5 * target:
            sents.append(s)
            continue
        piece: list[str] = []  # oversized "sentence": split on words
        for w in s.split():
            piece.append(w)
            if ntok(" ".join(piece)) >= target:
                sents.append(" ".join(piece)); piece = []
        if piece:
            sents.append(" ".join(piece))
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_t = 0
    for s in sents:
        t = ntok(s)
        if cur and cur_t + t > target:
            chunks.append(cur)
            keep = cur[-1:] if ntok(cur[-1]) < target / 4 else []
            cur, cur_t = list(keep), sum(ntok(x) for x in keep)
        cur.append(s)
        cur_t += t
    if cur:
        chunks.append(cur)
    if len(chunks) > 1 and sum(ntok(x) for x in chunks[-1]) < 0.3 * target:
        tail = chunks.pop()
        chunks[-1] += [x for x in tail if x not in chunks[-1][-1:]]
    return [" ".join(c) for c in chunks]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_films() -> Iterator[dict]:
    with FILMS.open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def units_for(film: dict) -> list[Unit]:
    text = film["synopsis"]
    n = ntok(text)
    if n <= MAX_INPUT_TOKENS:
        pieces = [text]
    else:
        pieces = split_text(text, EXCEPTION_CHUNK_TOKENS)
        covered = " ".join(pieces)
        assert all(s in covered for s in sentences(text)), f"chunking lost text for {film['film_id']}"
    units = []
    for i, p in enumerate(pieces):
        t = ntok(p)
        assert t <= MAX_INPUT_TOKENS, f"chunk of {film['film_id']} still over the limit ({t})"
        units.append(Unit(f"{film['film_id']}#{i}", film["film_id"], i, len(pieces), p, t, _sha(p)))
    return units


def build_units() -> list[Unit]:
    """All units, ordered by wikipedia_page_id then chunk index (the order of films.jsonl)."""
    out: list[Unit] = []
    for film in read_films():
        out += units_for(film)
    ids = [u.unit_id for u in out]
    assert len(ids) == len(set(ids)), "duplicate unit ids"
    return out


def plan_hash(units: list[Unit]) -> str:
    h = hashlib.sha256()
    for u in units:
        h.update(f"{u.unit_id}\x00{u.text_sha256}\n".encode())
    return h.hexdigest()


def make_shards(units: list[Unit]) -> list[list[Unit]]:
    """Deterministic packing: one shard = one API request (<= REQUEST_MAX_INPUTS inputs and <= REQUEST_MAX_TOKENS tokens)."""
    shards: list[list[Unit]] = []
    cur: list[Unit] = []
    cur_t = 0
    for u in units:
        if cur and (len(cur) >= REQUEST_MAX_INPUTS or cur_t + u.tokens > REQUEST_MAX_TOKENS):
            shards.append(cur); cur, cur_t = [], 0
        cur.append(u)
        cur_t += u.tokens
    if cur:
        shards.append(cur)
    return shards
