"""Copy the small, synthetic result files of every phase into `reports/` (tracked by git).

`data/` is ignored by git (large, regenerable); these few JSON files are the measured record of each phase:
manifests with hashes, audit and graph reports, catalogue report, embedding-cost manifest, Phase 0 analyses.
Idempotent and byte-for-byte copies; never touches the sources.

    python -m tool.RAGWikipediaSeries.publish_reports
"""
from __future__ import annotations

import shutil

from .common import DATA_DIR, PACKAGE_DIR

REPORTS = PACKAGE_DIR / "reports"
COPIES = {
    "phase0/full/scan_summary.json": "phase0_scan_summary.json", "phase0/full/harvest_summary.json": "phase0_harvest_summary.json",
    "phase0/full/harvest_animation_summary.json": "s1b_harvest_animation_summary.json", "phase0/series_analysis.json": "phase0_series_analysis.json",
    "phase0/seasons_analysis.json": "phase0_seasons_analysis.json", "phase0/relations_analysis.json": "phase0_relations_analysis.json",
    "phase0/bench_lexical.json": "phase0_bench_lexical.json", "phase0/cost_estimate.json": "phase0_cost_estimate.json",
    "phase0/tv_movies_analysis.json": "phase0_tv_movies_analysis.json", "s1/manifest.json": "s1_manifest.json", "s2/manifest.json": "s2_manifest.json",
    "s3/graph_report.json": "s3_graph_report.json", "s4/audit.json": "s4_audit.json", "s5/manifest.json": "s5_manifest.json",
    "s5/catalog_report.json": "s5_catalog_report.json", "s6/embedding_manifest.json": "s6_embedding_manifest.json",
}


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    for source, name in COPIES.items():
        path = DATA_DIR / source
        if path.exists():
            shutil.copyfile(path, REPORTS / name)
            print(f"{name}  {path.stat().st_size} bytes")
        else:
            print(f"missing (phase not run): {source}")


if __name__ == "__main__":
    main()
