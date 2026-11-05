"""Phase S5: the clean, versioned catalogue (series / seasons / episodes / TV movies) + manifest + verify.

Joins S1 (Wikipedia records), S2 (Wikidata ids) and S3 (relations), applies the reviewed decisions of
`review/overrides.json` and writes `data/s5/`. Nothing upstream is edited: dropping an override and
rebuilding restores the automatic result (reversible); `verify` rebuilds in a temporary folder and compares
every file byte for byte (reproducible).

    python -m tool.RAGWikipediaSeries.build_clean build
    python -m tool.RAGWikipediaSeries.build_clean verify

overrides.json:
  {"relations": {"<page_id>": {"series_page_id": int|null, "reason": str}},        (used by build_relations)
   "exclude":    {"<page_id>": {"reason": str}},                                  (record leaves the catalogue)
   "reclassify": {"<page_id>": {"to": "tv_movie"|"series", "reason": str}}}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from .audit_series import entity_families
from .build_relations import OVERRIDES, read
from .common import DATA_DIR

S1, S2, S3, S5 = DATA_DIR / "s1", DATA_DIR / "s2", DATA_DIR / "s3", DATA_DIR / "s5"
SCHEMA_VERSION = 1
FILES = ("series", "seasons", "episodes", "episodes_meta", "tv_movies", "uncertain", "excluded")
ACCEPTED_RELATION = ("verified_wikidata", "verified_wikipedia", "inferred", "reviewed")
SEASON_TEXT_MIN = 150


def load_overrides(path: Path = OVERRIDES) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"relations": data.get("relations", {}), "exclude": data.get("exclude", {}), "reclassify": data.get("reclassify", {}), "flag": data.get("flag", {})}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def split_list(value: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,;/]", value or "") if p.strip()]


def ids_of(entity: dict | None) -> dict:
    if not entity:
        return {"qid": None}
    out = {"qid": entity["qid"]}
    for key in ("imdb_id", "tvdb_id"):
        if entity.get(key):
            out[key] = entity[key]
    if entity.get("tmdb_tv_id"):
        out["tmdb_id"], out["tmdb_kind"] = entity["tmdb_tv_id"], "tv"
    if entity.get("tmdb_movie_id"):
        out["tmdb_id"], out["tmdb_kind"] = entity["tmdb_movie_id"], "movie"
    return out


def common_fields(rec: dict, entity: dict | None) -> dict:
    info = rec.get("info", {})
    original = info.get("titolo_originale") or ((entity or {}).get("original_title") or [None])[0]
    return {"record_id": rec["record_id"], "page_id": rec["page_id"], "title": rec["title"], "original_title": original,
            "year": info.get("year"), "year_end": info.get("year_end"), "country": split_list(info.get("paese")) + split_list(info.get("paese_2")),
            "genres": split_list(info.get("genere")) + split_list(info.get("genere_2")), "network": info.get("rete_tv"),
            "language": info.get("lingua_originale"), "ids": ids_of(entity), "wikipedia_url": rec["wikipedia_url"],
            "revision_id": rec["revision_id"], "wikidata_classes": (entity or {}).get("instance_of", [])}


def text_fields(rec: dict) -> dict:
    section = rec.get("plot_heading") if rec["text_kind"] == "plot" else ("introduzione" if rec["text_kind"] == "lead" else None)
    return {"text_provenance": {"source": "it.wikipedia page", "revision_id": rec["revision_id"], "section": section, "kind": rec["text_kind"]},
            "plot_heading": rec.get("plot_heading"), "text_kind": rec["text_kind"], "plot_text": rec["plot_text"], "lead_text": rec["lead_text"], "plot_chars": rec["plot_chars"],
            "lead_chars": rec["lead_chars"], "plot_flags": rec.get("plot_flags", [])}


def class_check(entity: dict | None, labels: dict, expected: str) -> str:
    """How the Wikidata class (P31) of the page's entity compares with the type decided from the infobox.
    Never changes the type: a disagreement is a flag (`wikidata_film`, `wikidata_other`, ...) for the filters."""
    if not entity:
        return "no_wikidata_entity"
    fams = [f for f in entity_families(entity, labels) if f != "unknown"]
    if not fams:
        return "unknown"
    if expected in fams:
        return "agrees"
    return "wikidata_" + "+".join(fams)


def build(s1: Path, s2: Path, s3: Path, overrides: dict) -> dict[str, list[dict]]:
    labels = json.loads((s2 / "wikidata_classes.json").read_text()) if (s2 / "wikidata_classes.json").exists() else {}
    entities = {r["page_id"]: r for r in read(s2 / "wikidata_entities.jsonl")}
    relations = {e["child_page_id"]: e for e in read(s3 / "relations.jsonl")}
    links = read(s3 / "episode_links.jsonl")
    logical = read(s3 / "logical_seasons.jsonl")
    out: dict[str, list[dict]] = {k: [] for k in FILES}
    removed = {int(k): v for k, v in overrides["exclude"].items()}
    reclass = {int(k): v for k, v in overrides["reclassify"].items()}
    flagged = {int(k): v for k, v in overrides.get("flag", {}).items()}

    def drop(rec: dict, reason: str, detail=None) -> None:
        out["excluded"].append({"record_id": rec["record_id"], "page_id": rec["page_id"], "title": rec["title"], "reason": reason, "detail": detail,
                                "origin": "s5_override" if reason.startswith("override") else "s1",
                                "original_classification": removed.get(rec["page_id"], {}).get("original")})

    for rec in read(s1 / "excluded.jsonl"):
        out["excluded"].append({"record_id": rec["record_id"], "page_id": rec["page_id"], "title": rec["title"], "reason": rec["reason"],
                                "detail": rec.get("detail", rec.get("kind")), "origin": "s1"})

    kept_series: dict[int, dict] = {}
    for source, target in (("series", "series"), ("tv_movies", "tv_movies"), ("uncertain", "uncertain")):
        for rec in read(s1 / f"{source}.jsonl"):
            pid = rec["page_id"]
            if pid in removed:
                drop(rec, "override_exclude", removed[pid].get("reason"))
                continue
            kind = {"tv_movie": "tv_movies", "series": "series"}[reclass[pid]["to"]] if pid in reclass else target
            mixed = bool(rec.get("mixed_media")) or (pid in flagged and flagged[pid]["flag"] == "mixed_media")
            ent = entities.get(pid)
            row = {"entity_type": "tv_movie" if kind == "tv_movies" else ("series" if kind == "series" else "uncertain"),
                   "subtype": "tv_movie" if kind == "tv_movies" else rec["subtype"], **common_fields(rec, ent), **text_fields(rec),
                   "class_check": class_check(ent, labels, "film" if kind == "tv_movies" else "series"),
                   "flags": sorted(({"mixed_media"} if mixed else set()) | ({"dorama"} if rec.get("dorama") else set())
                                   | ({"reclassified:" + reclass[pid]["to"]} if pid in reclass else set())
                                   | ({flagged[pid]["flag"]} if pid in flagged else set())
                                   | ({"programme"} if rec.get("subtype") == "programme" else set()))}
            if kind == "tv_movies":
                row.update({"director": rec.get("director") or rec.get("info", {}).get("regista"), "cast": rec.get("info", {}).get("cast"),
                            "has_text": rec["text_kind"] != "none", "classification": rec.get("classification"),
                            "series_id": None, "season_id": None, "parent_ids": []})
            else:
                row.update({"creators": rec.get("info", {}).get("ideatore"), "cast": rec.get("info", {}).get("cast"),
                            "declared_seasons": rec.get("info", {}).get("stagioni"), "declared_episodes": rec.get("info", {}).get("episodi"),
                            "inline_episode_row_count": rec.get("inline_episode_row_count", 0), "has_episode_pages": rec.get("has_episode_pages", False)})
            if pid in reclass:
                row["original_classification"] = reclass[pid].get("original")
            if pid in flagged:
                row["review_note"] = flagged[pid]["reason"]
            # Future retriever: default searches on anime / animated series use `default_search_eligible == True`; the mixed
            # manga+anime franchise pages stay in the catalogue and are returned only when the request asks for them.
            row["catalog_class"] = "franchise_page_mixed_media" if mixed else ("tv_movie" if kind == "tv_movies" else "series_page")
            row["default_search_eligible"] = not mixed
            row["ids_reliable"] = row["class_check"] == "agrees"   # a mismatching entity may describe the manga / game, not this work
            out[kind].append(row)
            if kind in ("series", "uncertain"):
                kept_series[pid] = row

    # seasons (pages) + logical seasons
    season_row: dict[int, dict] = {}
    for rec in read(s1 / "seasons.jsonl"):
        rel = relations.get(rec["page_id"], {})
        parent = rel.get("parent_page_id") if rel.get("status") in ACCEPTED_RELATION else None
        flags = []
        if parent and parent not in kept_series:
            flags.append("parent_excluded")
            parent = None
        text = rec["lead_text"]
        row = {"entity_type": "season", "subtype": "season_page", "record_id": rec["record_id"], "page_id": rec["page_id"], "title": rec["title"],
               "series_id": f"wp-{parent}" if parent else None, "series_title": kept_series[parent]["title"] if parent else rec.get("series_name_from_title"),
               "season_number": rel.get("season_number"), "season_number_sources": rel.get("season_number_sources"), "relation_status": rel.get("status"),
               "relation_sources": rel.get("sources"), "parent_ids": [f"wp-{parent}"] if parent else [], "logical": False,
               "text_kind": "season_intro" if len(text) >= SEASON_TEXT_MIN else "none", "lead_text": text, "lead_chars": len(text),
               "table_row_count": rec["table_row_count"], "episode_section_count": rec["episode_section_count"], "wikipedia_url": rec["wikipedia_url"],
               "revision_id": rec["revision_id"], "ids": ids_of(entities.get(rec["page_id"])), "flags": flags + (["season_number_disagrees"] if "season_number_disagrees" in rel.get("notes", []) else [])}
        out["seasons"].append(row)
        season_row[rec["page_id"]] = row
    for lg in logical:
        if lg["series_page_id"] not in kept_series:
            continue
        text = lg.get("text") or ""
        out["seasons"].append({"entity_type": "season", "subtype": "logical_season", "record_id": lg["record_id"], "page_id": lg["series_page_id"],
                               "title": f"{lg['series_title']} – stagione {lg['season_number']}", "series_id": f"wp-{lg['series_page_id']}",
                               "series_title": lg["series_title"], "season_number": lg["season_number"], "relation_status": "declared_by_series_page",
                               "parent_ids": [f"wp-{lg['series_page_id']}"], "logical": True, "evidence": lg["evidence"],
                               "text_kind": "series_section" if len(text) >= SEASON_TEXT_MIN else "none", "lead_text": text, "lead_chars": len(text),
                               "table_row_count": 0, "episode_section_count": 0, "wikipedia_url": None, "revision_id": None, "ids": {"qid": None}, "flags": ["logical"]})

    # episodes with text; their table row (if matched) gives number and date
    rows_of: dict[int, list[dict]] = {}
    for fname in ("seasons", "episode_lists"):
        for rec in read(s1 / f"{fname}.jsonl"):
            rows_of[rec["page_id"]] = rec["table_rows"]
    link_of = {l["episode_record_id"]: l for l in links}
    matched_rows: dict[int, set[int]] = defaultdict(set)
    for ep in read(s1 / "episodes.jsonl"):
        link = link_of.get(ep["record_id"], {})
        series_pid = link.get("series_page_id")
        flags = []
        if series_pid and series_pid not in kept_series:
            flags.append("parent_excluded")
            series_pid = None
        parent_page = ep.get("parent_page_id")
        row = None
        if link.get("row_index") is not None and parent_page in rows_of:
            row = rows_of[parent_page][link["row_index"]]
            matched_rows[parent_page].add(link["row_index"])
        season_page = parent_page if link.get("parent_kind") == "season" and parent_page in season_row else None
        entity = {"entity_type": "episode", "subtype": "episode_page" if ep["source"] == "episode_page" else "episode_section",
                  "record_id": ep["record_id"], "page_id": ep["page_id"], "title": ep["title"],
                  "series_id": f"wp-{series_pid}" if series_pid else None, "series_title": kept_series[series_pid]["title"] if series_pid else None,
                  "season_id": f"wp-{season_page}" if season_page else None, "season_number": link.get("season_number"),
                  "episode_number": link.get("episode_number"), "numbering": link.get("numbering", "unknown"),
                  "air_dates": (row or {}).get("dates", []), "title_original": (row or {}).get("title_original"), "title_it": (row or {}).get("title_it"),
                  "parent_ids": [i for i in (f"wp-{series_pid}" if series_pid else None, f"wp-{season_page}" if season_page else None) if i],
                  "relation_status": link.get("series_status"), "source": ep["source"], "parent_page_id": parent_page,
                  "text_kind": "plot", "plot_text": ep["plot_text"], "plot_chars": ep["plot_chars"], "wikipedia_url": ep["wikipedia_url"],
                  "revision_id": ep["revision_id"], "ids": ids_of(entities.get(ep["page_id"])) if ep["source"] == "episode_page" else {"qid": None},
                  "flags": flags}
        out["episodes"].append(entity)

    # metadata-only episodes: table rows with number and a title, not already carried by an episode with text
    for fname in ("seasons", "episode_lists"):
        for rec in read(s1 / f"{fname}.jsonl"):
            rel = relations.get(rec["page_id"], {})
            parent = rel.get("parent_page_id") if rel.get("status") in ACCEPTED_RELATION else None
            if parent not in kept_series:
                parent = None
            season = rec["page_id"] if fname == "seasons" else None
            for i, r in enumerate(rec["table_rows"]):
                if i in matched_rows[rec["page_id"]] or r.get("partial") or not r.get("number_int") or not (r.get("title_it") or r.get("title_original")):
                    continue
                out["episodes_meta"].append({"entity_type": "episode", "subtype": "episode_row", "record_id": f"wp-{rec['page_id']}#r{i}",
                                             "page_id": rec["page_id"], "title": r.get("title_it") or r.get("title_original"), "title_original": r.get("title_original"),
                                             "title_it": r.get("title_it"), "series_id": f"wp-{parent}" if parent else None,
                                             "season_id": f"wp-{season}" if season in season_row and parent else None,
                                             "season_number": rel.get("season_number") if fname == "seasons" else None,
                                             "episode_number": r["number_int"], "air_dates": r.get("dates", []), "parent_page_id": rec["page_id"],
                                             "text_kind": "none", "source": "table_row", "relation_status": rel.get("status"), "flags": ["metadata_only"]})
    # Identical plot text on several works (e.g. the TV films of one novel all carry the novel's synopsis): a flag,
    # never a removal; the vector of such records says little about the individual work.
    groups: dict[str, list[dict]] = defaultdict(list)
    for key in ("series", "tv_movies", "uncertain"):
        for row in out[key]:
            if row["text_kind"] == "plot":
                groups[hashlib.sha1(" ".join(row["plot_text"].lower().split()).encode()).hexdigest()].append(row)
    for rows in groups.values():
        if len(rows) > 1:
            for row in rows:
                row["flags"] = sorted(set(row["flags"]) | {"duplicate_plot_text"})
                row["plot_text_shared_by"] = len(rows)
    for key in out:
        out[key].sort(key=lambda r: (r["page_id"], r["record_id"]))
    return out


def report(out: dict[str, list[dict]]) -> dict:
    series, seasons, episodes = out["series"], out["seasons"], out["episodes"]
    parents = Counter()
    for s in seasons:
        parents[("logical" if s["logical"] else "page", "with_series" if s["series_id"] else "no_series")] += 1
    return {"counts": {k: len(v) for k, v in out.items()},
            "series": {"by_class_check": dict(Counter(s["class_check"] for s in series)), "by_subtype": dict(Counter(s["subtype"] for s in series)), "by_text_kind": dict(Counter(s["text_kind"] for s in series)),
                       "with_imdb": sum(1 for s in series if s["ids"].get("imdb_id")), "with_qid": sum(1 for s in series if s["ids"].get("qid")),
                       "duplicate_plot_text": sum(1 for s in series if "duplicate_plot_text" in s["flags"]), "ids_unreliable": sum(1 for s in series if not s["ids_reliable"])},
            "seasons": {"by_kind_parent": {f"{a}/{b}": n for (a, b), n in sorted(parents.items())}, "by_text_kind": dict(Counter(s["text_kind"] for s in seasons))},
            "episodes": {"with_text": len(episodes), "with_series": sum(1 for e in episodes if e["series_id"]), "with_season": sum(1 for e in episodes if e["season_id"]),
                         "numbered": sum(1 for e in episodes if e["episode_number"]), "metadata_only_rows": len(out["episodes_meta"])},
            "tv_movies": {"n": len(out["tv_movies"]), "by_text_kind": dict(Counter(m["text_kind"] for m in out["tv_movies"])),
                          "with_imdb": sum(1 for m in out["tv_movies"] if m["ids"].get("imdb_id")), "with_tmdb": sum(1 for m in out["tv_movies"] if m["ids"].get("tmdb_id")),
                          "without_tmdb_kept": sum(1 for m in out["tv_movies"] if not m["ids"].get("tmdb_id"))},
            "excluded_by_reason": dict(Counter(e["reason"] for e in out["excluded"]))}


def write(out: dict[str, list[dict]], directory: Path, overrides_path: Path = OVERRIDES) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for key in FILES:
        path = directory / f"{key}.jsonl"
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in out[key]:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(tmp, path)
        files[key] = {"records": len(out[key]), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    (directory / "catalog_report.json").write_text(json.dumps(report(out), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    upstream = {}
    for label, folder, names in (("s1", S1, FILES_S1), ("s2", S2, ("wikidata_entities.jsonl", "wikidata_classes.json")), ("s3", S3, FILES_S3)):
        upstream[label] = {n: sha256_file(folder / n) for n in names if (folder / n).exists()}
    manifest = {"schema_version": SCHEMA_VERSION, "files": files, "upstream_sha256": upstream,
                "overrides_sha256": sha256_file(overrides_path) if overrides_path.exists() else None}
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


FILES_S1 = ("series.jsonl", "seasons.jsonl", "episodes.jsonl", "episode_lists.jsonl", "tv_movies.jsonl", "uncertain.jsonl", "excluded.jsonl")
FILES_S3 = ("relations.jsonl", "episode_links.jsonl", "logical_seasons.jsonl")


def verify(directory: Path = S5) -> list[str]:
    """Rebuild into a temporary folder and compare every file byte for byte; also check the upstream hashes."""
    problems: list[str] = []
    manifest = json.loads((directory / "manifest.json").read_text())
    for label, folder in (("s1", S1), ("s2", S2), ("s3", S3)):
        for name, digest in manifest["upstream_sha256"].get(label, {}).items():
            if not (folder / name).exists() or sha256_file(folder / name) != digest:
                problems.append(f"upstream changed: {label}/{name}")
    overrides = load_overrides()
    path = OVERRIDES
    if (sha256_file(path) if path.exists() else None) != manifest["overrides_sha256"]:
        problems.append("overrides.json changed since the build")
    with tempfile.TemporaryDirectory() as tmp:
        again = write(build(S1, S2, S3, overrides), Path(tmp))
        for key, info in manifest["files"].items():
            if again["files"][key]["sha256"] != info["sha256"]:
                problems.append(f"{key}.jsonl differs from a fresh rebuild")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify"])
    args = parser.parse_args()
    if args.command == "build":
        manifest = write(build(S1, S2, S3, load_overrides()), S5)
        print(json.dumps({k: v["records"] for k, v in manifest["files"].items()}, indent=1))
        print(json.dumps(json.loads((S5 / "catalog_report.json").read_text()), ensure_ascii=False, indent=1)[:3500])
    else:
        problems = verify()
        print("VERIFY OK: byte-identical rebuild" if not problems else "VERIFY FAILED:\n" + "\n".join(problems))
        sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
