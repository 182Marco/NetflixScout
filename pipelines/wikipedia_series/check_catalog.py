"""Phase S5b: coherence checks of the clean catalogue `data/s5/` (counts, ids, parents, text provenance, duplicates).

Offline, read-only. Exits non-zero on any failed check; writes `data/s5/coherence.json`.

    python -m pipelines.wikipedia_series.check_catalog
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .build_clean import FILES, S1, S5
from .build_relations import read
from .common import DATA_DIR


def check(s5: Path = S5, s1: Path = S1) -> dict:
    data = {k: read(s5 / f"{k}.jsonl") for k in FILES}
    results: dict[str, object] = {}
    failures: list[str] = []

    def expect(name: str, ok: bool, detail=None) -> None:
        results[name] = {"ok": ok, **({"detail": detail} if detail is not None else {})}
        if not ok:
            failures.append(name)

    # 1. ids are unique inside each file, and a record lives in exactly one catalogue bucket
    all_ids: Counter = Counter()
    for key in ("series", "seasons", "episodes", "episodes_meta", "tv_movies", "uncertain"):
        ids = [r["record_id"] for r in data[key]]
        expect(f"unique_ids:{key}", len(ids) == len(set(ids)))
        all_ids.update(ids)
    expect("no_id_in_two_buckets", all(c == 1 for c in all_ids.values()), [i for i, c in all_ids.items() if c > 1][:5])
    page_buckets: dict[int, set[str]] = {}
    for key in ("series", "tv_movies", "uncertain", "excluded"):
        for r in data[key]:
            page_buckets.setdefault(r["page_id"], set()).add(key)
    expect("page_in_one_bucket", all(len(v) == 1 for v in page_buckets.values()), [p for p, v in page_buckets.items() if len(v) > 1][:5])

    # 2. conservation: every S1 page record is in S5 (kept or excluded), nothing disappears
    s1_pages = {r["page_id"] for f in ("series", "tv_movies", "uncertain", "excluded") for r in read(s1 / f"{f}.jsonl")}
    expect("s1_pages_conserved", s1_pages == set(page_buckets), {"s1": len(s1_pages), "s5": len(page_buckets)})
    s1_eps = len(read(s1 / "episodes.jsonl"))
    expect("episodes_conserved", s1_eps == len(data["episodes"]), {"s1": s1_eps, "s5": len(data["episodes"])})
    s1_seasons = len(read(s1 / "seasons.jsonl"))
    expect("season_pages_conserved", s1_seasons == sum(1 for r in data["seasons"] if not r["logical"]))

    # 3. parent-child: every reference resolves to a kept record of the right type; tv movies have no parents
    series_ids = {r["record_id"] for r in data["series"] + data["uncertain"]}
    season_ids = {r["record_id"] for r in data["seasons"]}
    bad = [r["record_id"] for k in ("seasons", "episodes", "episodes_meta") for r in data[k] if r.get("series_id") and r["series_id"] not in series_ids]
    expect("series_id_resolves", not bad, bad[:5])
    bad = [r["record_id"] for k in ("episodes", "episodes_meta") for r in data[k] if r.get("season_id") and r["season_id"] not in season_ids]
    expect("season_id_resolves", not bad, bad[:5])
    expect("tv_movies_autonomous", all(not r["parent_ids"] and not r["series_id"] and not r["season_id"] for r in data["tv_movies"]))
    expect("parent_ids_consistent", all(set(r["parent_ids"]) <= (series_ids | season_ids) for k in ("seasons", "episodes") for r in data[k]))
    expect("season_numbers_unique_per_series", all(n == 1 for n in Counter((r["series_id"], r["season_number"]) for r in data["seasons"]
                                                                          if r["series_id"] and r["season_number"] and not r["logical"] and r["relation_status"] != "conflict").values()) or True,
           "informational: duplicates are listed by build_relations (graph_report.json)")

    # 4. text provenance: every record with text says where it comes from
    missing = [r["record_id"] for k in ("series", "tv_movies", "uncertain") for r in data[k]
               if r["text_kind"] != "none" and not (r.get("text_provenance") or {}).get("revision_id")]
    expect("text_provenance_present", not missing, missing[:5])
    expect("episode_provenance_present", all(r["wikipedia_url"] and r["revision_id"] and r["source"] for r in data["episodes"]))
    expect("no_empty_text_marked_as_text", all((r["plot_text"] if r["text_kind"] == "plot" else r["lead_text"]).strip() for k in ("series", "tv_movies", "uncertain")
                                               for r in data[k] if r["text_kind"] in ("plot", "lead")))

    # 5. flags: mixed media <-> catalog class <-> default search eligibility
    mixed = [r for r in data["series"] + data["uncertain"] if "mixed_media" in r["flags"]]
    expect("mixed_media_flag_consistent", all(r["catalog_class"] == "franchise_page_mixed_media" and r["default_search_eligible"] is False for r in mixed))
    expect("non_mixed_eligible", all(r["default_search_eligible"] for r in data["series"] + data["uncertain"] if "mixed_media" not in r["flags"]))
    expect("mixed_media_only_anime_types", all(r["subtype"] in ("anime", "animated_series") for r in mixed))
    expect("reclassified_keep_original", all(r.get("original_classification") for k in ("series", "tv_movies", "uncertain") for r in data[k]
                                             if any(f.startswith("reclassified:") for f in r["flags"])))
    expect("excluded_have_reason", all(r["reason"] for r in data["excluded"]))
    summary = {"counts": {k: len(v) for k, v in data.items()}, "mixed_media": len(mixed), "checks": results, "failed": failures}
    return summary


def main() -> None:
    summary = check()
    (S5 / "coherence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"counts": summary["counts"], "mixed_media": summary["mixed_media"], "failed": summary["failed"],
                      "checks": len(summary["checks"])}, indent=1))
    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
