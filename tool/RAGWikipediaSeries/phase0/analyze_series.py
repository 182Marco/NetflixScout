"""Phase 0 analysis of series pages (plot / lead coverage), offline, from the harvested wikitext.

Series kinds come from infobox parameters (measured in the scan): FictionTV `tipo fiction`
(serie tv / miniserie tv / serial tv / webserie are series; film tv is a TV FILM), `Fumetto e
animazione` (`tipo` anime / cartone with `sottotipo` serie tv / oav / ona / webserie), and `Programma`.

    python -m tool.RAGWikipediaSeries.phase0.analyze_series
"""
from __future__ import annotations

import gzip
import json
import re
import statistics
from collections import Counter, defaultdict

import mwparserfromhell

from ..clean_plot import clean_wikitext, extract_plot
from ..common import DATA_DIR
from .scan_dump import infobox_params, normalize_template

HARVEST = DATA_DIR / "phase0" / "full" / "harvest.jsonl.gz"
PLOT_HEADINGS = ["trama", "plot", "sinossi", "premessa", "soggetto", "riassunto", "storia", "argomento",
                 "la trama", "descrizione", "il programma"]
FICTION_SERIES = ("serie", "miniserie", "serial", "webserie")


def kind_of(text: str) -> tuple[str, dict]:
    head = text[:60000]
    low = head.lower()
    if "{{fictiontv" in low.replace(" ", ""):
        p = infobox_params(head, "fictiontv")
        t = p.get("tipo fiction", "").lower()
        t = re.sub(r"<!--.*", "", t).strip()
        return ("fiction:" + (t or "?")), p
    if re.search(r"\{\{\s*fumetto e animazione", low):
        p = infobox_params(head, "fumetto e animazione")
        t, s = p.get("tipo", "").lower(), p.get("sottotipo", "").lower()
        return (f"anim:{t}/{re.sub(r'<!--.*', '', s).strip() or '?'}"), p
    if re.search(r"\{\{\s*programma\s*[|\n]", low):
        return "programma", infobox_params(head, "programma")
    return "other", {}


def text_stats(text: str) -> dict:
    code = mwparserfromhell.parse(text)
    lead = clean_wikitext(code.get_sections(include_lead=True, flat=True)[0]) if code.get_sections() else ""
    plot = extract_plot(text, headings=PLOT_HEADINGS, min_chars=0, min_words=0)
    ptxt = plot.text or ""
    return {"lead_chars": len(lead), "plot_chars": len(ptxt), "plot_words": len(ptxt.split()),
            "plot_heading": plot.heading, "plot_flags": plot.flags}


def main() -> None:
    per = []
    for line in gzip.open(HARVEST, "rt", encoding="utf-8"):
        d = json.loads(line)
        if d["ns"] != 0:
            continue
        kind, params = kind_of(d["text"])
        if kind == "other":
            continue
        row = {"id": d["id"], "title": d["title"], "kind": kind, "len": len(d["text"])}
        row.update(text_stats(d["text"]))
        row["seasons_declared"] = params.get("stagioni") or params.get("numero stagioni")
        per.append(row)
    out = DATA_DIR / "phase0"
    (out / "series_per_page.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in per), encoding="utf-8")
    by = defaultdict(list)
    for r in per:
        k = r["kind"]
        group = ("fiction_series" if k.startswith("fiction:") and k.split(":")[1].startswith(FICTION_SERIES)
                 else "fiction_tv_film" if k == "fiction:film tv" else "animated_series" if k.startswith("anim:") and
                 any(x in k for x in ("serie tv", "oav", "ona", "webserie")) and ("anime" in k or "cartone" in k)
                 else "programma" if k == "programma" else "other_kind")
        by[group].append(r)
    summary = {"kinds": Counter(r["kind"] for r in per).most_common(30), "groups": {}}
    for g, rs in by.items():
        plots = [r["plot_chars"] for r in rs]
        leads = [r["lead_chars"] for r in rs]
        best = [max(a, b) for a, b in zip(plots, leads)]
        summary["groups"][g] = {
            "n": len(rs),
            "plot>=400chars&60words": sum(1 for r in rs if r["plot_chars"] >= 400 and r["plot_words"] >= 60),
            "plot>0": sum(1 for x in plots if x > 0),
            "lead>=400chars": sum(1 for x in leads if x >= 400),
            "plot_or_lead>=400": sum(1 for x in best if x >= 400),
            "none(<150)": sum(1 for x in best if x < 150),
            "median_plot_chars_when_present": statistics.median([x for x in plots if x > 0] or [0]),
            "p90_plot_chars": sorted(plots)[int(len(plots) * 0.9)] if plots else 0,
            "plot_over_32000chars(>~8k tokens)": sum(1 for x in plots if x > 32000),
        }
    (out / "series_analysis.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
