"""Texts to embed for every strategy. A: whole synopsis. B1/B2: LLM summaries. C500/C250: paragraph/sentence-aware chunks
of the plots longer than twice the chunk size (shorter plots stay a single vector). Every text keeps its film_id."""
from __future__ import annotations

import json
import re

from common import ENC, RESULTS, load_films, ntok

MAX_EMBED_TOKENS = 8000  # hard input limit of text-embedding-3-* is 8191
VARIANTS = ["A", "B1", "B2", "C500", "C250"]


def clip(text: str, limit: int = MAX_EMBED_TOKENS) -> str:
    ids = ENC.encode(text, disallowed_special=())
    return text if len(ids) <= limit else ENC.decode(ids[:limit])


def sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        parts = re.split(r"(?<=[.!?…»”\"])\s+(?=[A-ZÀ-Ý«“\"'(\d])", para.strip())
        out += [p for p in parts if p.strip()]
    return out


def chunk(text: str, target: int) -> list[str]:
    """Greedy packing of whole sentences up to `target` tokens, one sentence of overlap, no tiny tail."""
    sents = []
    for s in sentences(text):
        if ntok(s) <= 1.5 * target:
            sents.append(s)
            continue
        words, piece = s.split(), []  # oversized "sentence" (list, table-like text): split on words
        for w in words:
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


def build(pool: list[str]) -> dict[str, list[tuple[str, str]]]:
    """variant -> list of (film_id, text)."""
    films = load_films()
    summaries = json.loads((RESULTS / "summaries.json").read_text())
    out: dict[str, list[tuple[str, str]]] = {v: [] for v in VARIANTS}
    for fid in pool:
        syn = films[fid]["synopsis"]
        n = ntok(syn)
        out["A"].append((fid, clip(syn)))
        for lv in ("B1", "B2"):
            out[lv].append((fid, summaries[f"{lv}:{fid}"]["text"]))
        for name, size in (("C500", 500), ("C250", 250)):
            if n > 2 * size:
                out[name] += [(fid, c) for c in chunk(syn, size)]
            else:
                out[name].append((fid, clip(syn)))
    return out


if __name__ == "__main__":
    pool = json.loads((RESULTS / "sample.json").read_text())["pool"]
    v = build(pool)
    for name, items in v.items():
        toks = [ntok(t) for _, t in items]
        print(name, "vectors", len(items), "films", len({f for f, _ in items}), "tokens", sum(toks),
              "max", max(toks), "mean", round(sum(toks) / len(toks)))
