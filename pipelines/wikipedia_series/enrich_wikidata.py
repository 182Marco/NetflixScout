"""Phase S2: Wikidata enrichment of the S1 catalogue (QIDs, classes, relations, external ids, dates).

Reads data/s1/*.jsonl, asks the PUBLIC Wikidata API (`wbgetentities`, free, no key) for the entity linked
to each Italian-Wikipedia page title (batches of 50), keeps every response in the own snapshot
(`data/cache/wikidata/<snapshot_id>`, append-only, resumable: a rerun asks the network only for what the
snapshot does not hold) and writes a compact, deterministic summary:

    data/s2/wikidata_entities.jsonl   one row per matched page (qid, classes, relations, ids, dates)
    data/s2/wikidata_missing.jsonl    titles with no Wikidata entity
    data/s2/wikidata_classes.json     label of every class (P31) found
    data/s2/manifest.json

    python -m pipelines.wikipedia_series.enrich_wikidata [--offline] [--limit N]

`--offline` forbids any network request (verification: it must reproduce the same files byte for byte).
No OpenAI, nothing paid; the film project and its snapshots are never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path

import yaml

from .common import DATA_DIR, PACKAGE_DIR, Snapshot, WikidataClient
from .config import WikidataConfig

log = logging.getLogger("series.s2")
S1_DIR = DATA_DIR / "s1"
OUT_DIR = DATA_DIR / "s2"
SOURCES = ("series", "seasons", "episode_lists", "tv_movies", "uncertain")  # + autonomous episode pages
PROPS = "claims|sitelinks|labels|descriptions"

# property -> short name in the summary. Entity-valued ones keep QIDs; the rest keep the raw value.
ENTITY_PROPS = {"P31": "instance_of", "P179": "part_of_series", "P361": "part_of", "P155": "follows", "P156": "followed_by",
                "P449": "network", "P495": "country", "P136": "genre", "P364": "original_language", "P4908": "season_of",
                "P8345": "franchise"}
VALUE_PROPS = {"P345": "imdb_id", "P4983": "tmdb_tv_id", "P4947": "tmdb_movie_id", "P4835": "tvdb_id",
               "P1476": "original_title", "P2437": "seasons_count", "P2438": "episodes_count",
               "P577": "publication_date", "P580": "start_time", "P582": "end_time", "P1545": "series_ordinal"}
KEEP_ENTITY = {"P31", "P179", "P361", "P155", "P156", "P449", "P495", "P136", "P364", "P8345"}
KEEP_VALUE = {"P345", "P4983", "P4947", "P4835", "P1476", "P2437", "P2438", "P577", "P580", "P582"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snak_value(snak: dict):
    if snak.get("snaktype") != "value":
        return None
    value = snak["datavalue"]["value"]
    if isinstance(value, dict):
        if "id" in value:
            return value["id"]
        if "time" in value:
            return value["time"]
        if "amount" in value:
            return value["amount"].lstrip("+")
        if "text" in value:
            return value["text"]
        return None
    return value


def claim_rows(entity: dict, prop: str) -> list[dict]:
    """Non-deprecated statements of a property: value, rank and the ordinal qualifier (P1545) if any."""
    rows = []
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = snak_value(claim.get("mainsnak", {}))
        if value is None:
            continue
        row = {"v": value, "preferred": claim.get("rank") == "preferred"}
        ordinals = [snak_value(q) for q in claim.get("qualifiers", {}).get("P1545", [])]
        if ordinals and ordinals[0] is not None:
            row["ordinal"] = ordinals[0]
        rows.append(row)
    return rows


def summarize(entity: dict, title: str) -> dict:
    out: dict = {"qid": entity["id"], "title": title,
                 "label_it": entity.get("labels", {}).get("it", {}).get("value"),
                 "label_en": entity.get("labels", {}).get("en", {}).get("value"),
                 "description_en": entity.get("descriptions", {}).get("en", {}).get("value")}
    for prop in sorted(KEEP_ENTITY):
        rows = claim_rows(entity, prop)
        if rows:
            out[ENTITY_PROPS[prop]] = [r["v"] for r in rows] if prop != "P179" else [
                {"qid": r["v"], **({"ordinal": r["ordinal"]} if "ordinal" in r else {})} for r in rows]
    for prop in sorted(KEEP_VALUE):
        rows = claim_rows(entity, prop)
        if rows:
            out[VALUE_PROPS[prop]] = [r["v"] for r in rows] if prop not in ("P345", "P4983", "P4947", "P4835") else rows[0]["v"]
    return out


def fetch_titles(client: WikidataClient, titles: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Entities keyed by itwiki title, and the titles that have none."""
    data = client.get_json({"action": "wbgetentities", "sites": "itwiki", "titles": "|".join(titles), "props": PROPS,
                            "languages": "it|en", "sitefilter": "itwiki"})
    normalized = {n["from"]: n["to"] for n in data.get("normalized", [])}  # empty unless the API normalises a title
    found: dict[str, dict] = {}
    for qid, entity in data.get("entities", {}).items():
        if "missing" in entity:
            continue
        link = entity.get("sitelinks", {}).get("itwiki", {}).get("title")
        if link:
            found[link] = entity
    result, missing = {}, []
    for title in titles:
        target = normalized.get(title, title)
        entity = found.get(target) or found.get(title)
        if entity:
            result[title] = summarize(entity, title)
        else:
            missing.append(title)
    return result, missing


def class_labels(client: WikidataClient, qids: list[str]) -> dict[str, dict]:
    out = {}
    for start in range(0, len(qids), 50):
        chunk = qids[start:start + 50]
        data = client.get_json({"action": "wbgetentities", "ids": "|".join(chunk), "props": "labels", "languages": "it|en"})
        for qid, ent in data.get("entities", {}).items():
            lab = ent.get("labels", {})
            out[qid] = {"it": lab.get("it", {}).get("value"), "en": lab.get("en", {}).get("value")}
    return out


def collect_titles(s1: Path) -> list[tuple[str, str, int]]:
    """(title, source file, page id) of every S1 page that can have a Wikidata entity. Order is stable."""
    seen, out = set(), []
    for name in SOURCES + ("episodes",):
        path = s1 / f"{name}.jsonl"
        if not path.exists():
            continue
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            if name == "episodes" and rec.get("source") != "episode_page":
                continue  # sections of a season page have no page of their own
            if rec["title"] in seen:
                continue
            seen.add(rec["title"])
            out.append((rec["title"], name, rec["page_id"]))
    return sorted(out, key=lambda t: t[2])


def load_client(offline: bool) -> WikidataClient:
    cfg = WikidataConfig.model_validate(yaml.safe_load((PACKAGE_DIR / "config.yaml").read_text())["wikidata"])
    if offline:
        cfg = cfg.model_copy(update={"mode": "offline"})
    return WikidataClient(cfg, Snapshot(DATA_DIR.parent / cfg.snapshot_root / cfg.snapshot_id))


def write_lines(path: Path, rows: list[dict]) -> None:
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def run(client: WikidataClient, s1: Path, out_dir: Path, *, limit: int | None = None, batch: int = 50) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = collect_titles(s1)
    if limit:
        items = items[:limit]
    titles = [t for t, _, _ in items if "|" not in t]
    skipped = [t for t, _, _ in items if "|" in t]
    entities, missing = {}, []
    started = time.monotonic()
    for start in range(0, len(titles), batch):
        found, gone = fetch_titles(client, titles[start:start + batch])
        entities.update(found)
        missing += gone
        if (start // batch) % 20 == 0:
            log.info("%d/%d titles, %d entities, %d network / %d snapshot requests, %.0f s", start, len(titles), len(entities),
                     client.network_requests, client.snapshot_hits, time.monotonic() - started)
    by_title = {t: (src, pid) for t, src, pid in items}
    rows = []
    for title, ent in entities.items():
        src, pid = by_title[title]
        rows.append({"page_id": pid, "source": src, **ent})
    rows.sort(key=lambda r: r["page_id"])
    write_lines(out_dir / "wikidata_entities.jsonl", rows)
    write_lines(out_dir / "wikidata_missing.jsonl", sorted(({"title": t, "source": by_title[t][0], "page_id": by_title[t][1]} for t in missing + skipped),
                                                          key=lambda r: r["page_id"]))
    classes = sorted({q for r in rows for q in r.get("instance_of", [])})
    labels = class_labels(client, classes)
    (out_dir / "wikidata_classes.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    by_src = Counter(r["source"] for r in rows)
    miss_src = Counter(by_title[t][0] for t in missing + skipped)
    manifest = {"entities": len(rows), "missing": len(missing), "skipped_titles_with_pipe": len(skipped),
                "matched_by_source": dict(by_src), "missing_by_source": dict(miss_src), "classes": len(labels),
                "requests": {"network": client.network_requests, "snapshot_hits": client.snapshot_hits},
                "snapshot_id": client.cfg.snapshot_id, "mode": client.cfg.mode, "limit": limit,
                "files": {n: sha256_file(out_dir / n) for n in ("wikidata_entities.jsonl", "wikidata_missing.jsonl", "wikidata_classes.json")},
                "seconds": round(time.monotonic() - started, 1)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="no network: snapshot only (verification)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    manifest = run(load_client(args.offline), S1_DIR, args.out, limit=args.limit)
    print(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
