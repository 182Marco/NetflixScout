"""Phase 0: PREVIEW of the hierarchical units (series / season / episode) from the harvested wikitext.

Not the final dataset: it measures how many units exist, how their text looks and how reliably a
season can be tied to its series. Relation sources measured here:
  - `{{torna a|<series page>}}` in the lead of the season page (explicit link written by editors);
  - the title "Episodi di NAME (n stagione)" resolved against series titles (fallback, may be ambiguous).
Output: data/phase0/units_preview.jsonl and data/phase0/relations_analysis.json

    python -m tool.RAGWikipediaSeries.phase0.build_units
"""
from __future__ import annotations

import gzip
import json
import re
from collections import Counter, defaultdict

from ..clean_plot import clean_wikitext, extract_plot
from ..common import DATA_DIR
from .analyze_seasons import BOILER, SEASON_TITLE, sections
from .analyze_series import HARVEST, PLOT_HEADINGS, kind_of, text_stats

BACK = re.compile(r"\{\{\s*torna a\s*\|\s*([^|}]+?)\s*(?:\|[^}]*)?\}\}", re.I)
TITLE = re.compile(r"^Episodi di (.+) \(([^()]+ stagione)\)$")
ORD = {"prima": 1, "seconda": 2, "terza": 3, "quarta": 4, "quinta": 5, "sesta": 6, "settima": 7, "ottava": 8,
       "nona": 9, "decima": 10, "undicesima": 11, "dodicesima": 12, "tredicesima": 13, "quattordicesima": 14,
       "quindicesima": 15, "sedicesima": 16, "diciassettesima": 17, "diciottesima": 18, "diciannovesima": 19,
       "ventesima": 20}


def is_series_kind(kind: str) -> bool:
    if kind.startswith("fiction:"):
        return kind.split(":")[1].startswith(("serie", "miniserie", "serial", "webserie"))
    if kind.startswith("anim:"):
        return any(x in kind for x in ("serie tv", "oav", "ona", "webserie")) and ("anime" in kind or "cartone" in kind)
    return kind == "programma"


def season_number(qualifier: str) -> int | None:
    word = qualifier.split()[0].lower()
    return ORD.get(word) or (int(word) if word.isdigit() else None)


def main() -> None:
    series, seasons_raw = {}, []
    for line in gzip.open(HARVEST, "rt", encoding="utf-8"):
        d = json.loads(line)
        if d["ns"] != 0:
            continue
        if SEASON_TITLE.match(d["title"]):
            seasons_raw.append(d)
            continue
        kind, _ = kind_of(d["text"])
        if is_series_kind(kind):
            stats = text_stats(d["text"])
            series[d["title"]] = {"id": d["id"], "title": d["title"], "kind": kind, "stats": stats, "text": d["text"]}
    redirects = {}
    for l in open(DATA_DIR / "phase0" / "full" / "scan_redirects.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["target"]:
            redirects[r["title"]] = r["target"]
    base = defaultdict(list)
    for t in series:
        base[re.sub(r" \([^)]*\)$", "", t)].append(t)

    def resolve(name: str) -> tuple[str, str | None]:
        if name in series:
            return "exact", name
        if name in redirects and redirects[name] in series:
            return "redirect", redirects[name]
        return "none", None

    rel = Counter()
    units = []
    texts: dict = {}
    for t, s in series.items():
        st = s["stats"]
        text_chars = max(st["plot_chars"], st["lead_chars"])
        plot = extract_plot(s["text"], headings=PLOT_HEADINGS, min_chars=0, min_words=0).text or ""
        lead_text = clean_wikitext(s["text"].split("\n==", 1)[0][:6000]) if not plot else ""
        texts[s["id"]] = plot if len(plot) >= 400 else (plot + "\n" + lead_text).strip()
        units.append({"level": "series", "id": s["id"], "series_id": s["id"], "title": t, "kind": s["kind"],
                      "plot_chars": st["plot_chars"], "lead_chars": st["lead_chars"], "usable": text_chars >= 400})
    for d in seasons_raw:
        text = d["text"]
        m = BACK.search(text[:1500])
        t = TITLE.match(d["title"])
        name, qual = (t.group(1), t.group(2)) if t else (None, None)
        how, parent = ("none", None)
        if m:
            rel["has_torna_a"] += 1
            how, parent = resolve(m.group(1))
            rel[f"torna_a_{how}"] += 1
        by_title = None
        if name:
            h2, p2 = resolve(name)
            cands = [name] if h2 != "none" else base.get(name, [])
            by_title = cands[0] if len(cands) == 1 else None
            rel["title_resolves_uniquely" if by_title else ("title_ambiguous" if len(cands) > 1 else "title_none")] += 1
        if parent and by_title:
            rel["both_sources"] += 1
            rel["sources_agree" if parent == by_title else "sources_disagree"] += 1
        final = parent or by_title
        rel["season_with_parent" if final else "season_orphan"] += 1
        head = text.split("{|", 1)[0]
        lead = clean_wikitext(head[:4000])
        sid = series[final]["id"] if final else None
        texts[d["id"]] = lead
        units.append({"level": "season", "id": d["id"], "series_id": sid, "title": d["title"], "season_no": season_number(qual or ""),
                      "parent_source": "torna_a" if parent else ("title" if by_title else None), "lead_chars": len(lead), "usable": len(lead) >= 150})
        for sec in sections(text):
            if sec["level"] == 2 and not BOILER.match(sec["title"]):
                body = re.sub(r"^\{\|.*?^\|\}", "", sec["body"], flags=re.M | re.S)
                prose = clean_wikitext(body)
                if len(prose) >= 150:
                    uid = f"{d['id']}#{len(units)}"
                    texts[uid] = prose
                    units.append({"level": "episode", "id": uid, "season_id": d["id"], "series_id": sid,
                                  "title": sec["title"], "chars": len(prose), "usable": True})
    out = DATA_DIR / "phase0"
    (out / "units_preview.jsonl").write_text("\n".join(json.dumps(u, ensure_ascii=False) for u in units), encoding="utf-8")
    with gzip.open(out / "units_text.jsonl.gz", "wt", encoding="utf-8") as fh:
        for uid, text in texts.items():
            fh.write(json.dumps({"id": uid, "text": text}, ensure_ascii=False) + "\n")
    lv = Counter(u["level"] for u in units)
    usable = Counter(u["level"] for u in units if u["usable"])
    ep = [u for u in units if u["level"] == "episode"]
    summary = {"units": dict(lv), "usable": dict(usable), "relations": dict(rel),
               "episodes_with_known_series": sum(1 for u in ep if u["series_id"]),
               "series_with_at_least_one_season_page": len({u["series_id"] for u in units if u["level"] == "season" and u["series_id"]}),
               "series_with_at_least_one_episode_text": len({u["series_id"] for u in ep if u["series_id"]})}
    (out / "relations_analysis.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
