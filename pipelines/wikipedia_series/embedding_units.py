"""Phase S6 (no API): the exact texts to embed, token counts and the cost estimate. NO embedding is made.

Reads the verified catalogue `data/s5/` and writes `data/s6/units.jsonl.gz` (one unit per vectorisable
record: id, entity_type, text, sha256 of the text, tokens) and `embedding_manifest.json` with status
`pending`: counts, token totals measured with the local tokenizer (tiktoken, cl100k_base; the OpenAI
embedding model counts the same way) and the price at 0.13 USD per million tokens. An embedding run later
only has to read this file. Which records get a vector (decisions 2, 4, 5):
  series   plot (>=400 chars, 60 words) or, as a different `text_kind`, the introduction (>=400 chars)
  season   its own page's introduction (>=150 chars); logical seasons never (no text of their own)
  episode  prose >=150 chars, with the context prefix "Serie – stagione N – titolo"
  tv_movie plot or introduction; own `entity_type`, never mixed into series searches by default

    python -m pipelines.wikipedia_series.embedding_units
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from .build_relations import read
from .common import DATA_DIR

S5, OUT = DATA_DIR / "s5", DATA_DIR / "s6"
PRICE_PER_M = 0.13
MAX_TOKENS = 8191          # input limit of the embedding model
TARGET_TOKENS = 7800       # longer texts are cut at this size (flag `truncated`), never silently
LABELS = {"tv_series": "serie TV", "miniseries": "miniserie TV", "serial": "serial TV", "web_series": "webserie", "anime": "serie anime",
          "animated_series": "serie animata", "programme": "programma TV", "tv_movie": "film TV"}


def compose(rec: dict) -> tuple[str, str] | None:
    """(text, text_kind) to embed for a record, or None when it has no usable text."""
    kind = rec["text_kind"]
    et = rec["entity_type"]
    if et in ("series", "tv_movie"):
        body = rec["plot_text"] if kind == "plot" else rec["lead_text"] if kind == "lead" else ""
        if not body:
            return None
        year = f" ({rec['year']})" if rec.get("year") else ""
        return f"{rec['title']}{year} — {LABELS.get(rec['subtype'], rec['subtype'])}.\n{body}", kind
    if et == "season":
        if kind != "season_intro" or rec.get("logical"):
            return None
        return f"{rec.get('series_title') or ''} – {rec['title']}.\n{rec['lead_text']}".strip(), kind
    if et == "episode":
        parts = [rec.get("series_title") or "", f"stagione {rec['season_number']}" if rec.get("season_number") else "",
                 f"episodio {rec['episode_number']}" if rec.get("episode_number") else "", rec["title"]]
        prefix = " – ".join(p for p in parts if p)
        return f"{prefix}.\n{rec['plot_text']}", "plot"
    return None


def units(s5: Path = S5):
    for name in ("series", "seasons", "episodes", "tv_movies"):
        for rec in read(s5 / f"{name}.jsonl"):
            composed = compose(rec)
            if composed:
                yield rec, composed[0], composed[1]


def build(s5: Path, out: Path, *, encoder=None) -> dict:
    if encoder is None:
        import tiktoken
        encoder = tiktoken.get_encoding("cl100k_base")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "units.jsonl.gz"
    tmp = path.with_name(path.name + ".part")
    totals: Counter = Counter()
    by_type: dict[str, Counter] = {}
    longest = Counter()
    with gzip.GzipFile(tmp, "wb", compresslevel=6, mtime=0) as raw:
        for rec, text, kind in units(s5):
            tokens = encoder.encode(text)
            truncated = len(tokens) > TARGET_TOKENS
            if truncated:
                text = encoder.decode(tokens[:TARGET_TOKENS])
                tokens = tokens[:TARGET_TOKENS]
            et = rec["entity_type"]
            c = by_type.setdefault(et, Counter())
            c["units"] += 1
            c["tokens"] += len(tokens)
            c[f"text_kind:{kind}"] += 1
            c["truncated"] += int(truncated)
            longest[et] = max(longest[et], len(tokens))
            row = {"unit_id": rec["record_id"], "entity_type": et, "subtype": rec["subtype"], "text_kind": kind, "text": text,
                   "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "tokens": len(tokens), "truncated": truncated}
            raw.write((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
            totals["units"] += 1
            totals["tokens"] += len(tokens)
    os.replace(tmp, path)
    manifest = {"status": "pending", "embedding_model": "text-embedding-3-large", "dimensions": 1536, "price_per_million_tokens_usd": PRICE_PER_M,
                "tokenizer": "tiktoken cl100k_base", "units": totals["units"], "tokens": totals["tokens"],
                "estimated_usd": round(totals["tokens"] / 1e6 * PRICE_PER_M, 2),
                "by_type": {k: {**dict(v), "longest_tokens": longest[k], "estimated_usd": round(v["tokens"] / 1e6 * PRICE_PER_M, 3)} for k, v in sorted(by_type.items())},
                "units_file": {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "note": "No embedding was requested. Run an embedding job only with credits and after `build_clean verify`."}
    (out / "embedding_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main() -> None:
    print(json.dumps(build(S5, OUT), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
