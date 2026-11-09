"""Read-only loaders of every local archive used by the A0 audit. Each returns plain Python structures.

Nothing is cached on disk and nothing is written; each loader is called at most once per run (see `Context`).
"""
from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

from cinema_db.harness.build.snapshot import Snapshot

from . import util

EXTERNAL_ID_PROPS = {
    "P345": "imdb_title", "P4947": "tmdb_movie", "P4983": "tmdb_tv", "P4835": "tvdb_series", "P2704": "eidr",
}
# Properties whose meaning is certain (the audit does not guess the others: they are listed by number only).
KNOWN_PROPS = {
    "P345": "IMDb title/name ID", "P4947": "TMDb movie ID", "P4983": "TMDb TV series ID", "P4835": "TheTVDB series ID",
    "P2704": "EIDR ID", "P1712": "Metacritic ID", "P1258": "Rotten Tomatoes ID", "P6127": "Letterboxd film ID",
    "P161": "cast member", "P57": "director", "P58": "screenwriter", "P136": "genre", "P577": "publication date",
    "P166": "award received", "P1411": "nominated for", "P2142": "box office", "P2130": "cost (budget)",
    "P144": "based on", "P155": "follows", "P156": "followed by", "P179": "part of the series", "P8345": "media franchise",
}


def cinema_works(conn) -> dict[int, tuple[str, int | None]]:
    return {w: (k, y) for w, k, y in conn.execute("SELECT work_id, kind, release_year FROM work")}


def cinema_external_ids(conn) -> dict[str, dict[str, list[int]]]:
    """scheme -> value -> [entity_id] (a list: the uniqueness constraint is checked, not assumed)."""
    out: dict[str, dict[str, list[int]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for entity_id, scheme, value in conn.execute("SELECT entity_id, scheme, value FROM external_id"):
        out[scheme][value].append(entity_id)
    return out


def cinema_names(conn) -> dict[str, list[int]]:
    """normalised work name (any kind of name) -> work ids."""
    out: dict[str, list[int]] = collections.defaultdict(list)
    for entity_id, name in conn.execute(
        "SELECT n.entity_id, n.name FROM entity_name n JOIN work w ON w.work_id = n.entity_id"
    ):
        key = util.norm_title(name)
        if key:
            out[key].append(entity_id)
    return out


def movielens(conn) -> list[dict[str, Any]]:
    """One record per MovieLens movie (links + stats + parsed title + genres)."""
    genres: dict[int, list[str]] = collections.defaultdict(list)
    for movie_id, genre in conn.execute("SELECT movie_id, genre FROM movie_genres"):
        genres[movie_id].append(genre)
    stats = {m: (n, a) for m, n, a in conn.execute("SELECT movie_id, n_ratings, avg_rating FROM movie_stats")}
    rows = []
    for movie_id, title, year, imdb, tmdb in conn.execute(
        "SELECT m.movie_id, m.title, m.year, l.imdb_id, l.tmdb_id FROM movies m LEFT JOIN links l USING(movie_id)"
    ):
        names, parsed_year = util.parse_movielens_title(title)
        n, avg = stats.get(movie_id, (0, None))
        rows.append({
            "movie_id": movie_id, "title": title, "names": names, "year": year or parsed_year,
            "imdb": util.imdb_tt(imdb), "tmdb": str(tmdb).strip() if tmdb not in (None, "") else None,
            "n": n, "avg": avg, "genres": sorted(genres.get(movie_id, [])),
        })
    return rows


def v3_catalog() -> list[dict[str, Any]]:
    keep = ("film_id", "wikidata_id", "imdb_id", "title", "original_title", "year", "wikipedia_page_id", "work_format",
            "franchise_ids", "catalog_status")
    rows = []
    for d in util.iter_jsonl(util.V3_CATALOG):
        r = {k: d.get(k) for k in keep}
        actors = d.get("actors") or []
        r["actors"] = [(a.get("wikidata_id"), a.get("character")) for a in actors]
        r["directors"] = [x.get("wikidata_id") for x in (d.get("director") or [])]
        r["duration"] = d.get("duration_minutes")
        rows.append(r)
    return rows


def film_pages_status() -> dict[str, Any]:
    """Pages of the film extraction: accepted candidates, rejected (with reason) and the cleaning exclusions."""
    candidates = {d["page_id"]: d["title"] for d in util.iter_jsonl(util.CANDIDATES) if "page_id" in d}
    rejected = {d["page_id"]: (d["title"], d["reason"]) for d in util.iter_jsonl(util.REJECTED)}
    excluded = list(util.iter_jsonl(util.CLEAN_EXCLUDED))
    return {"candidates": candidates, "rejected": rejected, "excluded": excluded}


def s5_records() -> dict[str, list[dict[str, Any]]]:
    """Series catalogue s5: minimal fields per file. Episodes are counted only (155 MB)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name in ("series", "tv_movies", "uncertain", "seasons"):
        rows = []
        for d in util.iter_jsonl(util.S5 / f"{name}.jsonl"):
            ids = d.get("ids") or {}
            rows.append({
                "record_id": d.get("record_id"), "title": d.get("title"), "qid": ids.get("qid"),
                "imdb": util.imdb_tt(ids.get("imdb_id")), "tmdb": ids.get("tmdb_id"), "tmdb_kind": ids.get("tmdb_kind"),
                "tvdb": ids.get("tvdb_id"), "entity_type": d.get("entity_type"), "catalog_class": d.get("catalog_class"),
                "has_cast": bool(d.get("cast")), "eligible": d.get("default_search_eligible"),
                "year": d.get("year") or d.get("first_year"), "ids_reliable": d.get("ids_reliable"),
            })
        out[name] = rows
    episodes = with_number = with_ids = 0
    for d in util.iter_jsonl(util.S5 / "episodes.jsonl"):
        episodes += 1
        with_number += d.get("episode_number") is not None
        with_ids += bool((d.get("ids") or {}).get("qid"))
    out["episodes_summary"] = [{"episodes": episodes, "with_number": with_number, "with_qid": with_ids}]
    out["excluded"] = [{"reason": d.get("reason")} for d in util.iter_jsonl(util.S5 / "excluded.jsonl")]
    return out


def snapshot_census(root: Path) -> dict[str, Any]:
    """Entities of a Wikidata snapshot (de-duplicated by QID): identifiers, claim census, cast qualifiers."""
    snap = Snapshot(root)
    seen: set[str] = set()
    ents: dict[str, dict[str, Any]] = {}
    props: collections.Counter[str] = collections.Counter()
    datatype: dict[str, str] = {}
    cast = {"statements": 0, "with_ordinal": 0, "with_character_name": 0, "with_character_item": 0, "entities_with_ordinal": 0}
    for qid, entity in snap.entities():
        if qid in seen:
            continue
        seen.add(qid)
        claims = entity.get("claims", {})
        rec: dict[str, Any] = {"label_it": ((entity.get("labels") or {}).get("it") or {}).get("value"),
                               "label_en": ((entity.get("labels") or {}).get("en") or {}).get("value"),
                               "p31": [], "sitelink": ((entity.get("sitelinks") or {}).get("itwiki") or {}).get("title")}
        for prop in claims:
            props[prop] += 1
            if prop not in datatype and claims[prop]:
                datatype[prop] = claims[prop][0].get("mainsnak", {}).get("datatype", "")
        for prop, scheme in EXTERNAL_ID_PROPS.items():
            vals = [s["mainsnak"]["datavalue"]["value"] for s in claims.get(prop, [])
                    if s.get("rank") != "deprecated" and s.get("mainsnak", {}).get("snaktype") == "value"]
            if vals:
                rec[scheme] = vals
        rec["p31"] = [s["mainsnak"]["datavalue"]["value"]["id"] for s in claims.get("P31", [])
                      if s.get("mainsnak", {}).get("snaktype") == "value"]
        ordinal_here = False
        for s in claims.get("P161", []):
            if s.get("rank") == "deprecated":
                continue
            cast["statements"] += 1
            q = s.get("qualifiers", {})
            if "P1545" in q:
                cast["with_ordinal"] += 1
                ordinal_here = True
            cast["with_character_name"] += "P4633" in q
            cast["with_character_item"] += "P453" in q
        cast["entities_with_ordinal"] += ordinal_here
        ents[qid] = rec
    return {"entities": ents, "props": dict(props), "datatype": datatype, "cast": cast,
            "index_sha256": snap.index_sha256, "requests": len(snap.requests), "acquired": snap.acquired_range}


def phase4_person_kinds() -> dict[str, int]:
    """What the person responses of the targeted Wikidata snapshot carry (SPARQL `kind` values)."""
    snap = Snapshot(util.PHASE4_SNAPSHOT)
    kinds: collections.Counter[str] = collections.Counter()
    persons = set()
    for r in snap.requests:
        if r.status != 200 or not r.endpoint.endswith("/sparql"):
            continue
        for b in snap.body(r).get("results", {}).get("bindings", []):
            if "kind" in b and "p" in b:
                kinds[b["kind"]["value"]] += 1
                persons.add(b["p"]["value"])
    return {"kinds": dict(kinds), "distinct_items": len(persons)}
