"""Phase 0 analysis of season / episode-list pages from the harvested raw wikitext (offline).

For every "Episodi di ... (stagione)" page: episodes listed in the tables, episode sections that carry
prose (a plot), and the amount of text. Output: data/phase0/seasons_analysis.json (+ per-page jsonl).

    python -m pipelines.wikipedia_series.phase0.analyze_seasons
"""
from __future__ import annotations

import gzip
import json
import re
import statistics
from collections import Counter

from ..clean_plot import clean_wikitext
from ..common import DATA_DIR

HARVEST = DATA_DIR / "phase0" / "full" / "harvest.jsonl.gz"
HEAD = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
BOILER = re.compile(r"^(note|collegamenti esterni|altri progetti|voci correlate|bibliografia|dvd|home video|ascolti|"
                    r"riferimenti|edizioni home video|colonna sonora|trasmissione|critica|accoglienza|cast|personaggi)", re.I)
SEASON_TITLE = re.compile(r"^Episodi di .+ \(.+ stagione\)$")


def sections(text: str) -> list[dict]:
    marks = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip("' ")) for m in HEAD.finditer(text)]
    out = []
    for i, (_, end, level, title) in enumerate(marks):
        stop = len(text)
        for later in marks[i + 1:]:
            if later[2] <= level:
                stop = later[0]
                break
        out.append({"level": level, "title": title, "body": text[end:stop]})
    return out


def table_rows(text: str) -> int:
    """Data rows of the wikitables: a `|-` followed by a cell line (`|...`), not by a header (`!`) or
    the table end (`|}`)."""
    return len(re.findall(r"^\|-[^\n]*\n\s*\|(?![}\-+])", text, re.M))


def prose_chars(body: str) -> int:
    body = re.sub(r"^\{\|.*?^\|\}", "", body, flags=re.M | re.S)  # drop tables
    return len(clean_wikitext(body))


def analyze(text: str) -> dict:
    secs = sections(text)
    ep_secs = [s for s in secs if s["level"] == 2 and not BOILER.match(s["title"])]
    sized = [prose_chars(s["body"]) for s in ep_secs]
    return {"rows": table_rows(text), "ep_sections": len(ep_secs),
            "ep_sections_with_prose": sum(1 for n in sized if n >= 150), "prose_chars": sum(sized),
            "lead": len(clean_wikitext(text.split("{|", 1)[0][:4000]))}


def main() -> None:
    results = []
    for line in gzip.open(HARVEST, "rt", encoding="utf-8"):
        d = json.loads(line)
        if d["ns"] != 0 or not SEASON_TITLE.match(d["title"]):
            continue
        a = analyze(d["text"])
        a.update(id=d["id"], title=d["title"], len=len(d["text"]))
        results.append(a)
    with_rows = [r for r in results if r["rows"] > 0]
    summary = {
        "season_pages": len(results),
        "with_table_rows": len(with_rows),
        "episodes_listed_total": sum(r["rows"] for r in results),
        "pages_with_any_plot_section": sum(1 for r in results if r["ep_sections_with_prose"] > 0),
        "pages_where_most_episodes_have_plot": sum(1 for r in with_rows if r["ep_sections_with_prose"] >= 0.8 * r["rows"]),
        "episodes_with_plot_sections_total": sum(min(r["ep_sections_with_prose"], r["rows"]) for r in with_rows),
        "median_rows": statistics.median(r["rows"] for r in with_rows) if with_rows else 0,
        "median_prose_chars_when_plot": statistics.median([r["prose_chars"] for r in results if r["ep_sections_with_prose"]] or [0]),
        "rows_distribution": Counter(min(r["rows"], 30) // 5 * 5 for r in with_rows),
    }
    out = DATA_DIR / "phase0"
    (out / "seasons_per_page.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8")
    (out / "seasons_analysis.json").write_text(json.dumps(summary, indent=1, default=dict), encoding="utf-8")
    print(json.dumps(summary, indent=1, default=dict))


if __name__ == "__main__":
    main()
