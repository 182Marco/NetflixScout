"""franchise_id for the v3 collection, derived OFFLINE from the Wikidata snapshot (no network).

A film belongs to a franchise when Wikidata says so (P8345 media franchise, P179 part of the series) or when the film is tied to
another catalogue film by a sequel chain (P155 follows, P156 followed by). A film without any group has franchise_id = None. Coverage is partial by nature: Wikidata is incomplete."""
from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data/cache/wikidata/itwiki-20261101-a"
P_FRANCHISE, P_SERIES = "P8345", "P179"
P_LINKS = ("P155", "P156")           # sequel chains only: remakes and adaptations (P144, P4969) merged unrelated films


def _vals(claims: dict, prop: str) -> list[str]:
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def read_links(film_ids: set[str]) -> dict[str, dict]:
    """film_id -> {"franchises": [...], "links": [...]} read from every wbgetentities body of the snapshot."""
    found: dict[str, dict] = {}
    for line in (SNAP / "requests.jsonl").open(encoding="utf-8"):
        e = json.loads(line)
        if e["params"].get("action") != "wbgetentities" or "claims" not in e["params"].get("props", ""):
            continue
        body = json.loads(gzip.decompress((SNAP / "bodies" / f"{e['sha256']}.json.gz").read_bytes()))
        for qid, ent in (body.get("entities") or {}).items():
            if qid not in film_ids or "claims" not in ent:
                continue
            cl = ent["claims"]
            found[qid] = {"franchises": sorted(set(_vals(cl, P_FRANCHISE) + _vals(cl, P_SERIES))),
                          "sequel_links": sorted({x for p in P_LINKS for x in _vals(cl, p)})}
    return found


MAX_FRANCHISE = 60     # declared groups larger than this are lists (a studio, a registry, a character with hundreds of shorts), not franchises
MIN_DECLARED = 2


def assign(films: dict[str, dict], links: dict[str, dict]) -> dict[str, dict]:
    """films: film_id -> record (needs `year`). Returns film_id -> {franchise_id, franchise_ids, franchise_size, franchise_basis}.

    `franchise_ids` is every group the film belongs to (a crossover belongs to two); excluding a franchise means excluding every film
    that shares ANY id with the referenced film. Sequel chains (P155/P156 only) are components; a component of 2..MAX films gets an id
    "C:<oldest film id>". Declared franchises count only when they have MIN_DECLARED..MAX_FRANCHISE members in this catalogue."""
    declared_count = Counter(fr for f in films for fr in links.get(f, {}).get("franchises", []))
    specific = {fr for fr, n in declared_count.items() if MIN_DECLARED <= n <= MAX_FRANCHISE}
    parent = {f: f for f in films}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for f, d in links.items():
        for o in d["sequel_links"]:
            if o in films and o != f:
                ra, rb = find(f), find(o)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    comps: dict[str, list[str]] = {}
    for f in films:
        comps.setdefault(find(f), []).append(f)
    comp_id: dict[str, str] = {}
    for members in comps.values():
        if MIN_DECLARED <= len(members) <= MAX_FRANCHISE:
            oldest = sorted(members, key=lambda f: (films[f].get("year") or 9999, f))[0]
            for f in members:
                comp_id[f] = f"C:{oldest}"
    sizes = Counter(comp_id.values())
    out: dict[str, dict] = {}
    for f in films:
        decl = [fr for fr in links.get(f, {}).get("franchises", []) if fr in specific]
        ids = sorted(set(decl) | ({comp_id[f]} if f in comp_id else set()))
        if not ids:
            continue
        primary = sorted(decl, key=lambda fr: (-declared_count[fr], fr))[0] if decl else comp_id[f]
        size = declared_count[primary] if decl else sizes[comp_id[f]]
        basis = "+".join(b for b, on in (("wikidata_franchise", bool(decl)), ("sequel_chain", f in comp_id)) if on)
        out[f] = {"franchise_id": primary, "franchise_ids": ids, "franchise_size": size, "franchise_basis": basis}
    return out
