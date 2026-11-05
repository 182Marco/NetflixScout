"""Per-record evidence for the audit, from LOCAL data only: films.jsonl, candidates.jsonl (flags, infobox, plot heading)
and the original Wikidata responses of the snapshot (claims P31 'instance of', P279, sitelink titles, label)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
SNAPSHOT = ROOT / "data" / "cache" / "wikidata" / "itwiki-20261101-a"
OUT = ROOT / "data" / "audit"


def claim_ids(entity: dict, prop: str) -> list[str]:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if c.get("rank") != "deprecated" and isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def snapshot_entities() -> dict[str, dict]:
    """qid -> {p31, p279, has_enwiki, label_it, label_en} from every stored wbgetentities response."""
    out: dict[str, dict] = {}
    for line in (SNAPSHOT / "requests.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["params"].get("action") != "wbgetentities":
            continue
        body = json.loads(gzip.decompress((SNAPSHOT / "bodies" / f"{e['sha256']}.json.gz").read_bytes()))
        for qid, ent in body.get("entities", {}).items():
            out[qid] = {"p31": claim_ids(ent, "P31"), "p279": claim_ids(ent, "P279"),
                        "enwiki": "enwiki" in ent.get("sitelinks", {}),
                        "label_it": ent.get("labels", {}).get("it", {}).get("value"),
                        "label_en": ent.get("labels", {}).get("en", {}).get("value")}
    return out


def load() -> list[dict]:
    wd = snapshot_entities()
    cand = {int(json.loads(l)["page_id"]): json.loads(l) for l in (PROCESSED / "candidates.jsonl").open()}
    rows = []
    for line in (PROCESSED / "films.jsonl").open():
        f = json.loads(line)
        c = cand[f["wikipedia_page_id"]]
        w = wd.get(f["wikidata_id"] or "", {})
        rows.append({"film": f, "flags": c["flags"], "infobox_keys": sorted(c["infobox"]), "plot_heading": c["plot_heading"],
                     "p31": w.get("p31", []), "p279": w.get("p279", []), "enwiki": w.get("enwiki"), "has_wd": bool(w)})
    return rows
