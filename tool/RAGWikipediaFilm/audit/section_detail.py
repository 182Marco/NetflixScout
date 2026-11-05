"""Phase 6: for the 25 contaminated pages, list EVERY heading inside the captured plot section with its cleaned length, so each
cut can be checked by name (not only by the first sibling). Reads the LOCAL dump, no network; writes data/audit/section_detail.json."""
from __future__ import annotations

import bz2
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from ..clean_plot import clean_wikitext, find_plot_section

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    ids = {c["wikipedia_page_id"] for c in json.loads((ROOT / "audit/synopsis_contamination.json").read_text())["records"]}
    dump = ROOT / "data" / "raw" / f"itwiki-{cfg['dump']['date']}-pages-articles.xml.bz2"
    out = {}
    with bz2.open(dump, "rb") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag.endswith("}page"):
                pid = int(el.find("{*}id").text)
                if pid in ids:
                    text = el.find("{*}revision/{*}text").text or ""
                    sec, head, _ = find_plot_section(text, cfg["extract"]["plot_headings"])
                    hs = sec.filter_headings()
                    raw = str(sec)
                    marks = [(raw.find(str(h)), str(h.title).strip(), h.level) for h in hs]
                    parts = []
                    for i, (pos, title, lvl) in enumerate(marks):
                        end = marks[i + 1][0] if i + 1 < len(marks) else len(raw)
                        body = clean_wikitext(raw[pos + len(str(hs[i])):end]) if i else clean_wikitext(raw[:marks[1][0]] if len(marks) > 1 else raw)
                        parts.append({"heading": title, "level": lvl, "chars": len(body), "start": body[:100], "end": body[-100:]})
                    out[pid] = {"plot_heading": head, "parts": parts}
                    if len(out) == len(ids):
                        break
                el.clear()
    (ROOT / "data/audit/section_detail.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("done", len(out))


if __name__ == "__main__":
    main()
