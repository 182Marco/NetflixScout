"""Phase S1: definitive, reproducible extraction of the raw catalogue from the harvested wikitext.

Input : data/phase0/full/harvest.jsonl.gz (raw wikitext of the 37,717 pages selected by the full scan;
        the dump itself is NOT read again). Output: data/s1/*.jsonl (+ manifest.json), written atomically
        and sorted by page id, so two runs give byte-identical files.

Entity types written (nothing is linked here: relations are built in S3 from the hints recorded):
  series.jsonl        TV series, miniseries, serials, web series, anime / animated series (+ episodic programmes)
  seasons.jsonl       pages "Episodi di X (n stagione)": lead text, episode table rows, relation hints
  episodes.jsonl      episodes with prose: sections of season pages / episode-list pages / series pages and
                      the autonomous episode pages ({{Episodio SerieTV}}, {{Episodio dorama}})
  episode_lists.jsonl "Episodi di X" pages that are not a season page (relation by hints only)
  tv_movies.jsonl     narrative TV movies (own type, never linked to seasons or episodes)
  uncertain.jsonl     candidates the data cannot decide (TV movies, programmes): kept apart, never forced
  excluded.jsonl      every harvested page NOT kept, with the reason (manga, documentaries, shows, ...)

    python -m tool.RAGWikipediaSeries.extract_series [--limit N]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from . import tv_movies
from .clean_plot import clean_wikitext, extract_plot
from .common import DATA_DIR
from .phase0.analyze_seasons import BOILER, SEASON_TITLE, sections
import mwparserfromhell

from .phase0.analyze_series import HARVEST, PLOT_HEADINGS, kind_of
from .phase0.build_units import BACK, ORD, TITLE, season_number
from .phase0.scan_dump import infobox_params, normalize_template

HARVEST_ANIMATION = HARVEST.with_name("harvest_animation.jsonl.gz")  # S1b: pages the first harvest did not select

SCHEMA_VERSION = 1
OUT_DIR = DATA_DIR / "s1"
FILES = ("series", "seasons", "episodes", "episode_lists", "tv_movies", "uncertain", "excluded")
WIKI = "https://it.wikipedia.org/wiki/"

PLOT_MIN_CHARS, PLOT_MIN_WORDS = 400, 60       # decision 5: same threshold as the films
LEAD_MIN_CHARS = 400                           # the introduction as a text of its own kind (lower reliability)
EPISODE_MIN_CHARS = 150                        # provisional threshold for an episode section (Phase 0)
TEXT_CAP = 60000
LEAD_CAP = 6000

EPISODE_LIST_TITLE = re.compile(r"^(episodi|lista degli episodi|elenco degli episodi|lista episodi)\b", re.I)
DORAMA = re.compile(r"dorama|drama (giapponesi|coreani|cinesi|taiwanesi|thailandesi)|"
                    r"serie televisive (giapponesi|sudcoreane|cinesi|taiwanesi|thailandesi|hongkonghesi)", re.I)
CATEGORY = re.compile(r"\[\[\s*categoria\s*:\s*([^\]|]+)", re.I)
INLINE_HEADING = re.compile(r"^(episodi|puntate|elenco degli episodi|lista degli episodi|stagioni|serie)\b", re.I)
SEASON_HEADING = re.compile(r"\b(stagione|serie|parte|ciclo)\b|^\d+\s*$", re.I)
TABLE = re.compile(r"^\{\|.*?^\|\}", re.M | re.S)
EPISODE_INFOBOX = ("episodio serietv", "episodio dorama")
# Programmes (TV shows) are kept only when they are narrative fiction or have episode pages of their own.
NARRATIVE_PROGRAMME_GENRES = ("commedia", "sitcom", "drammatico", "fiction", "thriller", "fantascienza",
                              "poliziesco", "giallo", "horror", "azione", "avventura", "fantasy", "fantastico",
                              "western", "sentimentale", "soap", "telenovela", "animazione")
UNCERTAIN_PROGRAMME_GENRES = ("comico", "satirico", "satira", "sketch", "storico", "per bambini", "per ragazzi")

LIGHT_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
LIGHT_REF = re.compile(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", re.S)
LIGHT_TPL = re.compile(r"\{\{[^{}]*\}\}")
CELL_ATTR = re.compile(r"^\s*(?:(?:rowspan|colspan|style|class|align|width|bgcolor|scope|valign)\s*=\s*(?:\"[^\"]*\"|'[^']*'|\S+)\s*)+\|(?!\|)")


def url_of(title: str) -> str:
    return WIKI + quote(title.replace(" ", "_"), safe="_():,'!-")


def digits(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def year_of(value: str | None) -> int | None:
    match = re.search(r"(1[89]\d\d|20\d\d)", tv_movies.clean_param(value))
    return int(match.group(1)) if match else None


def light_clean(cell: str) -> str:
    """Cheap cleaning of one TABLE cell (metadata, not prose): links, refs, simple templates, quotes."""
    cell = LIGHT_REF.sub("", cell)
    for _ in range(3):
        cell = LIGHT_TPL.sub("", cell)
    cell = LIGHT_LINK.sub(r"\1", cell)
    cell = re.sub(r"<[^>]+>", " ", cell).replace("'''", "").replace("''", "")
    return " ".join(cell.split())


# ----------------------------------------------------------------------------------------------- tables
HEADER_KEYS = (("number", ("n°", "nº", "n.", "n", "#", "no.", "num", "ep", "episodio", "puntata", "numero")),
               ("title_original", ("titolo originale", "original title", "titolo inglese")),
               ("title_it", ("titolo italiano", "titolo", "titolo it")),
               ("date", ("prima tv", "prima visione", "data", "messa in onda", "trasmissione", "uscita", "pubblicazione", "originale", "usa", "italia")))


def header_role(label: str) -> str | None:
    low = label.lower().strip(" .:")
    for role, words in HEADER_KEYS:
        if any(low == w or (len(w) > 4 and w in low) for w in words):
            return role
    return None


def parse_table(raw: str) -> dict:
    """Header labels and data rows (cleaned cell lists) of one wikitable. Heuristic: rows shorter than the
    header (rowspan) are flagged `partial`, never aligned by guessing."""
    header: list[str] = []
    rows: list[list[str]] = []
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current:
            rows.append(current)
        current = None

    for line in raw.split("\n")[1:]:
        line = line.rstrip()
        if line.startswith("|}"):
            break
        if line.startswith("|-"):
            flush()
            current = []
        elif line.startswith("!"):
            cells = [light_clean(CELL_ATTR.sub("", c.strip())) for c in re.split(r"!!|\|\|", line[1:])]
            if current is None or not rows and not current:
                header.extend(cells)
        elif line.startswith("|") and not line.startswith("|+"):
            if current is None:
                current = []
            for c in line[1:].split("||"):
                current.append(light_clean(CELL_ATTR.sub("", c.strip())))
        elif current:
            current[-1] = (current[-1] + " " + light_clean(line)).strip()
    flush()
    return {"header": header, "rows": rows}


def episode_rows(text: str) -> list[dict]:
    """Episode metadata rows of every wikitable of the page: number, titles, dates when the header allows."""
    out: list[dict] = []
    for raw in TABLE.findall(text):
        table = parse_table(raw)
        roles = [header_role(h) for h in table["header"]]
        if "number" not in roles and not any(r in ("title_original", "title_it") for r in roles):
            continue
        for cells in table["rows"]:
            row: dict = {"cells": cells[:8]}
            if len(cells) == len(roles):
                for role, value in zip(roles, cells):
                    if role == "date":
                        row.setdefault("dates", []).append(value)
                    elif role and value:
                        row.setdefault(role, value)
            else:
                row["partial"] = True
                if cells and "number" in roles[:1]:
                    row["number"] = cells[0]
            if "number" in row:
                row["number_int"] = digits(row["number"])
            if row.get("number") or row.get("title_original") or row.get("title_it"):
                out.append(row)
    return out


# ------------------------------------------------------------------------------------------------- text
def cap(text: str) -> tuple[str, bool]:
    return (text[:TEXT_CAP], True) if len(text) > TEXT_CAP else (text, False)


def lead_of(text: str) -> str:
    head = re.split(r"^\{\|", text, maxsplit=1, flags=re.M)[0]
    head = re.split(r"^==", head, maxsplit=1, flags=re.M)[0]
    return clean_wikitext(head[:LEAD_CAP])


def series_text(text: str) -> dict:
    plot = extract_plot(text, headings=PLOT_HEADINGS, min_chars=0, min_words=0)
    plot_text, plot_cut = cap(plot.text or "")
    lead = lead_of(text)
    words = len(plot_text.split())
    if len(plot_text) >= PLOT_MIN_CHARS and words >= PLOT_MIN_WORDS:
        kind = "plot"
    elif len(lead) >= LEAD_MIN_CHARS:
        kind = "lead"
    else:
        kind = "none"
    return {"text_kind": kind, "plot_heading": plot.heading, "plot_flags": plot.flags, "plot_text": plot_text,
            "plot_chars": len(plot_text), "plot_words": words, "plot_truncated": plot_cut,
            "lead_text": lead, "lead_chars": len(lead)}


EPISODE_META = re.compile(r"^(titolo originale|titolo italiano|titolo|prima tv[^:\n]*|prima visione[^:\n]*|diretto da|scritto da|regia|sceneggiatura|"
                          r"soggetto|ospiti?|guest star|guest|trasmess[oa][^:\n]*|data[^:\n]*|episodio dedicato a|musiche|numero|durata)\s*:", re.I)


def strip_episode_metadata(prose: str) -> tuple[str, list[str]]:
    """Leading credit / title / air-date lines ("Titolo originale: ...", "Sceneggiatura: ...") are metadata, not
    plot: they are cut from the text (kept apart in `meta_lines`) so the vector describes the story only."""
    lines = prose.split("\n")
    meta: list[str] = []
    while lines and (not lines[0].strip() or EPISODE_META.match(lines[0].strip())):
        if lines[0].strip():
            meta.append(lines[0].strip()[:300])
        lines.pop(0)
    return "\n".join(lines).strip(), meta[:6]


def episode_sections(text: str, source: str) -> list[dict]:
    """Per-episode prose of a season / episode-list page: level-2 sections that are not boilerplate. The
    plot is the `Trama` sub-section when there is one, else the prose without the credit bullets."""
    secs = sections(text)
    out = []
    for index, sec in enumerate(secs):
        if sec["level"] != 2 or BOILER.match(sec["title"]):
            continue
        body = TABLE.sub("", sec["body"])
        plot_body = None
        for sub in secs[index + 1:]:
            if sub["level"] <= 2:
                break
            if sub["level"] == 3 and tv_movies_heading(sub["title"]):
                plot_body = sub["body"]
                break
        if plot_body is None:
            first_sub = re.search(r"^===", body, re.M)
            plot_body = body[: first_sub.start()] if first_sub else body
        plot_body = "\n".join(l for l in plot_body.split("\n") if not re.match(r"^\s*[*:;]\s*(diretto|regia|scritto|sceneggiatura|guest|ospiti|"
                                                                           r"direttore|trasmesso|prima tv|data)", l, re.I))
        prose, meta = strip_episode_metadata(clean_wikitext(plot_body))
        if len(prose) >= EPISODE_MIN_CHARS:
            out.append({"heading": sec["title"], "anchor": sec["title"], "plot_text": prose[:TEXT_CAP],
                        "plot_chars": len(prose), "source": source, "meta_lines": meta})
    return out


def tv_movies_heading(title: str) -> bool:
    return title.strip().lower() in ("trama", "plot", "sinossi", "riassunto", "storia")


def inline_sections(text: str) -> tuple[list[dict], list[dict]]:
    """Episode information INSIDE a series page: metadata rows of its tables and the sub-sections of an
    'Episodi' / 'Stagioni' section that carry prose (kind season | episode | other, decided in S3)."""
    secs = sections(text)
    rows: list[dict] = []
    subs: list[dict] = []
    for index, sec in enumerate(secs):
        if sec["level"] > 2 or not INLINE_HEADING.match(sec["title"]):
            continue
        rows.extend(episode_rows(sec["body"]))
        for sub in secs[index + 1:]:
            if sub["level"] <= sec["level"]:
                break
            prose = clean_wikitext(TABLE.sub("", sub["body"]))
            if len(prose) >= EPISODE_MIN_CHARS:
                subs.append({"heading": sub["title"], "level": sub["level"], "plot_text": prose[:TEXT_CAP],
                             "plot_chars": len(prose), "looks_like_season": bool(SEASON_HEADING.search(sub["title"]))})
    return rows, subs


# ---------------------------------------------------------------------------------------------- records
def base_record(d: dict, entity_type: str) -> dict:
    return {"record_id": f"wp-{d['id']}", "entity_type": entity_type, "page_id": d["id"], "title": d["title"],
            "revision_id": d["rev"], "wikipedia_url": url_of(d["title"])}


def series_subtype(kind: str) -> tuple[str, str | None]:
    if kind.startswith("fiction:"):
        t = kind.split(":", 1)[1]
        for prefix, sub in (("miniserie", "miniseries"), ("webserie", "web_series"), ("serial", "serial"), ("serie", "tv_series")):
            if t.startswith(prefix):
                return sub, None
    if kind.startswith("anim:"):
        t, _, s = kind[5:].partition("/")
        return ("anime" if "anime" in t else "animated_series"), (s or None)
    return "programme", None


def info_of(params: dict[str, str]) -> dict:
    keep = ("titolo originale", "titolo italiano", "paese", "paese 2", "lingua originale", "genere", "genere 2",
            "rete tv", "rete tv italiana", "ideatore", "regista", "stagioni", "episodi", "puntate", "durata", "casa produzione")
    info = {k.replace(" ", "_"): tv_movies.clean_param(params.get(k)) for k in keep if tv_movies.clean_param(params.get(k))}
    cast = tv_movies.clean_param(params.get("attori"))
    if cast:
        info["cast"] = cast[:600]
    info["year"] = year_of(params.get("anno prima visione") or params.get("data inizio") or params.get("inizio prima visione"))
    info["year_end"] = year_of(params.get("fine prima visione") or params.get("data fine"))
    return {k: v for k, v in info.items() if v}


def programme_policy(params: dict[str, str], has_episode_pages: bool, has_rows: bool) -> tuple[str, list[str]]:
    genres = [tv_movies.clean_param(params.get(k)).lower() for k in ("genere", "genere 2", "genere 3")]
    genres = [g for g in genres if g]
    narrative = [g for g in genres if any(w in g for w in NARRATIVE_PROGRAMME_GENRES)]
    if has_episode_pages:
        return "keep", ["has_episode_pages"]
    if narrative:
        return "keep", ["narrative_genre:" + narrative[0]]
    if any(w in g for g in genres for w in UNCERTAIN_PROGRAMME_GENRES):
        return "uncertain", ["ambiguous_genre:" + genres[0]]
    return "exclude", ["not_episodic_programme:" + (genres[0] if genres else "no_genre")]


def animation_infoboxes(text: str) -> list[dict[str, str]]:
    """Parameters of EVERY top-level `{{Fumetto e animazione}}` infobox of the page (a page can describe a
    manga and its anime adaptation with two of them; the scan only kept the first)."""
    boxes = []
    for template in mwparserfromhell.parse(text[:60000]).filter_templates(recursive=False):
        if normalize_template(str(template.name)) == "fumetto e animazione":
            boxes.append({" ".join(str(p.name).strip().lower().split()): " ".join(str(p.value).split())[:200]
                          for p in list(template.params)[:40]})
    return boxes


def is_tv_animation(box: dict[str, str]) -> bool:
    kind = tv_movies.clean_param(box.get("tipo")).lower()
    sub = tv_movies.clean_param(box.get("sottotipo")).lower()
    return ("anime" in kind or "cartone" in kind) and any(x in sub for x in ("serie tv", "oav", "ona", "webserie"))


def animation_kind(text: str) -> tuple[str, dict[str, str], bool] | None:
    """(kind, params, mixed_media) of the first TV-animation infobox, or None when no infobox describes a series.
    `mixed_media` is true when the page also carries a manga / film / other infobox (a franchise page)."""
    boxes = animation_infoboxes(text)
    tv = [b for b in boxes if is_tv_animation(b)]
    if not tv:
        return None
    box = tv[0]
    kind = f"anim:{tv_movies.clean_param(box.get('tipo')).lower()}/{tv_movies.clean_param(box.get('sottotipo')).lower()}"
    return kind, box, len(boxes) > len(tv)


def episode_page(d: dict) -> dict | None:
    head = d["text"][:60000]
    low = head.lower().replace("_", " ")
    for name in EPISODE_INFOBOX:
        if "{{" + name in low.replace("{{ ", "{{"):
            params = infobox_params(head, name)
            if not params:
                continue
            rec = base_record(d, "episode")
            text = series_text(d["text"])
            rec.update({"source": "episode_page", "infobox": name, "params": {k: tv_movies.clean_param(v)[:200] for k, v in list(params.items())[:20]},
                        **text})
            return rec
    return None


# ------------------------------------------------------------------------------------------------- driver
def _limited(factory, limit):
    for n, d in enumerate(factory()):
        if limit is not None and n >= limit:
            return
        yield d


def process(factory, *, limit: int | None = None) -> tuple[dict[str, list[dict]], Counter]:
    """`factory()` returns a fresh iterator over the harvested pages (two streaming passes, no big list)."""
    out: dict[str, list[dict]] = {k: [] for k in FILES}
    stats: Counter = Counter()
    # Titles of "Episodi di X" pages (base name X): a programme with such pages has an episode structure.
    base_with_pages: set[str] = set()
    for d in _limited(factory, limit):
        m = re.match(r"^Episodi (?:di|de|del|dei|della|degli|delle|dell'|d')\s*(.+?)(?: \([^()]+ stagione\))?$", d["title"])
        if m:
            base_with_pages.add(m.group(1).strip())
    for d in _limited(factory, limit):
        if d["ns"] != 0:
            continue
        stats["pages"] += 1
        title, text = d["title"], d["text"]
        if SEASON_TITLE.match(title):
            rec = base_record(d, "season")
            m = TITLE.match(title)
            back = BACK.search(text[:1500])
            rows = episode_rows(text)
            eps = episode_sections(text, "season_page")
            rec.update({"series_name_from_title": m.group(1) if m else None, "season_qualifier": m.group(2) if m else None,
                        "season_number": season_number(m.group(2)) if m else None,
                        "torna_a": back.group(1) if back else None, "lead_text": lead_of(text), "table_rows": rows,
                        "table_row_count": len(rows), "episode_section_count": len(eps)})
            rec["lead_chars"] = len(rec["lead_text"])
            out["seasons"].append(rec)
            for e in eps:
                er = {"record_id": f"wp-{d['id']}#s{len(out['episodes'])}", "entity_type": "episode", "page_id": d["id"],
                      "title": e["heading"], "revision_id": d["rev"], "wikipedia_url": url_of(title) + "#" + quote(e["heading"].replace(" ", "_")),
                      "parent_page_id": d["id"], "parent_title": title, **e}
                out["episodes"].append(er)
            continue
        if EPISODE_LIST_TITLE.match(title):
            rec = base_record(d, "episode_list")
            back = BACK.search(text[:1500])
            rows = episode_rows(text)
            eps = episode_sections(text, "episode_list_page")
            rec.update({"torna_a": back.group(1) if back else None, "lead_text": lead_of(text), "table_rows": rows,
                        "table_row_count": len(rows), "episode_section_count": len(eps)})
            out["episode_lists"].append(rec)
            for e in eps:
                out["episodes"].append({"record_id": f"wp-{d['id']}#l{len(out['episodes'])}", "entity_type": "episode", "page_id": d["id"],
                                        "title": e["heading"], "revision_id": d["rev"], "wikipedia_url": url_of(title),
                                        "parent_page_id": d["id"], "parent_title": title, **e})
            continue
        kind, params = kind_of(text)
        mixed = False
        if not kind.startswith("fiction:") and kind != "programma" and "fumetto e animazione" in text[:60000].lower():
            found = animation_kind(text)
            if found:
                kind, params, mixed = found
                stats["animation_mixed_media" if mixed else "animation_single"] += 1
            elif kind.startswith("anim:"):
                kind = "anim:not_tv_series"
        if kind == "fiction:film tv":
            stats["tv_movie_candidates"] += 1
            t = series_text(text)
            verdict = tv_movies.classify(params, text, plot_chars=t["plot_chars"], plot_words=t["plot_words"], lead_chars=t["lead_chars"])
            rec = base_record(d, "tv_movie")
            rec.update({"subtype": "tv_movie", "info": info_of(params), "classification": verdict, **t,
                        "director": tv_movies.clean_param(params.get("regista")),
                        "network": tv_movies.clean_param(params.get("rete tv")) or None,
                        "has_text": t["text_kind"] != "none", "ids": {}})
            target = {tv_movies.NARRATIVE: "tv_movies", tv_movies.UNCERTAIN: "uncertain", tv_movies.NON_NARRATIVE: "excluded"}[verdict["class"]]
            if target == "excluded":
                out["excluded"].append({**base_record(d, "tv_movie"), "reason": "non_narrative_tv_movie", "detail": verdict["reasons"]})
            else:
                out[target].append(rec)
            continue
        is_series = kind.startswith(("fiction:serie", "fiction:miniserie", "fiction:serial", "fiction:webserie")) or (
            kind.startswith("anim:") and kind != "anim:not_tv_series")
        if is_series or kind == "programma":
            rows, subs = inline_sections(text)
            base = re.sub(r" \([^)]*\)$", "", title)
            target, why = "series", []
            if kind == "programma":
                target, why = programme_policy(params, base in base_with_pages, bool(rows))
                target = {"keep": "series", "uncertain": "uncertain", "exclude": "excluded"}[target]
                stats[f"programme_{target}"] += 1
            if target == "excluded":
                out["excluded"].append({**base_record(d, "series"), "reason": "programme_not_episodic", "detail": why})
                continue
            sub, fmt = series_subtype(kind)
            t = series_text(text)
            cats = [c.strip() for c in CATEGORY.findall(text)]
            rec = base_record(d, "series")
            rec.update({"subtype": sub, "format": fmt, "info": info_of(params), "dorama": bool(any(DORAMA.search(c) for c in cats)),
                        "categories_n": len(cats), "inline_episode_rows": rows[:400], "inline_episode_row_count": len(rows),
                        "inline_sections": subs[:60], "has_episode_pages": base in base_with_pages, "ids": {},
                        "mixed_media": mixed, **t})
            if why:
                rec["programme_reason"] = why
            out[target].append(rec)
            continue
        epage = episode_page(d)
        if epage:
            out["episodes"].append(epage)
            stats["episode_pages"] += 1
            continue
        reason = "manga_or_other_animation" if kind.startswith("anim:") else "no_series_signal"
        out["excluded"].append({**base_record(d, "unknown"), "reason": reason, "kind": kind})
    for key in out:
        out[key].sort(key=lambda r: (r["page_id"], r["record_id"]))
    return out, stats


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def harvest_paths() -> list[Path]:
    return [p for p in (HARVEST, HARVEST_ANIMATION) if p.exists()]


def read_harvest():
    """Raw wikitext rows of the first harvest, then of the animation harvest (S1b) when it exists."""
    for path in harvest_paths():
        for line in gzip.open(path, "rt", encoding="utf-8"):
            yield json.loads(line)


def write_outputs(out: dict[str, list[dict]], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for key in FILES:
        path = out_dir / f"{key}.jsonl"
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in out[key]:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(tmp, path)
        files[key] = {"records": len(out[key]), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="only the first N harvested pages (tests)")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    started = time.monotonic()
    out, stats = process(read_harvest, limit=args.limit)
    files = write_outputs(out, args.out)
    harvest_summary = json.loads((HARVEST.parent / "harvest_summary.json").read_text())
    extra = HARVEST_ANIMATION.parent / "harvest_animation_summary.json"
    extra_summary = json.loads(extra.read_text()) if extra.exists() and HARVEST_ANIMATION.exists() else None
    manifest = {"schema_version": SCHEMA_VERSION, "source": {"harvest_sha256": harvest_summary["sha256"], "harvest_pages": harvest_summary["kept"],
                                                           "harvest_animation": {k: extra_summary[k] for k in ("kept", "sha256")} if extra_summary else None},
                "thresholds": {"plot_chars": PLOT_MIN_CHARS, "plot_words": PLOT_MIN_WORDS, "lead_chars": LEAD_MIN_CHARS,
                               "episode_chars": EPISODE_MIN_CHARS}, "files": files, "stats": dict(stats),
                "seconds": round(time.monotonic() - started, 1), "limit": args.limit}
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"files": {k: v["records"] for k, v in files.items()}, "stats": dict(stats), "seconds": manifest["seconds"]}, indent=1))


if __name__ == "__main__":
    main()
