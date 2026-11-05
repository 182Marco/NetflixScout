"""Phase S3: relations series -> seasons -> episodes, from S1 (Wikipedia) and S2 (Wikidata). Offline.

Sources of the parent of a season / episode-list page (independent evidence, compared, never merged blindly):
  torna_a   the `{{torna a|series}}` link written by the editors in the lead of the page
  title     "Episodi di NAME (n stagione)" -> NAME resolved against series titles (exact or unique base title)
  wikidata  P179 (part of the series) of the page's own entity, mapped back to a series page by QID
Status of a relation:
  verified_wikidata  Wikidata agrees with at least one Wikipedia source
  verified_wikipedia torna_a and title agree, Wikidata has no usable statement
  inferred           a single source
  conflict           sources point to different series -> `relation_review.jsonl`, no parent assigned
  orphan             nothing resolves -> no parent assigned
Nothing is invented: episodes get a number only from an exact title match with a table row; seasons without a
page become LOGICAL nodes (no text) only when the series page itself declares them (infobox count or inline
sections); every edge keeps its provenance. Corrections are applied from `review/overrides.json` (reversible,
see review/overrides.json) on top of the automatic result, never by editing S1/S2 files.

    python -m tool.RAGWikipediaSeries.build_relations
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .common import DATA_DIR, PACKAGE_DIR
from .phase0.build_units import ORD, season_number

S1, S2, OUT = DATA_DIR / "s1", DATA_DIR / "s2", DATA_DIR / "s3"
OVERRIDES = PACKAGE_DIR / "review" / "overrides.json"   # reviewer decisions: source, versioned in git (data/ is not)
REDIRECTS = DATA_DIR / "phase0" / "full" / "scan_redirects.jsonl"
SERIES_FILES = ("series", "uncertain")  # uncertain programmes can still be parents; they stay flagged
MAX_DECLARED_SEASONS = 60
ACCEPTED = ("verified_wikidata", "verified_wikipedia", "inferred", "reviewed")
LIST_TITLE = re.compile(r"^(?:Episodi|Lista degli episodi|Elenco degli episodi|Lista episodi)\s+(?:di|de|del|dei|della|degli|delle|dell'|d')\s*(.+?)$", re.I)
QUALIFIER = re.compile(r" \(([^()]+)\)$")


def norm(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def read(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8")] if path.exists() else []


class SeriesIndex:
    """Title / base-title / QID lookups over the series candidates (parents)."""

    def __init__(self, series: list[dict], redirects: dict[str, str], qid_of: dict[int, str]) -> None:
        self.by_title = {s["title"]: s for s in series}
        self.redirects = redirects
        self.by_base: dict[str, list[dict]] = defaultdict(list)
        for s in series:
            self.by_base[norm(QUALIFIER.sub("", s["title"]))].append(s)
        self.by_qid = {qid_of[s["page_id"]]: s for s in series if s["page_id"] in qid_of}

    def exact(self, title: str | None) -> dict | None:
        if not title:
            return None
        title = title.strip()
        if title in self.by_title:
            return self.by_title[title]
        target = self.redirects.get(title)
        return self.by_title.get(target) if target else None

    def by_name(self, name: str | None) -> tuple[dict | None, list[dict]]:
        """Unique series for a bare name; (None, candidates) when ambiguous, (None, []) when unknown."""
        if not name:
            return None, []
        hit = self.exact(name)
        if hit:
            return hit, []
        candidates = self.by_base.get(norm(name), [])
        return (candidates[0], []) if len(candidates) == 1 else (None, candidates)


def decide(sources: dict[str, dict | None]) -> tuple[str, dict | None, list[str]]:
    """status, parent, notes from the resolved parents of the three sources (None = source gave nothing)."""
    got = {k: v for k, v in sources.items() if v}
    notes: list[str] = []
    if not got:
        return "orphan", None, notes
    parents = {v["page_id"] for v in got.values()}
    if len(parents) > 1:
        wiki = {v["page_id"] for k, v in got.items() if k != "wikidata"}
        wd = got.get("wikidata")
        if wd and len(wiki) == 2 and wd["page_id"] in wiki:
            notes.append("wikidata_breaks_tie")
            return "verified_wikidata", wd, notes  # two Wikipedia sources disagree, the independent one sides with one
        if wd and len(wiki) == 1 and len(got) == 3:
            # torna_a and the title agree with each other and only Wikidata differs: two explicit Wikipedia
            # statements outweigh one Wikidata statement (seen: Archie Bunker's Place vs Arcibaldo, Doppia sentenza 1969 vs 1966)
            notes.append("wikidata_disagrees:" + str(wd["page_id"]))
            return "verified_wikipedia", got["torna_a"], notes
        return "conflict", None, notes
    parent = next(iter(got.values()))
    if "wikidata" in got and len(got) > 1:
        return "verified_wikidata", parent, notes
    if len(got) > 1:
        return "verified_wikipedia", parent, notes
    return "inferred", parent, ["single_source:" + next(iter(got))]


def episode_key(title: str) -> str:
    return norm(re.sub(r"^\d+\s*[.:\-–]?\s*", "", title or ""))


def match_rows(rows: list[dict], sections: list[dict]) -> dict[str, tuple[int, dict]]:
    """Episode section -> (row index, table row), ONLY by exact normalised title (italian or original), and
    only when that title identifies one row. No positional guess."""
    index: dict[str, dict[int, dict]] = defaultdict(dict)
    for i, row in enumerate(rows):
        for field in ("title_it", "title_original"):
            if row.get(field):
                index[episode_key(row[field])][i] = row
    out = {}
    for sec in sections:
        hits = index.get(episode_key(sec["title"]), {})
        if len(hits) == 1:
            out[sec["record_id"]] = next(iter(hits.items()))
    return out


def declared_seasons(info: dict) -> int | None:
    match = re.match(r"^\s*(\d{1,3})\b", str(info.get("stagioni", "")))
    value = int(match.group(1)) if match else None
    return value if value and value <= MAX_DECLARED_SEASONS else None


def ordinal_of(heading: str) -> int | None:
    low = heading.strip().lower()
    for word, number in ORD.items():
        if re.search(rf"\b{word}\b", low):
            return number
    match = re.search(r"\b(?:stagione|serie|parte)\s+(\d{1,2})\b|^(\d{1,2})\s*$|\b(\d{1,2})\s*[ªa°]?\s+stagione\b", low)
    return int(next(g for g in match.groups() if g)) if match else None


def load_overrides(path: Path = OVERRIDES) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"relations": {}}


def build(s1: Path, s2: Path, redirects_path: Path, overrides: dict) -> dict[str, list[dict]]:
    series = [r for f in SERIES_FILES for r in read(s1 / f"{f}.jsonl")]
    entities = {r["page_id"]: r for r in read(s2 / "wikidata_entities.jsonl")}
    qid_of = {pid: e["qid"] for pid, e in entities.items()}
    redirects = {}
    if redirects_path.exists():
        for row in read(redirects_path):
            if row.get("target"):
                redirects[row["title"]] = row["target"]
    index = SeriesIndex(series, redirects, qid_of)
    title_of = {s["page_id"]: s["title"] for s in series}
    relations, review = [], []
    resolved: dict[int, dict | None] = {}
    counts: Counter = Counter()

    def resolve_page(rec: dict, kind: str) -> dict:
        text_name = rec.get("series_name_from_title")
        if kind == "episode_list":
            m = LIST_TITLE.match(rec["title"])
            text_name = QUALIFIER.sub("", m.group(1)) if m else None
        back = index.exact(rec.get("torna_a"))
        by_title, ambiguous = index.by_name(text_name)
        ent = entities.get(rec["page_id"], {})
        wd_parent = None
        wd_unmapped = None
        for link in ent.get("part_of_series", []):
            wd_parent = index.by_qid.get(link["qid"])
            if not wd_parent:
                wd_unmapped = link["qid"]
            else:
                break
        pre_notes = []
        if back and by_title and back["page_id"] != by_title["page_id"] and QUALIFIER.search(back["title"]) and not QUALIFIER.search(by_title["title"]) \
                and norm(QUALIFIER.sub("", back["title"])) == norm(by_title["title"]):
            # The title of a season / list page never carries the disambiguating qualifier, so it cannot tell the
            # "(serie televisiva 2018)" page from the plain-name page: it is not evidence against the explicit link.
            by_title = None
            pre_notes.append("title_not_discriminating")
        status, parent, notes = decide({"torna_a": back, "title": by_title, "wikidata": wd_parent})
        notes = pre_notes + notes
        override = overrides.get("relations", {}).get(str(rec["page_id"]))
        if override:
            target = next((s for s in series if s["page_id"] == override["series_page_id"]), None)
            if target or override.get("series_page_id") is None:
                status, parent = "reviewed", target
                notes = notes + ["override:" + override.get("reason", "")]
        src = {"torna_a": back["page_id"] if back else None, "title": by_title["page_id"] if by_title else None,
               "wikidata": wd_parent["page_id"] if wd_parent else None}
        edge = {"child_record_id": rec["record_id"], "child_page_id": rec["page_id"], "child_title": rec["title"],
                "child_type": kind, "parent_page_id": parent["page_id"] if parent else None,
                "parent_title": parent["title"] if parent else None, "status": status, "sources": src, "notes": notes}
        if ambiguous:
            edge["title_ambiguous_among"] = [c["page_id"] for c in ambiguous[:5]]
        if wd_unmapped:
            edge["wikidata_parent_qid_outside_catalog"] = wd_unmapped
        # season number: title ordinal vs Wikidata ordinal
        if kind == "season":
            number = rec.get("season_number")
            ords = [l.get("ordinal") for l in ent.get("part_of_series", []) if l.get("ordinal")]
            wd_number = int(ords[0]) if ords and str(ords[0]).isdigit() else None
            edge["season_number"] = number if number is not None else wd_number
            edge["season_number_sources"] = {"title": number, "wikidata": wd_number}
            if number is not None and wd_number is not None and number != wd_number:
                edge["notes"] = notes + ["season_number_disagrees"]
        if status in ("conflict", "orphan") or ambiguous and status != "verified_wikidata":
            review.append({**{k: edge[k] for k in ("child_record_id", "child_page_id", "child_title", "child_type", "status", "sources")},
                           "torna_a": rec.get("torna_a"), "name_from_title": text_name,
                           "candidate_titles": {k: title_of.get(v) for k, v in src.items() if v}})
        return edge

    seasons = read(s1 / "seasons.jsonl")
    lists = read(s1 / "episode_lists.jsonl")
    for rec in seasons:
        edge = resolve_page(rec, "season")
        relations.append(edge)
        resolved[rec["page_id"]] = edge
    for rec in lists:
        edge = resolve_page(rec, "episode_list")
        relations.append(edge)
        resolved[rec["page_id"]] = edge
    # Second pass: a page whose `torna a` points to ANOTHER episode-list / season page ("Episodi di Naruto:
    # Shippuden" for each of its seasons) inherits the parent that page was resolved to. Only for pages that
    # nothing else resolved, never overriding a decision, and marked with the page it came through.
    by_page_title = {e["child_title"]: e for e in relations}
    for rec in seasons + lists:
        edge = resolved[rec["page_id"]]
        if edge["status"] != "orphan" or not rec.get("torna_a"):
            continue
        link = rec["torna_a"].strip()
        hub = by_page_title.get(redirects.get(link, link))
        if hub and hub is not edge and hub["parent_page_id"] and hub["status"] in ACCEPTED:
            edge.update({"parent_page_id": hub["parent_page_id"], "parent_title": hub["parent_title"], "status": "inferred",
                         "notes": edge["notes"] + ["via_list_page:" + hub["child_title"]]})
            review[:] = [r for r in review if r["child_record_id"] != edge["child_record_id"]]
    for edge in relations:
        counts[f"{edge['child_type']}_{edge['status']}"] += 1

    # Episodes: parent page is the season / list page they were read from; series follows that edge.
    rows_of = {r["page_id"]: r["table_rows"] for r in seasons + lists}
    sections_by_page: dict[int, list[dict]] = defaultdict(list)
    episode_links = []
    for ep in read(s1 / "episodes.jsonl"):
        if ep["source"] == "episode_page":
            continue
        sections_by_page[ep["parent_page_id"]].append(ep)
    matches: dict[str, dict] = {}
    for pid, secs in sections_by_page.items():
        matches.update(match_rows(rows_of.get(pid, []), secs))
    for pid, secs in sorted(sections_by_page.items()):
        edge = resolved.get(pid, {})
        for ep in secs:
            hit = matches.get(ep["record_id"])
            row = hit[1] if hit else None
            link = {"episode_record_id": ep["record_id"], "episode_title": ep["title"], "parent_page_id": pid,
                    "parent_kind": edge.get("child_type"), "season_number": edge.get("season_number"),
                    "series_page_id": edge.get("parent_page_id"), "series_status": edge.get("status"),
                    "episode_number": row.get("number_int") if row else None, "row_index": hit[0] if hit else None,
                    "numbering": "table_row_exact_title" if row and row.get("number_int") else "unknown"}
            episode_links.append(link)
            counts["episode_numbered" if link["episode_number"] else "episode_unnumbered"] += 1
            counts["episode_with_series" if link["series_page_id"] else "episode_without_series"] += 1
    # Autonomous episode pages ({{Episodio SerieTV}}): relation only from the infobox text, kept as a hint.
    for ep in read(s1 / "episodes.jsonl"):
        if ep["source"] == "episode_page":
            hint = (ep.get("params", {}).get("serie") or ep.get("params", {}).get("titolo serie") or "").strip()
            parent, _ = index.by_name(hint) if hint else (None, [])
            episode_links.append({"episode_record_id": ep["record_id"], "episode_title": ep["title"], "parent_page_id": None,
                                  "parent_kind": "episode_page", "season_number": digits(ep.get("params", {}).get("stagione")),
                                  "series_page_id": parent["page_id"] if parent else None,
                                  "series_status": "inferred" if parent else "orphan", "episode_number": digits(ep.get("params", {}).get("numero episodio") or ep.get("params", {}).get("episodio")),
                                  "numbering": "infobox", "infobox_series_hint": hint or None})
            counts["episode_page_with_series" if parent else "episode_page_without_series"] += 1

    # Logical seasons: only where the series page itself declares them and no season page exists for that number.
    have: dict[int, set[int]] = defaultdict(set)
    for edge in relations:
        if edge["child_type"] == "season" and edge["parent_page_id"] and edge.get("season_number"):
            have[edge["parent_page_id"]].add(edge["season_number"])
    logical = []
    for s in series:
        wanted: dict[int, dict] = {}
        for sec in s.get("inline_sections", []):
            number = ordinal_of(sec["heading"]) if sec.get("looks_like_season") else None
            if number and number not in have[s["page_id"]] and number not in wanted:
                wanted[number] = {"evidence": "series_page_section", "heading": sec["heading"], "text": sec["plot_text"], "text_chars": sec["plot_chars"]}
        declared = declared_seasons(s.get("info", {}))
        if declared:
            for number in range(1, declared + 1):
                if number not in have[s["page_id"]] and number not in wanted:
                    wanted[number] = {"evidence": "infobox_declared_count", "heading": None, "text": None, "text_chars": 0}
        for number, ev in sorted(wanted.items()):
            logical.append({"record_id": f"wp-{s['page_id']}#season{number}", "entity_type": "season", "logical": True,
                            "series_page_id": s["page_id"], "series_title": s["title"], "season_number": number,
                            "has_own_page": False, **ev})
            counts["logical_season_" + ev["evidence"]] += 1
    relations.sort(key=lambda e: (e["child_page_id"], e["child_record_id"]))
    return {"relations": relations, "episode_links": episode_links, "logical_seasons": logical, "relation_review": review,
            "_counts": [dict(counts)], "_series_total": [{"n": len(series)}]}


def digits(value) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def checks(result: dict[str, list[dict]]) -> dict:
    rel = result["relations"]
    per_series: dict[int, list[int]] = defaultdict(list)
    for e in rel:
        if e["child_type"] == "season" and e["parent_page_id"] and e.get("season_number"):
            per_series[e["parent_page_id"]].append(e["season_number"])
    duplicates = {sid: sorted(n for n, c in Counter(nums).items() if c > 1) for sid, nums in per_series.items()}
    duplicates = {k: v for k, v in duplicates.items() if v}
    gaps = {}
    for sid, nums in per_series.items():
        full = set(range(1, max(nums) + 1))
        missing = sorted(full - set(nums))
        if missing:
            gaps[sid] = missing
    child_ids = [e["child_record_id"] for e in rel]
    return {"series_with_season_pages": len(per_series), "series_with_duplicate_season_numbers": len(duplicates),
            "series_with_gaps_in_season_numbers": len(gaps), "duplicate_child_ids": len(child_ids) - len(set(child_ids)),
            "season_without_number": sum(1 for e in rel if e["child_type"] == "season" and not e.get("season_number")),
            "self_parent": sum(1 for e in rel if e["parent_page_id"] == e["child_page_id"]),
            "examples_duplicates": dict(list(duplicates.items())[:5]), "examples_gaps": dict(list(gaps.items())[:5])}


def write(result: dict[str, list[dict]], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for key, rows in result.items():
        if key.startswith("_"):
            continue
        path = out / f"{key}.jsonl"
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(tmp, path)
        files[key] = {"records": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return files


def main() -> None:
    result = build(S1, S2, REDIRECTS, load_overrides())
    files = write(result, OUT)
    report = {"counts": result["_counts"][0], "checks": checks(result), "files": files, "overrides_applied": len(load_overrides().get("relations", {}))}
    (OUT / "graph_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "checks": {k: v for k, v in report["checks"].items() if not k.startswith("examples")},
                      "files": {k: v["records"] for k, v in files.items()}}, indent=1))


if __name__ == "__main__":
    main()
