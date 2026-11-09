"""Phase 0 Wikidata probe: a handful of AGGREGATE read-only queries (free public API, own snapshot).

1. labels of the candidate class ids (class ids are never trusted from memory);
2. per class: items, items with an itwiki sitelink, and how many carry the properties that would
   give relations / metadata (series, order, dates, external ids).
Responses are stored in `data/cache/wikidata/<snapshot_id>` so a rerun is offline and identical.

    python -m pipelines.wikipedia_series.phase0.wikidata_probe
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from ..common import DATA_DIR, PACKAGE_DIR, Snapshot, WikidataClient
from ..config import WikidataConfig

log = logging.getLogger("series.phase0.wikidata")

CLASSES = {
    "Q5398426": "tv series?", "Q1259759": "miniseries?", "Q98701476": "miniseries?", "Q63952888": "anime series?",
    "Q15416": "tv programme?", "Q21191270": "tv episode?", "Q3464665": "tv season?", "Q21198342": "manga series?",
    "Q220898": "?", "Q113687694": "ova?", "Q1047299": "?", "Q24856": "film series?", "Q1983062": "episode?",
    "Q1261214": "tv special?", "Q506240": "tv film?", "Q117467246": "?", "Q1667921": "novel series?",
    "Q581714": "animated series?", "Q7725310": "series of creative works?", "Q43232": "?", "Q336144": "?",
}
SERIES_PROPS = ["P2437", "P2438", "P449", "P345", "P4983", "P4835", "P577", "P580", "P582", "P364"]
CHILD_PROPS = ["P179", "P155", "P156", "P577", "P345", "P4983", "P4835", "P361"]


def load_client() -> WikidataClient:
    cfg = WikidataConfig.model_validate(yaml.safe_load((PACKAGE_DIR / "config.yaml").read_text())["wikidata"])
    return WikidataClient(cfg, Snapshot(DATA_DIR.parent / cfg.snapshot_root / cfg.snapshot_id))


def labels(client: WikidataClient, ids: list[str]) -> dict:
    data = client.get_json({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|descriptions",
                            "languages": "it|en"})
    out = {}
    for qid, ent in data.get("entities", {}).items():
        lab = ent.get("labels", {})
        desc = ent.get("descriptions", {})
        out[qid] = {"it": lab.get("it", {}).get("value"), "en": lab.get("en", {}).get("value"),
                    "desc_en": desc.get("en", {}).get("value"), "missing": "missing" in ent}
    return out


def count_query(cls: str, props: list[str], itwiki: bool) -> str:
    sitelink = "?s schema:about ?i ; schema:isPartOf <https://it.wikipedia.org/> ." if itwiki else ""
    opts = " ".join(f"OPTIONAL {{ ?i wdt:{p} ?v{n} . }}" for n, p in enumerate(props))
    cols = " ".join(f"(COUNT(DISTINCT ?v{n}) AS ?c{n})" for n, _ in enumerate(props))
    return f"SELECT (COUNT(DISTINCT ?i) AS ?items) {cols} WHERE {{ ?i wdt:P31 wd:{cls} . {sitelink} {opts} }}"


def probe_class(client: WikidataClient, cls: str, props: list[str], itwiki: bool) -> dict:
    # COUNT(DISTINCT ?vN) counts distinct VALUES, not items: wrapped per property to count ITEMS.
    sitelink = "?s schema:about ?i ; schema:isPartOf <https://it.wikipedia.org/> ." if itwiki else ""
    parts = " ".join(
        f"{{ SELECT (COUNT(DISTINCT ?i{n}) AS ?c{n}) WHERE {{ ?i{n} wdt:P31 wd:{cls} . "
        f"{sitelink.replace('?i ', f'?i{n} ')} ?i{n} wdt:{p} ?x . }} }}"
        for n, p in enumerate(props)
    )
    base = f"{{ SELECT (COUNT(DISTINCT ?i) AS ?items) WHERE {{ ?i wdt:P31 wd:{cls} . {sitelink} }} }}"
    query = "SELECT * WHERE { " + base + " " + parts + " }"
    rows = client.sparql_json(query)["results"]["bindings"]
    row = rows[0] if rows else {}
    out = {"items": int(row.get("items", {}).get("value", 0))}
    for n, p in enumerate(props):
        out[p] = int(row.get(f"c{n}", {}).get("value", 0))
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    client = load_client()
    result: dict = {"labels": {}, "classes": {}}
    ids = list(CLASSES)
    for start in range(0, len(ids), 50):
        result["labels"].update(labels(client, ids[start:start + 50]))
    for cls in ids:
        info = result["labels"].get(cls, {})
        if info.get("missing"):
            continue
        props = SERIES_PROPS if cls in {"Q5398426", "Q1259759", "Q98701476", "Q63952888", "Q15416", "Q581714"} else CHILD_PROPS
        entry = {"label": info.get("en"), "desc": info.get("desc_en")}
        for name, itwiki in (("all", False), ("itwiki", True)):
            try:
                entry[name] = probe_class(client, cls, props, itwiki)
            except Exception as error:  # a timeout on a huge class is a result, not a crash
                entry[name] = {"error": str(error)[:200]}
            log.info("%s %s %s: %s", cls, entry["label"], name, entry[name])
        result["classes"][cls] = entry
    result["requests"] = {"network": client.network_requests, "snapshot_hits": client.snapshot_hits}
    out = DATA_DIR / "phase0" / "wikidata_probe.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("written %s (%d network requests)", out, client.network_requests)


if __name__ == "__main__":
    main()
