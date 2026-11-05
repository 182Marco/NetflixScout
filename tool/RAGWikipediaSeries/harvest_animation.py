"""Phase S1b: second harvest pass for the pages the first one did not select.

The first harvest (`phase0/harvest.py`) selected pages by series templates / categories. Measured gap
(scan, 2026-11-05): 5,233 pages carry `{{Fumetto e animazione}}` but were not harvested; 1,360 of them have
the first infobox of type anime / cartone with subtype serie TV / OVA / ONA / webserie, and pages with a
manga infobox FIRST and an anime infobox later (the scan kept only the first infobox) are invisible in the
scan. All of them are read here (raw wikitext, one streaming pass over the dump) and decided offline in S1.

Output: data/phase0/full/harvest_animation.jsonl.gz (atomic) + harvest_animation_summary.json.
Read-only on the dump and on the first harvest.

    python -m tool.RAGWikipediaSeries.harvest_animation
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time

from .common import DATA_DIR, DUMP_PATH, iter_pages, open_dump

log = logging.getLogger("series.s1b.harvest")
SCAN = DATA_DIR / "phase0" / "full" / "scan_pages.jsonl"
SELECTION = DATA_DIR / "phase0" / "harvest_selection.json"
OUT = DATA_DIR / "phase0" / "full" / "harvest_animation.jsonl.gz"


def select_ids() -> set[int]:
    already = {int(k) for k in json.loads(SELECTION.read_text())["pages"]}
    ids = set()
    for line in open(SCAN, encoding="utf-8"):
        row = json.loads(line)
        if "fumetto e animazione" in row["tpl_kw"] and row["id"] not in already:
            ids.add(row["id"])
    return ids


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ids = select_ids()
    log.info("selected %d additional pages", len(ids))
    tmp = OUT.with_name(OUT.name + ".part")
    kept, started, seen = 0, time.monotonic(), set()
    with open_dump(DUMP_PATH) as stream, gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
        for n, page in enumerate(iter_pages(stream), 1):
            if page.namespace == 0 and page.page_id in ids and not page.redirect:
                kept += 1
                seen.add(page.page_id)
                handle.write(json.dumps({"id": page.page_id, "ns": 0, "title": page.title, "rev": page.revision_id,
                                         "kind": "article", "text": page.text}, ensure_ascii=False, separators=(",", ":")) + "\n")
            if n % 500000 == 0:
                log.info("%d pages, kept %d, %.0f s", n, kept, time.monotonic() - started)
    os.replace(tmp, OUT)
    summary = {"selected": len(ids), "kept": kept, "missing_ids": len(ids - seen), "bytes": OUT.stat().st_size,
               "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(), "seconds": round(time.monotonic() - started, 1)}
    (OUT.parent / "harvest_animation_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log.info("done %s", summary)


if __name__ == "__main__":
    main()
