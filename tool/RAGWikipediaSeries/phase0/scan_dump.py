"""Phase 0 scan: ONE streaming pass over the whole Italian Wikipedia dump.

Records, without any interpretation, the cheap structural signals of every page that may concern TV
series, seasons or episodes (templates, categories, headings, section sizes, first links, infobox
parameters), plus the inventory of related templates and categories and the redirects. The rules that
decide what is a series / season / episode are taken afterwards (`analyze.py`) by looking at these
numbers. Read-only on the dump; outputs are written atomically (`.part` then rename).

    python -m tool.RAGWikipediaSeries.phase0.scan_dump [--sample] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Iterator

import mwparserfromhell

from ..common import DATA_DIR, DUMP_DATE, DUMP_PATH, Page, iter_pages, open_dump

log = logging.getLogger("series.phase0.scan")

SCAN_VERSION = 1
OUT_DIR = DATA_DIR / "phase0"

# Deliberately broad: it only decides what is RECORDED, never what is accepted. Noise (football
# "Serie A", sports "stagione") is filtered later with the numbers in front of us.
SIGNAL_RE = re.compile(
    r"serie|fiction|episod|stagion|season|anime|manga|telefilm|miniserie|sitcom|sit-com|soap|"
    r"telenovela|programm[ai]|puntat|televis|\btv\b|cartoni|animazion|web ?serie|\boav\b|\bova\b|"
    r"\bona\b|reality|talk show|docuserie|antologi|sceneggiat",
    re.I,
)
TITLE_PATTERNS = {
    "episodes_of": re.compile(r"^(episodi|lista degli episodi|elenco degli episodi|episodi di)\b", re.I),
    "season_of": re.compile(r"\b(stagione|season)\b|\(\w+ stagione\)|\bstagioni?\b", re.I),
    "episode_paren": re.compile(r"\((episodio|puntata)[^)]*\)", re.I),
    "series_paren": re.compile(r"\((serie|miniserie|programma|sitcom|anime|fiction)[^)]*\)", re.I),
}
TEMPLATE_RE = re.compile(r"\{\{\s*([^{}|\n<>\[\]]{1,80}?)\s*(?=[|}\n<])")
CATEGORY_RE = re.compile(r"\[\[\s*(?:categoria|category)\s*:\s*([^\]|]+)", re.I)
HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
LINK_RE = re.compile(r"\[\[([^\]|#\n]{1,120})")
REDIRECT_RE = re.compile(r"#\s*(?:redirect|rinvia)\w*\s*:?\s*\[\[([^\]|#]+)", re.I)
TABLE_ROW_RE = re.compile(r"^\|-", re.M)

MAX_CATEGORIES = 40
MAX_HEADINGS = 80
MAX_LEAD_LINKS = 8
LEAD_CHARS = 1500
MAX_PARAMS = 30
MAX_VALUE_CHARS = 200
OUTPUT_FILES = {
    "pages": "scan_pages.jsonl",
    "templates": "scan_templates.jsonl",
    "categories": "scan_categories.jsonl",
    "redirects": "scan_redirects.jsonl",
}


def normalize_template(name: str) -> str:
    return " ".join(name.replace("_", " ").split()).lower()


def title_signals(title: str) -> list[str]:
    return [label for label, pattern in TITLE_PATTERNS.items() if pattern.search(title)]


def section_sizes(text: str) -> list[tuple[int, str, int]]:
    """(level, heading, characters up to the next heading of the same or higher level)."""
    marks = [(m.start(), m.end(), len(m.group(1)), m.group(2)) for m in HEADING_RE.finditer(text)]
    out = []
    for index, (_, end, level, title) in enumerate(marks[:MAX_HEADINGS]):
        stop = len(text)
        for later in marks[index + 1:]:
            if later[2] <= level:
                stop = later[0]
                break
        out.append((level, title, stop - end))
    return out


def infobox_params(text: str, template_name: str) -> dict[str, str]:
    """Parameters of the first template with the given (normalized) name, values truncated."""
    code = mwparserfromhell.parse(text[:60000])
    for template in code.filter_templates(recursive=False):
        if normalize_template(str(template.name)) == template_name:
            params = {}
            for param in list(template.params)[:MAX_PARAMS]:
                key = " ".join(str(param.name).strip().lower().split())
                params[key] = " ".join(str(param.value).split())[:MAX_VALUE_CHARS]
            return params
    return {}


def page_row(page: Page) -> dict | None:
    """Row for a namespace-0 article that carries any signal, otherwise None."""
    text = page.text
    templates = [normalize_template(t) for t in TEMPLATE_RE.findall(text)]
    kw_templates = sorted({t for t in templates if SIGNAL_RE.search(t)})
    categories = CATEGORY_RE.findall(text)
    kw_categories = [c.strip() for c in categories if SIGNAL_RE.search(c)]
    t_signals = title_signals(page.title)
    if not (kw_templates or kw_categories or t_signals):
        return None
    first5 = []
    for name in templates:
        if name not in first5:
            first5.append(name)
        if len(first5) == 5:
            break
    params: dict[str, str] = {}
    params_of = next((t for t in templates if SIGNAL_RE.search(t)), None)
    if params_of is not None:
        params = infobox_params(text, params_of)
    sections = section_sizes(text)
    return {
        "id": page.page_id,
        "title": page.title,
        "rev": page.revision_id,
        "len": len(text),
        "tpl_first": first5,
        "tpl_kw": kw_templates,
        "tpl_kw_params_of": params_of,
        "params": params,
        "cats_kw": kw_categories[:MAX_CATEGORIES],
        "cats_n": len(categories),
        "title_sig": t_signals,
        "sections": sections,
        "table_rows": len(TABLE_ROW_RE.findall(text)),
        "lead_links": LINK_RE.findall(text[:LEAD_CHARS])[:MAX_LEAD_LINKS],
        "has_disambig": any(t.startswith("disambigua") for t in first5),
    }


def redirect_row(page: Page) -> dict | None:
    match = REDIRECT_RE.match(page.text.lstrip())
    target = match.group(1).strip() if match else None
    if SIGNAL_RE.search(page.title) or (target and SIGNAL_RE.search(target)):
        return {"id": page.page_id, "ns": page.namespace, "title": page.title, "target": target}
    return None


def other_namespace_row(page: Page) -> tuple[str, dict] | None:
    if page.namespace == 10 and SIGNAL_RE.search(page.title):
        match = REDIRECT_RE.match(page.text.lstrip())
        return "templates", {
            "id": page.page_id,
            "title": page.title,
            "len": len(page.text),
            "redirect_to": match.group(1).strip() if match else None,
            "head": " ".join(page.text[:240].split()),
        }
    if page.namespace == 14 and SIGNAL_RE.search(page.title):
        return "categories", {
            "id": page.page_id,
            "title": page.title,
            "len": len(page.text),
            "parents": CATEGORY_RE.findall(page.text)[:10],
        }
    return None


def scan(pages: Iterator[Page], out_dir: Path, *, limit: int | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    for key, name in OUTPUT_FILES.items():
        handles[key] = open(out_dir / (name + ".part"), "w", encoding="utf-8")
    ns_count: Counter[int] = Counter()
    redirects = 0
    articles = 0
    rows = Counter()
    kw_template_pages: Counter[str] = Counter()
    kw_category_pages: Counter[str] = Counter()
    started = time.monotonic()

    def write(key: str, row: dict) -> None:
        handles[key].write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        rows[key] += 1

    seen = 0
    try:
        for page in pages:
            seen += 1
            ns_count[page.namespace] += 1
            if limit is not None and seen > limit:
                break
            is_redirect = page.redirect or page.text.lstrip().lower().startswith("#redirect")
            if is_redirect:
                redirects += 1
                row = redirect_row(page)
                if row is not None:
                    write("redirects", row)
            elif page.namespace == 0:
                articles += 1
                row = page_row(page)
                if row is not None:
                    write("pages", row)
                    kw_template_pages.update(row["tpl_kw"])
                    kw_category_pages.update(set(row["cats_kw"]))
            else:
                other = other_namespace_row(page)
                if other is not None:
                    write(other[0], other[1])
            if seen % 200000 == 0:
                log.info("%d pages, %d signal rows, %.0f s", seen, rows["pages"], time.monotonic() - started)
    finally:
        for handle in handles.values():
            handle.close()
    for name in OUTPUT_FILES.values():
        os.replace(out_dir / (name + ".part"), out_dir / name)
    return {
        "scan_version": SCAN_VERSION,
        "pages_seen": seen,
        "namespaces": {str(k): v for k, v in sorted(ns_count.items())},
        "redirects": redirects,
        "ns0_articles": articles,
        "rows": dict(rows),
        "kw_template_pages": dict(kw_template_pages.most_common()),
        "kw_category_pages": dict(kw_category_pages.most_common()),
        "seconds": round(time.monotonic() - started, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="use the 80 MB truncated sample")
    parser.add_argument("--limit", type=int, default=None, help="stop after N pages (tests)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    dump = DUMP_PATH.with_name(DUMP_PATH.name + ".sample") if args.sample else DUMP_PATH
    out_dir = args.out or (OUT_DIR / ("sample" if args.sample else "full"))
    info_path = DUMP_PATH.with_name(DUMP_PATH.name + ".info.json")
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    log.info("dump=%s out=%s", dump, out_dir)
    with open_dump(dump) as stream:
        summary = scan(iter_pages(stream, allow_truncated=args.sample), out_dir, limit=args.limit)
    summary.update({"dump_file": dump.name, "dump_bytes": dump.stat().st_size, "dump_date": DUMP_DATE,
                    "dump_info": info})
    (out_dir / "scan_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("done: %s", {k: summary[k] for k in ("pages_seen", "ns0_articles", "redirects", "rows", "seconds")})


if __name__ == "__main__":
    main()
