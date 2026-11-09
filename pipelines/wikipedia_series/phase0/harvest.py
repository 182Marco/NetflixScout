"""Phase 0, second pass: save the RAW wikitext of the pages selected from the first scan.

Selection rules (from the numbers of the scan, see PROGRESS.md): pages with a series / programme /
season-navigation / episode template, pages in series-related categories, "Episodi di ..." titles,
the key templates (namespace 10) and, as test cases, the pages the film project excluded (read-only
use of its audit JSON). Output: `data/phase0/full/harvest.jsonl.gz` (atomic) + a selection manifest.
After this pass every further Phase 0 analysis is offline and fast.

    python -m pipelines.wikipedia_series.phase0.harvest [--select-only]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from ..common import DATA_DIR, DUMP_PATH, FILM_DIR, iter_pages, open_dump

log = logging.getLogger("series.phase0.harvest")
SCAN_DIR = DATA_DIR / "phase0" / "full"
CAT = re.compile(
    r"^(liste? di episodi|episodi di|serie televisive|miniserie|anime|serie animate|programmi televisivi|"
    r"telenovela|telenovelas|sitcom|soap opera|fiction|stagioni di serie|dorama|serie web|web serie)", re.I)
TPL = re.compile(r"^(fictiontv|programma|stagionitv|episodio |stagione anime|cita episodio$|episodi imdb)")
SPORT = re.compile(r"calcio|football|basket|nba|nfl|hockey|rugby|tennis|pallavolo|squadra|campionato|snooker|motoristica|world series", re.I)
KEY_TEMPLATES = re.compile(r"^template:(fictiontv|programma|stagionitv|episodio |stagione anime|cita episodio|cita tv|episodi imdb|"
                           r"avviso episodi tv|serie televisive )", re.I)


def reasons(row: dict) -> list[str]:
    why = []
    if any(TPL.match(t) and not SPORT.search(t) for t in row["tpl_kw"]):
        why.append("tpl")
    if any(CAT.match(c) for c in row["cats_kw"]):
        why.append("cat")
    if "episodes_of" in row["title_sig"]:
        why.append("title_ep")
    return why


def film_excluded_ids() -> set[int]:
    """Wikipedia page ids of the film project's exclusions (259 + hybrids): test cases, read-only."""
    ids: set[int] = set()
    for name in ("exclusions.json",):
        path = FILM_DIR / "audit" / name
        if path.exists():
            ids |= {r["wikipedia_page_id"] for r in json.loads(path.read_text())["records"] if r.get("wikipedia_page_id")}
    return ids


def build_selection() -> dict:
    selected: dict[int, list[str]] = {}
    for line in open(SCAN_DIR / "scan_pages.jsonl", encoding="utf-8"):
        row = json.loads(line)
        why = reasons(row)
        if why:
            selected[row["id"]] = why
    for pid in film_excluded_ids():
        selected.setdefault(pid, []).append("film_excl")
    return {"pages": {str(k): v for k, v in sorted(selected.items())}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    selection = build_selection()
    sel_path = DATA_DIR / "phase0" / "harvest_selection.json"
    sel_path.write_text(json.dumps(selection, separators=(",", ":")), encoding="utf-8")
    ids = {int(k) for k in selection["pages"]}
    log.info("selected %d article pages (%s)", len(ids), sel_path)
    if args.select_only:
        return
    out = SCAN_DIR / "harvest.jsonl.gz"
    tmp = out.with_name(out.name + ".part")
    kept = {"articles": 0, "templates": 0, "missing_ids": 0}
    seen_ids: set[int] = set()
    started = time.monotonic()
    with open_dump(DUMP_PATH) as stream, gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
        for n, page in enumerate(iter_pages(stream), 1):
            take = None
            if page.namespace == 0 and page.page_id in ids and not page.redirect:
                take, key = "article", "articles"
                seen_ids.add(page.page_id)
            elif page.namespace == 10 and KEY_TEMPLATES.match(page.title):
                take, key = "template", "templates"
            if take:
                kept[key] += 1
                handle.write(json.dumps({"id": page.page_id, "ns": page.namespace, "title": page.title,
                                         "rev": page.revision_id, "kind": take, "text": page.text},
                                        ensure_ascii=False, separators=(",", ":")) + "\n")
            if n % 500000 == 0:
                log.info("%d pages, %s, %.0f s", n, kept, time.monotonic() - started)
    os.replace(tmp, out)
    kept["missing_ids"] = len(ids - seen_ids)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (SCAN_DIR / "harvest_summary.json").write_text(json.dumps(
        {"kept": kept, "bytes": out.stat().st_size, "sha256": digest, "seconds": round(time.monotonic() - started, 1)},
        indent=1), encoding="utf-8")
    log.info("done %s sha256=%s", kept, digest[:16])


if __name__ == "__main__":
    main()
