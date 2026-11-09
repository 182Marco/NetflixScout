"""Quantify the TV-movie candidates (FictionTV `tipo fiction` = film TV) found by the Phase 0 scan.

    python -m pipelines.wikipedia_series.phase0.analyze_tv_movies
Offline, from data/phase0/full/harvest.jsonl.gz. Writes data/phase0/tv_movies_{per_page.jsonl,analysis.json}.
"""
from __future__ import annotations

import gzip
import json
import re
import statistics
from collections import Counter

from .. import tv_movies
from ..clean_plot import extract_plot
from ..common import DATA_DIR
from .analyze_series import HARVEST, PLOT_HEADINGS, kind_of, text_stats

OUT = DATA_DIR / "phase0"
RAI_RE = re.compile(r"\brai\b|rai ?(uno|due|tre|1|2|3|fiction)|mediaset|canale 5|rete ?4|italia 1", re.I)


def year_of(params: dict[str, str]) -> int | None:
    m = re.search(r"(1[89]\d\d|20\d\d)", tv_movies.clean_param(params.get("anno prima visione")))
    return int(m.group(1)) if m else None


def main() -> None:
    rows = []
    for line in gzip.open(HARVEST, "rt", encoding="utf-8"):
        d = json.loads(line)
        if d["ns"] != 0:
            continue
        kind, params = kind_of(d["text"])
        if kind != "fiction:film tv":
            continue
        stats = text_stats(d["text"])
        verdict = tv_movies.classify(params, d["text"], plot_chars=stats["plot_chars"],
                                     plot_words=stats["plot_words"], lead_chars=stats["lead_chars"])
        network = tv_movies.clean_param(params.get("rete tv")) + " " + tv_movies.clean_param(params.get("rete tv italiana"))
        rows.append({"id": d["id"], "title": d["title"], "year": year_of(params), **stats,
                     "class": verdict["class"], "reasons": verdict["reasons"], "evidence": verdict["evidence"],
                     "country": tv_movies.clean_param(params.get("paese")), "network": network.strip(),
                     "rai": bool(RAI_RE.search(network + " " + tv_movies.clean_param(params.get("casa produzione")))),
                     "has_original_title": bool(tv_movies.clean_param(params.get("titolo originale")))})
    (OUT / "tv_movies_per_page.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    by = Counter(r["class"] for r in rows)
    summary = {"candidates": len(rows), "classes": dict(by)}
    for cls in (tv_movies.NARRATIVE, tv_movies.NON_NARRATIVE, tv_movies.UNCERTAIN):
        rs = [r for r in rows if r["class"] == cls]
        summary[cls] = {
            "n": len(rs),
            "plot_ge_400_60": sum(1 for r in rs if r["plot_chars"] >= 400 and r["plot_words"] >= 60),
            "lead_ge_150": sum(1 for r in rs if r["lead_chars"] >= 150),
            "with_director": sum(1 for r in rs if r["evidence"]["director"]),
            "with_cast": sum(1 for r in rs if r["evidence"]["cast"]),
            "with_year": sum(1 for r in rs if r["year"]),
            "rai_or_mediaset": sum(1 for r in rs if r["rai"]),
            "top_reasons": Counter(x.split(":")[0] if x.startswith("genre") else x for r in rs for x in r["reasons"]).most_common(8),
            "top_genres": Counter(g for r in rs for g in r["evidence"]["genres"]).most_common(15),
            "plot_chars_median": statistics.median([r["plot_chars"] for r in rs]) if rs else 0,
        }
    summary["usable_text"] = {
        "narrative_with_plot_or_lead": sum(1 for r in rows if r["class"] == tv_movies.NARRATIVE
                                           and ((r["plot_chars"] >= 400 and r["plot_words"] >= 60) or r["lead_chars"] >= 150)),
        "narrative_without_any_text": sum(1 for r in rows if r["class"] == tv_movies.NARRATIVE
                                          and r["plot_chars"] < 400 and r["lead_chars"] < 150)}
    (OUT / "tv_movies_analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()}, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
