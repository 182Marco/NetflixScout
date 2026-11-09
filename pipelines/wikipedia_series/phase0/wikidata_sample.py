"""Phase 0: agreement between the infobox-based kind and the Wikidata class (P31), on a stratified sample.

Titles are sent only as SPARQL string literals via VALUES, escaped; responses are snapshotted.
    python -m pipelines.wikipedia_series.phase0.wikidata_sample
"""
from __future__ import annotations

import json
import logging
import random
from collections import Counter, defaultdict

from ..common import DATA_DIR
from .wikidata_probe import labels, load_client

SAMPLE = {"fiction:serie tv": 80, "fiction:miniserie tv": 40, "fiction:serial tv": 20, "fiction:webserie": 20,
          "fiction:film tv": 40, "anim": 60, "programma": 50, "season": 60}


def lit(title: str) -> str:
    return '"' + title.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"@it'


def group(kind: str) -> str:
    return "anim" if kind.startswith("anim:") else kind


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    rng = random.Random(7)
    base = DATA_DIR / "phase0"
    pool = defaultdict(list)
    for l in open(base / "series_per_page.jsonl", encoding="utf-8"):
        r = json.loads(l)
        pool[group(r["kind"])].append(r["title"])
    for l in open(base / "units_preview.jsonl", encoding="utf-8"):
        u = json.loads(l)
        if u["level"] == "season":
            pool["season"].append(u["title"])
    picked = []
    for g, n in SAMPLE.items():
        picked += [(g, t) for t in rng.sample(pool[g], min(n, len(pool[g])))]
    client = load_client()
    rows = {}
    for start in range(0, len(picked), 60):
        chunk = picked[start:start + 60]
        values = " ".join(lit(t) for _, t in chunk)
        query = ("SELECT ?title ?item ?cls WHERE { VALUES ?title { " + values + " } "
                 "?s schema:name ?title ; schema:isPartOf <https://it.wikipedia.org/> ; schema:about ?item . "
                 "OPTIONAL { ?item wdt:P31 ?cls } }")
        for b in client.sparql_json(query)["results"]["bindings"]:
            t = b["title"]["value"]
            rows.setdefault(t, {"item": b["item"]["value"].rsplit("/", 1)[-1], "cls": set()})
            if "cls" in b:
                rows[t]["cls"].add(b["cls"]["value"].rsplit("/", 1)[-1])
    classes = sorted({c for r in rows.values() for c in r["cls"]})
    names = {}
    for start in range(0, len(classes), 50):
        for q, v in labels(client, classes[start:start + 50]).items():
            names[q] = v.get("en")
    out = defaultdict(lambda: {"n": 0, "with_qid": 0, "with_p31": 0, "classes": Counter()})
    for g, t in picked:
        o = out[g]
        o["n"] += 1
        r = rows.get(t)
        if r:
            o["with_qid"] += 1
            if r["cls"]:
                o["with_p31"] += 1
            o["classes"].update(names.get(c, c) for c in r["cls"])
    result = {g: {**{k: v for k, v in o.items() if k != "classes"}, "top_p31": o["classes"].most_common(6)} for g, o in out.items()}
    result["_requests"] = {"network": client.network_requests, "snapshot_hits": client.snapshot_hits}
    (base / "wikidata_sample.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    for g, r in result.items():
        print(g, json.dumps(r, ensure_ascii=False)[:420])


if __name__ == "__main__":
    main()
