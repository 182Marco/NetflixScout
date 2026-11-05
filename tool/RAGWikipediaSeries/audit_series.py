"""Phase S4: audit of the S1-S3 catalogue. Offline, read-only on every input.

Writes data/s4/:
  audit.json          measured numbers (class agreement with Wikidata, duplicates, thin texts, relation quality)
  review_queue.jsonl  one row per record that needs a human/agent decision, with the evidence to decide
  sample.jsonl        stratified, seeded sample (same sample on every run) to re-read against the source
`overrides.json` (the decisions, see `apply_overrides` in build_clean.py) is written by the reviewer, never by
this script, so rerunning the audit cannot erase a decision.

    python -m tool.RAGWikipediaSeries.audit_series
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from .build_relations import norm, read
from .common import DATA_DIR

S1, S2, S3, OUT = DATA_DIR / "s1", DATA_DIR / "s2", DATA_DIR / "s3", DATA_DIR / "s4"
SEED = 20261105

SERIES_WORDS = ("television series", "miniseries", "web series", "anime series", "animated series", "television program",
                "telenovela", "soap opera", "sitcom", "drama", "animated television", "anime television", "ova", "ona",
                "television season", "reality", "talk show", "game show", "variety show", "documentary series", "tv series")
FILM_WORDS = ("film", "television film", "tv film", "movie", "short film", "animated film", "anime film")
OTHER_WORDS = ("manga", "comic", "novel", "book", "video game", "magazine", "character", "human", "person", "album", "song",
               "episode", "film series", "media franchise", "fictional", "light novel", "webcomic", "organization", "radio")


def family(label: str | None) -> str:
    low = (label or "").lower()
    if not low:
        return "unknown"
    if any(w in low for w in ("film series", "media franchise")):
        return "other"
    if "episode" in low and "series" not in low:
        return "other"
    if any(w in low for w in SERIES_WORDS):
        return "series"
    if any(low == w or low.endswith(" " + w) or w in low.split() for w in FILM_WORDS):
        return "film"
    if any(w in low for w in OTHER_WORDS):
        return "other"
    return "unknown"


def entity_families(entity: dict, labels: dict) -> list[str]:
    return sorted({family((labels.get(q) or {}).get("en")) for q in entity.get("instance_of", [])})


def text_hash(text: str) -> str:
    return hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()


def audit(s1: Path, s2: Path, s3: Path, harvests: list[Path] | None = None) -> tuple[dict, list[dict], list[dict]]:
    entities = {r["page_id"]: r for r in read(s2 / "wikidata_entities.jsonl")}
    labels = json.loads((s2 / "wikidata_classes.json").read_text()) if (s2 / "wikidata_classes.json").exists() else {}
    series, uncertain, movies = read(s1 / "series.jsonl"), read(s1 / "uncertain.jsonl"), read(s1 / "tv_movies.jsonl")
    review: list[dict] = []
    numbers: dict = {}

    # 1. class agreement between the infobox decision and Wikidata P31
    agree = Counter()
    for group, rows, expected in (("series", series, "series"), ("uncertain", uncertain, None), ("tv_movies", movies, "film")):
        for rec in rows:
            ent = entities.get(rec["page_id"])
            if not ent:
                agree[(group, "no_wikidata_entity")] += 1
                continue
            fams = entity_families(ent, labels)
            if not fams or fams == ["unknown"]:
                agree[(group, "no_usable_class")] += 1
                continue
            if expected and expected in fams:
                agree[(group, "agrees" + ("" if len(fams) == 1 else "_mixed"))] += 1
            elif expected and rec.get("mixed_media"):
                agree[(group, "explained_mixed_media:" + "+".join(fams))] += 1   # franchise page: the entity is the manga / game
            elif expected:
                agree[(group, "disagrees:" + "+".join(fams))] += 1
                review.append({"kind": "class_disagreement", "record_id": rec["record_id"], "page_id": rec["page_id"], "title": rec["title"],
                               "decided_as": group, "subtype": rec.get("subtype"), "wikidata_classes": [(labels.get(q) or {}).get("en") for q in ent.get("instance_of", [])],
                               "text_kind": rec.get("text_kind")})
            else:
                agree[(group, "families:" + "+".join(fams))] += 1
    numbers["class_agreement"] = {f"{g}/{k}": v for (g, k), v in sorted(agree.items())}

    # 2. duplicates: same QID on several pages, same normalised title, identical plot text
    by_qid: dict[str, list[dict]] = defaultdict(list)
    for rec in series + uncertain + movies:
        ent = entities.get(rec["page_id"])
        if ent:
            by_qid[ent["qid"]].append(rec)
    dup_qid = {q: rs for q, rs in by_qid.items() if len(rs) > 1}
    by_title: dict[str, list[dict]] = defaultdict(list)
    for rec in series:
        by_title[norm(re.sub(r" \([^)]*\)$", "", rec["title"]))].append(rec)
    dup_title = {t: rs for t, rs in by_title.items() if len(rs) > 1}
    by_text: dict[str, list[dict]] = defaultdict(list)
    for rec in series + movies:
        if rec.get("text_kind") == "plot":
            by_text[text_hash(rec["plot_text"])].append(rec)
    dup_text = {h: rs for h, rs in by_text.items() if len(rs) > 1}
    numbers["duplicates"] = {"same_qid": len(dup_qid), "same_base_title_series": len(dup_title), "identical_plot_text": len(dup_text)}
    for q, rs in dup_qid.items():
        review.append({"kind": "duplicate_qid", "qid": q, "pages": [{"page_id": r["page_id"], "title": r["title"], "subtype": r.get("subtype")} for r in rs]})
    for h, rs in dup_text.items():
        review.append({"kind": "identical_plot_text", "pages": [{"page_id": r["page_id"], "title": r["title"]} for r in rs]})

    # 3. text availability by type
    def text_stats(rows: list[dict]) -> dict:
        c = Counter(r.get("text_kind", "n/a") for r in rows)
        return {"n": len(rows), **dict(c)}
    numbers["text"] = {"series_by_subtype": {sub: text_stats([r for r in series if r["subtype"] == sub]) for sub in sorted({r["subtype"] for r in series})},
                       "tv_movies": text_stats(movies), "uncertain": text_stats(uncertain)}
    numbers["mixed_media_series"] = sum(1 for r in series if r.get("mixed_media"))
    if harvests:
        numbers["mixed_media_check"] = verify_mixed_flag(series, harvests)

    # 4. relations
    rel = read(s3 / "relations.jsonl")
    numbers["relations"] = {"by_status": dict(Counter((e["child_type"], e["status"]) .__str__() for e in rel))}
    for e in rel:
        if e["status"] in ("conflict", "orphan") or "season_number_disagrees" in e["notes"] or e.get("title_ambiguous_among"):
            review.append({"kind": "relation_" + e["status"], "child_record_id": e["child_record_id"], "child_page_id": e["child_page_id"],
                           "child_title": e["child_title"], "sources": e["sources"], "notes": e["notes"],
                           "season_number_sources": e.get("season_number_sources"), "ambiguous_among": e.get("title_ambiguous_among")})
    series_ids = {r["page_id"] for r in series}
    uncertain_ids = {r["page_id"] for r in uncertain}
    numbers["relations"]["seasons_under_uncertain_parent"] = sum(1 for e in rel if e["parent_page_id"] in uncertain_ids)
    numbers["relations"]["parents_not_in_series"] = sum(1 for e in rel if e["parent_page_id"] and e["parent_page_id"] not in series_ids | uncertain_ids)

    # 5. stratified, seeded sample for re-reading
    rng = random.Random(SEED)
    sample = []
    strata = [("series:" + sub, [r for r in series if r["subtype"] == sub], 12) for sub in sorted({r["subtype"] for r in series})]
    strata += [("tv_movie", movies, 25), ("uncertain", uncertain, 15), ("season", read(s1 / "seasons.jsonl"), 25),
               ("episode_list", read(s1 / "episode_lists.jsonl"), 12),
               ("episode", [e for e in read(s1 / "episodes.jsonl")], 30)]
    for name, rows, n in strata:
        for rec in rng.sample(rows, min(n, len(rows))):
            text = rec.get("plot_text") or rec.get("lead_text") or ""
            sample.append({"stratum": name, "record_id": rec["record_id"], "page_id": rec["page_id"], "title": rec["title"],
                           "url": rec.get("wikipedia_url"), "text_kind": rec.get("text_kind"), "info": rec.get("info"),
                           "text_head": " ".join(text.split())[:260]})
    numbers["review_queue"] = dict(Counter(r["kind"] for r in review))
    numbers["sample_size"] = len(sample)
    return numbers, review, sample


def write_jsonl(path: Path, rows: list[dict]) -> None:
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def main() -> None:
    from .extract_series import harvest_paths
    numbers, review, sample = audit(S1, S2, S3, harvest_paths())
    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT / "review_queue.jsonl", review)
    write_jsonl(OUT / "sample.jsonl", sample)
    (OUT / "audit.json").write_text(json.dumps(numbers, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(numbers, ensure_ascii=False, indent=1)[:5000])



# ------------------------------------------------------------------------------------------ mixed-media check
BOX = re.compile(r"\{\{\s*fumetto e animazione\s*(\|.*?)(?=\n\}\}|\Z)", re.I | re.S)
TIPO = re.compile(r"\|\s*tipo\s*=\s*([^\n|<]*)", re.I)
SOTTO = re.compile(r"\|\s*sottotipo\s*=\s*([^\n|<]*)", re.I)


def regex_infoboxes(text: str) -> list[tuple[str, str]]:
    """(tipo, sottotipo) of every `{{Fumetto e animazione}}` found WITHOUT the wikitext parser (independent check)."""
    out = []
    for chunk in re.split(r"(?i)\{\{\s*fumetto e animazione", text[:60000])[1:]:
        body = chunk.split("\n}}", 1)[0]
        t, s = TIPO.search(body), SOTTO.search(body)
        out.append(((t.group(1) if t else "").strip().lower(), (s.group(1) if s else "").strip().lower()))
    return out


def tv_box(tipo: str, sub: str) -> bool:
    return ("anime" in tipo or "cartone" in tipo) and any(x in sub for x in ("serie tv", "oav", "ona", "webserie"))


def verify_mixed_flag(series: list[dict], harvests: list[Path]) -> dict:
    """Recount the infoboxes of every anime / animated series page with a regex and compare with `mixed_media`."""
    want = {r["page_id"]: bool(r.get("mixed_media")) for r in series if r["subtype"] in ("anime", "animated_series")}
    agree = Counter()
    wrong: list[int] = []
    import gzip
    for path in harvests:
        for line in gzip.open(path, "rt", encoding="utf-8"):
            if '"ns":0' not in line[:60]:
                continue
            d = json.loads(line)
            if d["id"] not in want:
                continue
            boxes = regex_infoboxes(d["text"])
            has_other = any(not tv_box(t, s) for t, s in boxes) and any(tv_box(t, s) for t, s in boxes)
            ok = has_other == want[d["id"]]
            agree["confirmed" if ok else "mismatch"] += 1
            agree["flag_true" if want[d["id"]] else "flag_false"] += 1
            if not ok:
                wrong.append(d["id"])
    return {"checked": sum(v for k, v in agree.items() if k in ("confirmed", "mismatch")), **dict(agree), "mismatch_page_ids": wrong[:20]}


if __name__ == "__main__":
    main()
