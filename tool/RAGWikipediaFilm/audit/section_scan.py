"""Phase 4: does the Phase 1 plot extraction swallow sibling sections? Re-reads the LOCAL dump (no network) for the 41,421
candidate pages, repeats `find_plot_section` exactly as Phase 1 did and checks whether the captured section contains a heading
of the same or a higher level (a sibling section: production, release, reception...). For those pages it also computes the
synopsis that a correct cut would give. Read-only on every Phase 1 file; writes data/audit/section_scan.jsonl and section_fix.jsonl."""
from __future__ import annotations

import bz2
import json
import re
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from ..clean_plot import clean_wikitext, find_plot_section

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit"


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    headings = cfg["extract"]["plot_headings"]
    min_chars, min_words = cfg["extract"]["min_plot_chars"], cfg["extract"]["min_plot_words"]
    dump = ROOT / "data" / "raw" / f"itwiki-{cfg['dump']['date']}-pages-articles.xml.bz2"
    ids = {int(json.loads(l)["page_id"]) for l in (ROOT / "data" / "processed" / "candidates.jsonl").open()}
    OUT.mkdir(parents=True, exist_ok=True)
    scan, fix = (OUT / "section_scan.jsonl").open("w"), (OUT / "section_fix.jsonl").open("w")
    done = seen = 0
    t0 = time.time()
    with bz2.open(dump, "rb") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if not el.tag.endswith("}page"):
                continue
            seen += 1
            pid = int(el.find("{*}id").text)
            if pid in ids:
                text = el.find("{*}revision/{*}text").text or ""
                sec, head, flags = find_plot_section(text, headings)
                if sec is None:
                    scan.write(json.dumps({"page_id": pid, "plot_section": False}) + "\n")
                else:
                    hs = sec.filter_headings()
                    base = hs[0].level
                    siblings = [h for h in hs[1:] if h.level <= base]
                    row = {"page_id": pid, "plot_section": True, "heading": head, "raw_len": len(str(sec)),
                           "headings_inside": len(hs) - 1, "siblings_inside": len(siblings)}
                    if siblings:
                        raw = str(sec)
                        cut = raw.find(str(siblings[0]))
                        fixed = clean_wikitext(raw[:cut]) if cut > 0 else ""
                        row.update({"first_sibling": str(siblings[0].title).strip(), "fixed_chars": len(fixed),
                                    "fixed_words": len(fixed.split()),
                                    "would_be_rejected": len(fixed) < min_chars or len(fixed.split()) < min_words})
                        fix.write(json.dumps({"page_id": pid, "synopsis": fixed}, ensure_ascii=False) + "\n")
                    scan.write(json.dumps(row) + "\n")
                done += 1
                if done % 5000 == 0:
                    print(done, "candidate pages,", seen, "pages read,", round(time.time() - t0), "s", flush=True)
            el.clear()
    scan.close(); fix.close()
    print("finished", done, "of", len(ids), "candidate pages in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
