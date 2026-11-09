"""One streaming pass over the local Italian Wikipedia dump (no network, nothing written next to the dump).

The film catalogue was built from pages that have a film infobox AND a usable plot section; the extraction
only kept the reason of the rejections (`processed/rejected.jsonl`: page id, title, reason). To explain why a
well known film is missing, and to attach a year and an original title to the rejected pages, the dump is read
again with plain byte searches (no XML tree, no wikitext parser): fast enough for a single pass.

Output (JSONL, one record per page of interest, written to the audit folder):
- `kind: "film_page"`  every article that carries `{{Film` : id, title, year, original title, director, plot heading,
  approximate plot length, redirect flag always False;
- `kind: "target_hit"` every page (article or redirect) whose normalised title (qualifier removed) is in the targets.
"""
from __future__ import annotations

import bz2
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterator

from .util import DUMP, norm_title, strip_qualifier

PLOT_HEADINGS = ("trama", "plot", "sinossi", "soggetto", "riassunto", "storia", "argomento", "la trama", "trama del film")
_PAGE_END = b"</page>"
_TITLE = re.compile(rb"<title>(.*?)</title>", re.S)
_NS = re.compile(rb"<ns>(-?\d+)</ns>")
_ID = re.compile(rb"<id>(\d+)</id>")
_REDIRECT = re.compile(rb'<redirect title="([^"]*)"')
_TEXT = re.compile(rb"<text[^>]*>(.*?)</text>", re.S)
_FILM = re.compile(rb"\{\{\s*[Ff]ilm\s*[\n|}]")
_FILM_CAT = re.compile(rb"\[\[\s*[Cc]ategoria:\s*Film\s", re.I)
_DISAMBIG = re.compile(rb"\{\{\s*[Dd]isambigua", re.I)
_HEADING = re.compile(rb"^==+\s*([^=\n]+?)\s*==+\s*$", re.M)
_PARAM = re.compile(r"\|\s*(titolo originale|anno uscita|regista)\s*=\s*([^\n|]*)")


def _unescape(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def _wikilink_text(value: str) -> str:
    return re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", value).strip()


def iter_page_blobs(stream, chunk_size: int = 1 << 24) -> Iterator[bytes]:
    """Yields the raw bytes of every `<page>...</page>` of a decompressed XML stream."""
    buffer = b""
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        buffer += chunk
        start = 0
        while True:
            begin = buffer.find(b"<page>", start)
            if begin < 0:
                break
            end = buffer.find(_PAGE_END, begin)
            if end < 0:
                break
            yield buffer[begin : end + len(_PAGE_END)]
            start = end + len(_PAGE_END)
        buffer = buffer[start:]


def scan_page(blob: bytes, targets: frozenset[str]) -> list[dict]:
    """Records of one page (0, 1 or 2): a film page and/or a target hit. Pure."""
    ns = _NS.search(blob)
    if not ns or ns.group(1) != b"0":
        return []
    title_m = _TITLE.search(blob)
    id_m = _ID.search(blob)
    if not title_m or not id_m:
        return []
    title = _unescape(title_m.group(1))
    redirect_m = _REDIRECT.search(blob)
    key = norm_title(strip_qualifier(title))
    out: list[dict] = []
    text_m = _TEXT.search(blob)
    text = text_m.group(1) if text_m else b""
    film = (not redirect_m) and bool(_FILM.search(text))
    base = {"page_id": int(id_m.group(1)), "title": title}
    if film:
        decoded = _unescape(text)
        pos = decoded.lower().find("{{film")
        params = {m.group(1): _wikilink_text(m.group(2)) for m in _PARAM.finditer(decoded[pos : pos + 4000])}
        year_m = re.search(r"\b(1[89]\d\d|20\d\d)\b", params.get("anno uscita", ""))
        headings = [_unescape(h).strip().lower() for h in _HEADING.findall(text)]
        plot_heading = next((h for h in headings if h in PLOT_HEADINGS), None)
        out.append({
            **base, "kind": "film_page", "year": int(year_m.group(1)) if year_m else None,
            "original_title": params.get("titolo originale") or None,
            "director": params.get("regista") or None, "plot_heading": plot_heading,
            "headings": len(headings), "chars": len(text),
        })
    if key and key in targets:
        out.append({
            **base, "kind": "target_hit", "key": key, "redirect_to": _unescape(redirect_m.group(1)) if redirect_m else None,
            "film_infobox": film, "film_category": bool(_FILM_CAT.search(text)), "disambiguation": bool(_DISAMBIG.search(text)),
            "chars": len(text),
        })
    return out


def run_scan(targets: frozenset[str], out_path: Path, *, dump: Path = DUMP, limit_pages: int | None = None,
             log=sys.stderr) -> dict:
    """Single pass; returns counters. Writes `out_path` atomically at the end (a partial run leaves no file)."""
    started = time.time()
    pages = films = hits = 0
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with bz2.BZ2File(dump, "rb") as stream, tmp.open("w", encoding="utf-8") as handle:
        try:
            for blob in iter_page_blobs(stream):
                pages += 1
                for rec in scan_page(blob, targets):
                    handle.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
                    films += rec["kind"] == "film_page"
                    hits += rec["kind"] == "target_hit"
                if pages % 250000 == 0:
                    print(f"[dump_scan] pages={pages} film_pages={films} hits={hits} {time.time() - started:.0f}s", file=log, flush=True)
                if limit_pages and pages >= limit_pages:
                    break
        except EOFError:  # truncated sample: expected for the 80 MB sample, an error for the full dump
            if dump.name.endswith(".sample"):
                pass
            else:
                raise
    tmp.replace(out_path)
    return {"pages": pages, "film_pages": films, "target_hits": hits, "seconds": round(time.time() - started, 1)}
