"""Render parity_report.json as a per-query markdown table (read-only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows = report["per_query"]
lines = [
    "| query | tipo | raw r@10 Chroma/Qdrant/ef128 | raw r@50 Chroma/Qdrant/ef128 | sem. pool = rif. (Chroma/Qdrant) | sem. overlap rif. (C/Q) | hyb. pool = rif. (C/Q) | rerank input uguale (sem/hyb) | excl. movie_id r@10 | anno r@10 |",
    "|---|---|---|---|---|---|---|---|---|---|",
]
for key, r in rows.items():
    raw, sem, hyb = r["raw"], r["pipeline"]["semantic"], r["pipeline"]["hybrid"]
    yn = lambda v: "si" if v else "NO"  # noqa: E731
    lines.append(
        f"| {key} | {r['kind']} | {raw['chroma']['recall10']:.1f}/{raw['qdrant_default']['recall10']:.1f}/{raw['qdrant_ef128']['recall10']:.1f}"
        f" | {raw['chroma']['recall50']:.2f}/{raw['qdrant_default']['recall50']:.2f}/{raw['qdrant_ef128']['recall50']:.2f}"
        f" | {yn(sem['same_as_reference']['chroma'])}/{yn(sem['same_as_reference']['qdrant'])}"
        f" | {sem['overlap_with_reference']['chroma']:.1f}/{sem['overlap_with_reference']['qdrant']:.1f}"
        f" | {yn(hyb['same_as_reference']['chroma'])}/{yn(hyb['same_as_reference']['qdrant'])}"
        f" | {yn(sem['rerank_input_sets_equal'])}/{yn(hyb['rerank_input_sets_equal'])}"
        f" | {r['exclusion_by_movie_id']['recall10']:.1f} | {r['year_range_filter']['recall10']:.1f} |")
sys.stdout.write("\n".join(lines) + "\n")
