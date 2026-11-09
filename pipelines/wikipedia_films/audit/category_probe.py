"""Phase 8: Wikipedia's own categories and lead sentence for a handful of pages, read from the LOCAL dump (no network). Used to decide
whether a TV work is one film shown over two evenings or a miniseries with distinct episodes. Writes data/audit/category_probe.json."""
from __future__ import annotations

import bz2
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEVEN = ["Q248392", "Q3888794", "Q565293", "Q228396", "Q538952", "Q2421745", "Q3790916"]


def main(ids: list[str]) -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    films = {}
    for line in (ROOT / "data/processed/films.jsonl").open():
        f = json.loads(line)
        if f["film_id"] in ids:
            films[f["wikipedia_page_id"]] = f
    out = {}
    with bz2.open(ROOT / "data/raw" / f"itwiki-{cfg['dump']['date']}-pages-articles.xml.bz2", "rb") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if el.tag.endswith("}page"):
                pid = int(el.find("{*}id").text)
                if pid in films:
                    text = el.find("{*}revision/{*}text").text or ""
                    lead = re.split(r"\n==", text, 1)[0]
                    out[films[pid]["film_id"]] = {
                        "title": films[pid]["title"],
                        "categories": re.findall(r"\[\[Categoria:([^\]|]+)", text),
                        "lead": re.sub(r"\s+", " ", re.sub(r"\{\{[^}]*\}\}|\[\[|\]\]|'''?|<[^>]+>", "", lead))[:600],
                        "headings": re.findall(r"^=+\s*([^=\n]+?)\s*=+\s*$", text, re.M)[:25],
                        "infobox_name": (re.search(r"\{\{\s*([A-Za-zÀ-ÿ ]+)\s*\|", text) or [None, None])[1]}
                    if len(out) == len(films):
                        break
                el.clear()
    (ROOT / "data/audit/category_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("done", len(out), "of", len(films))


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or SEVEN)
