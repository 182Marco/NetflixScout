"""Sections of the A0 audit. Every function takes the lazy `Context` and returns a JSON-serialisable dict.

Labels: values are MEASURED unless the key says `estimate`/`hypothesis`. Heuristics are named in the output.
"""
from __future__ import annotations

import collections
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from . import loaders, util
from .util import pct

ML_THRESHOLDS = (1, 5, 10, 20, 50, 100, 500, 1000, 5000, 10000)
SCREEN_KINDS = ("film", "short", "tv_film", "series", "miniserie", "miniseries")


class Context:
    """Lazy, memoised access to every archive; the audit opens each one read-only and at most once."""

    def __init__(self, out_dir: Path = util.OUT_DIR, *, cinema: Path = util.CINEMA_DB, movielens: Path = util.MOVIELENS_DB) -> None:
        self.out_dir = out_dir
        self._cinema_path, self._ml_path = cinema, movielens
        self._memo: dict[str, Any] = {}

    def _get(self, key: str, make):
        if key not in self._memo:
            self._memo[key] = make()
        return self._memo[key]

    @property
    def cinema(self):
        return self._get("cinema", lambda: util.open_ro(self._cinema_path))

    @property
    def ml_db(self):
        return self._get("ml_db", lambda: util.open_ro(self._ml_path))

    works = property(lambda s: s._get("works", lambda: loaders.cinema_works(s.cinema)))
    ids = property(lambda s: s._get("ids", lambda: loaders.cinema_external_ids(s.cinema)))
    names = property(lambda s: s._get("names", lambda: loaders.cinema_names(s.cinema)))
    ml = property(lambda s: s._get("ml", lambda: loaders.movielens(s.ml_db)))
    v3 = property(lambda s: s._get("v3", loaders.v3_catalog))
    pages = property(lambda s: s._get("pages", loaders.film_pages_status))
    s5 = property(lambda s: s._get("s5", loaders.s5_records))
    film_snap = property(lambda s: s._get("film_snap", lambda: loaders.snapshot_census(util.FILM_SNAPSHOT)))
    series_snap = property(lambda s: s._get("series_snap", lambda: loaders.snapshot_census(util.SERIES_SNAPSHOT)))

    @property
    def rev(self) -> dict[int, dict[str, list[str]]]:
        """entity_id -> scheme -> [values] (reverse of `ids`)."""
        def make():
            out: dict[int, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))
            for scheme, values in self.ids.items():
                for value, entities in values.items():
                    for e in entities:
                        out[e][scheme].append(value)
            return out
        return self._get("rev", make)

    def qid_map(self, *, persons: bool = False) -> dict[str, int]:
        """Wikidata QID -> entity id, restricted to works (default) or persons. A QID may name both in rare dual-use cases."""
        ok = (lambda e: e not in self.works) if persons else (lambda e: e in self.works)
        return {v: next(e for e in es if ok(e)) for v, es in self.ids.get("wikidata", {}).items() if any(ok(e) for e in es)}

    def imdb_to_work(self) -> dict[str, int]:
        return {v: e[0] for v, e in self.ids.get("imdb_title", {}).items()}

    def dump_records(self) -> list[dict] | None:
        path = self.out_dir / "dump_scan.jsonl"
        return list(util.iter_jsonl(path)) if path.is_file() else None


def _decade(year: int | None) -> str:
    return "unknown" if not year else f"{year // 10 * 10}s"


# ----------------------------------------------------------------------------------------------- inventory
def inventory(ctx: Context) -> dict:
    c = ctx.cinema
    info = dict(c.execute("SELECT key, value FROM build_info"))
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
              ("work", "person", "company", "franchise", "credit", "external_id", "award_result", "work_relation", "work_release", "work_financial")}
    ml = ctx.ml_db
    ml_counts = {t: ml.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("movies", "links", "movie_stats", "ratings", "tags", "movie_genres")}
    files = [util.CINEMA_DB, util.MOVIELENS_DB, util.V3_CATALOG, util.CLEAN_CATALOG, util.CANDIDATES, util.REJECTED,
             util.CLEAN_EXCLUDED, util.DUMP] + sorted(util.S5.glob("*.jsonl"))
    return {
        "cinema_build_info": info, "cinema_counts": counts, "movielens_counts": ml_counts,
        "files": [util.fingerprint(f, sha=f.stat().st_size < 200_000_000 and f not in (util.CINEMA_DB, util.MOVIELENS_DB))
                  for f in files if f.is_file()],
        "snapshots": {"film": {"index_sha256": ctx.film_snap["index_sha256"], "requests": ctx.film_snap["requests"],
                               "acquired": ctx.film_snap["acquired"], "entities": len(ctx.film_snap["entities"])},
                      "series": {"index_sha256": ctx.series_snap["index_sha256"], "requests": ctx.series_snap["requests"],
                                 "acquired": ctx.series_snap["acquired"], "entities": len(ctx.series_snap["entities"])}},
        "v3_records": len(ctx.v3), "candidates": len(ctx.pages["candidates"]), "rejected": len(ctx.pages["rejected"]),
        "clean_excluded": len(ctx.pages["excluded"]),
        "s5": {k: len(v) for k, v in ctx.s5.items()},
        "series_catalog_excluded_reasons": dict(collections.Counter(r["reason"] for r in ctx.s5["excluded"]).most_common(8)),
    }


# ------------------------------------------------------------------------------------------------ overlap
def _sets(ctx: Context) -> dict[str, dict[str, set[str]]]:
    imdb: dict[str, set[str]] = {}
    qid: dict[str, set[str]] = {}
    imdb["cinema"] = set(ctx.ids.get("imdb_title", {}))
    qid["cinema"] = set(ctx.qid_map())
    imdb["movielens"] = {m["imdb"] for m in ctx.ml if m["imdb"]}
    imdb["rag_v3"] = {r["imdb_id"] for r in ctx.v3 if r["imdb_id"]}
    qid["rag_v3"] = {r["wikidata_id"] for r in ctx.v3 if r["wikidata_id"]}
    for name, rows in (("s5_series", ctx.s5["series"]), ("s5_tv_movies", ctx.s5["tv_movies"]), ("s5_uncertain", ctx.s5["uncertain"])):
        imdb[name] = {r["imdb"] for r in rows if r["imdb"]}
        qid[name] = {r["qid"] for r in rows if r["qid"]}
    for name, snap in (("wikidata_film_snapshot", ctx.film_snap), ("wikidata_series_snapshot", ctx.series_snap)):
        imdb[name] = {v for e in snap["entities"].values() for v in e.get("imdb_title", []) if util.TT.match(v)}
        qid[name] = set(snap["entities"])
    return {"imdb": imdb, "qid": qid}


def overlap(ctx: Context) -> dict:
    sets = _sets(ctx)
    out: dict[str, Any] = {}
    for key, family in sets.items():
        names = sorted(family)
        out[key] = {
            "sizes": {n: len(family[n]) for n in names},
            "matrix": {a: {b: len(family[a] & family[b]) for b in names} for a in names},
            "not_in_cinema": {n: len(family[n] - family["cinema"]) for n in names if n != "cinema"},
            "only_in_one_archive": {n: len(family[n] - set().union(*(family[m] for m in names if m != n))) for n in names},
        }
    # v3 film records vs cinema (by QID): in which kind does cinema hold them?
    works = ctx.works
    qid_work = ctx.qid_map()
    kinds = collections.Counter()
    missing = []
    for r in ctx.v3:
        w = qid_work.get(r["wikidata_id"])
        if w is None:
            kinds["absent"] += 1
            missing.append(r)
        else:
            kinds[works[w][0]] += 1
    out["v3_in_cinema_by_kind"] = dict(kinds)
    out["v3_absent_from_cinema_by_format"] = dict(collections.Counter(r["work_format"] for r in missing))
    out["v3_absent_from_cinema_sample"] = [{"qid": r["wikidata_id"], "title": r["title"], "year": r["year"], "imdb": r["imdb_id"],
                                           "format": r["work_format"]} for r in missing[:10]]
    return out


# ------------------------------------------------------------------------------------- MovieLens missing
def ml_relevance_curve(ctx: Context) -> dict:
    """Coverage of MovieLens by cinema at each rating-count threshold (the data needed to choose a threshold later)."""
    have = set(ctx.ids.get("imdb_title", {}))
    rows = []
    for t in ML_THRESHOLDS:
        pool = [m for m in ctx.ml if m["imdb"] and m["n"] >= t]
        miss = [m for m in pool if m["imdb"] not in have]
        rows.append({"min_ratings": t, "ml_films": len(pool), "missing_from_cinema": len(miss),
                     "missing_pct": pct(len(miss), len(pool)), "missing_ratings": sum(m["n"] for m in miss),
                     "total_ratings": sum(m["n"] for m in pool)})
    return {"by_threshold": rows, "movielens_without_imdb_link": sum(1 for m in ctx.ml if not m["imdb"]),
            "movielens_without_stats": sum(1 for m in ctx.ml if m["n"] == 0)}


def ml_missing_targets(ctx: Context) -> list[dict]:
    """All MovieLens films with an IMDb id that cinema does not hold, with cause-relevant features. Deterministic order."""
    have_imdb = set(ctx.ids.get("imdb_title", {}))
    out = []
    for m in sorted(ctx.ml, key=lambda x: x["movie_id"]):
        if m["imdb"] and m["imdb"] not in have_imdb:
            out.append(m)
    return out


def target_keys(missing: list[dict]) -> list[str]:
    keys: set[str] = set()
    for m in missing:
        for name in m["names"]:
            k = util.norm_title(name)
            if k:
                keys.add(k)
    return sorted(keys)


def ml_missing_analysis(ctx: Context) -> tuple[dict, list[dict]]:
    missing = ml_missing_targets(ctx)
    works = ctx.works
    tmdb_movie = ctx.ids.get("tmdb_movie", {})
    other_imdb = {"rag_v3": {r["imdb_id"]: r for r in ctx.v3 if r["imdb_id"]}}
    snap_imdb: dict[str, str] = {}
    for snap in (ctx.film_snap, ctx.series_snap):
        for qid, e in snap["entities"].items():
            for v in e.get("imdb_title", []):
                snap_imdb.setdefault(v, qid)
    s5_imdb = {r["imdb"]: r for name in ("series", "tv_movies", "uncertain") for r in ctx.s5[name] if r["imdb"]}
    dump = ctx.dump_records()
    film_by_key: dict[str, list[dict]] = collections.defaultdict(list)
    hits_by_key: dict[str, list[dict]] = collections.defaultdict(list)
    film_by_title: dict[str, dict] = {}
    if dump is not None:
        for rec in dump:
            if rec["kind"] == "film_page":
                film_by_title[rec["title"]] = rec
                for t in (rec["title"], rec.get("original_title") or ""):
                    k = util.norm_title(util.strip_qualifier(t))
                    if k:
                        film_by_key[k].append(rec)
            else:
                hits_by_key[rec["key"]].append(rec)
    rejected = ctx.pages["rejected"]
    candidates = set(ctx.pages["candidates"])
    rows = []
    for m in missing:
        keys = [k for k in (util.norm_title(n) for n in m["names"]) if k]
        evidence: dict[str, Any] = {}
        # (b) same work under another TMDb id
        alt = tmdb_movie.get(m["tmdb"]) if m["tmdb"] else None
        if alt:
            cause = "present_in_cinema_with_another_imdb_id"
            evidence = {"work_id": alt[0], "tmdb": m["tmdb"]}
        elif m["imdb"] in other_imdb["rag_v3"] or m["imdb"] in snap_imdb or m["imdb"] in s5_imdb:
            cause = "in_local_source_but_not_in_cinema"
            evidence = {"rag_v3": m["imdb"] in other_imdb["rag_v3"], "wikidata_snapshot": snap_imdb.get(m["imdb"]),
                        "s5": s5_imdb.get(m["imdb"], {}).get("catalog_class")}
        else:
            same = [w for k in keys for w in ctx.names.get(k, [])
                    if works[w][0] not in ("episode", "season") and m["year"] and works[w][1] and abs(works[w][1] - m["year"]) <= 1]
            if same:
                cause = "probable_same_work_under_other_ids"
                evidence = {"work_ids": sorted(set(same))[:5]}
            elif dump is None:
                cause = "unclassified_dump_not_scanned"
            else:
                cause, evidence = _dump_cause(m, keys, film_by_key, hits_by_key, film_by_title, rejected, candidates)
        rows.append({"movie_id": m["movie_id"], "title": m["title"], "year": m["year"], "imdb": m["imdb"], "tmdb": m["tmdb"],
                     "n_ratings": m["n"], "avg": m["avg"], "genres": m["genres"], "cause": cause, "evidence": evidence})
    big = [r for r in rows if r["n_ratings"] >= 50]
    summary = {
        "missing_total": len(rows), "missing_ge50": len(big), "dump_scanned": dump is not None,
        "causes_all": dict(collections.Counter(r["cause"] for r in rows).most_common()),
        "causes_ge50": dict(collections.Counter(r["cause"] for r in big).most_common()),
        "ge50_by_decade": dict(sorted(collections.Counter(_decade(r["year"]) for r in big).items())),
        "ge50_top_genres": dict(collections.Counter(g for r in big for g in r["genres"]).most_common(10)),
        "ge50_with_tmdb_id": sum(1 for r in big if r["tmdb"]),
        "ge50_ratings_total": sum(r["n_ratings"] for r in big),
        "ge50_top_by_ratings": [{"title": r["title"], "n": r["n_ratings"], "cause": r["cause"]}
                                for r in sorted(big, key=lambda r: -r["n_ratings"])[:25]],
        "tmdb_known_to_movielens_only": "MovieLens carries the TMDb id of most of them (see ge50_with_tmdb_id).",
    }
    return summary, rows


def _dump_cause(m, keys, film_by_key, hits_by_key, film_by_title, rejected, candidates):
    year = m["year"]
    pages: list[tuple[str, dict]] = []
    for k in keys:
        for rec in film_by_key.get(k, []):
            pages.append(("film_infobox_page", rec))
        for hit in hits_by_key.get(k, []):
            if hit["redirect_to"]:
                target = film_by_title.get(hit["redirect_to"])
                pages.append(("redirect_to_film_page" if target else "redirect_to_other_page", target or hit))
            elif not hit["film_infobox"]:
                pages.append(("page_without_film_infobox", hit))
    film_via = ("film_infobox_page", "redirect_to_film_page")
    confirmed = [(w, r) for w, r in pages if w in film_via and r.get("year") and year and abs(r["year"] - year) <= 1]
    pick = confirmed or [(w, r) for w, r in pages if w in film_via]
    if pick:
        via, rec = pick[0]
        page_id = rec["page_id"]
        if not confirmed:  # same title, different (or unknown) year: reported apart, never counted as the same film
            state = ("rejected:" + rejected[page_id][1]) if page_id in rejected else ("in_extraction" if page_id in candidates else "not_listed")
            return "itwiki_title_only_candidate_year_not_confirmed", {"page": rec["title"], "page_year": rec.get("year"), "via": via, "page_state": state}
        if page_id in rejected:
            return f"itwiki_film_page_rejected:{rejected[page_id][1]}", {"page": rec["title"], "via": via, "match": "year_confirmed"}
        if page_id in candidates:
            return "itwiki_film_page_in_extraction_but_not_in_cinema", {"page": rec["title"], "via": via, "match": "year_confirmed"}
        return "itwiki_film_page_not_in_extraction_lists", {"page": rec["title"], "via": via, "match": "year_confirmed"}
    if pages:
        via, rec = pages[0]
        return f"itwiki_{via}", {"page": rec["title"]}
    return "no_itwiki_page_with_that_title", {}


# ------------------------------------------------------------------------------------------ identifiers
def identifiers(ctx: Context) -> dict:
    c = ctx.cinema
    by_scheme = [{"scheme": s, "entity_type": t, "rows": n, "entities": e}
                 for s, t, n, e in c.execute("""SELECT x.scheme, e.entity_type, COUNT(*), COUNT(DISTINCT x.entity_id)
                                                FROM external_id x JOIN entity e USING(entity_id) GROUP BY 1, 2 ORDER BY 3 DESC""")]
    persons_total = c.execute("SELECT COUNT(*) FROM person").fetchone()[0]
    snaps = {}
    for name, snap in (("film_snapshot", ctx.film_snap), ("series_snapshot", ctx.series_snap)):
        census = []
        for prop, n in sorted(snap["props"].items(), key=lambda kv: -kv[1]):
            if snap["datatype"].get(prop) == "external-id":
                census.append({"property": prop, "label": loaders.KNOWN_PROPS.get(prop, "(label not verified)"), "entities": n,
                               "imported_by_build": prop in loaders.EXTERNAL_ID_PROPS})
        snaps[name] = {"entities": len(snap["entities"]), "external_id_properties": census[:40],
                       "external_id_properties_total": len(census), "cast_statements": snap["cast"],
                       "properties_distinct": len(snap["props"])}
    # v3: do the cast/director records carry any person identifier other than the QID?
    v3_person_ids = {"actors": sum(len(r["actors"]) for r in ctx.v3),
                     "actors_with_qid": sum(1 for r in ctx.v3 for q, _ in r["actors"] if q),
                     "actors_with_character": sum(1 for r in ctx.v3 for _, ch in r["actors"] if ch),
                     "other_person_identifiers": 0}
    ml = ctx.ml
    return {
        "cinema_external_ids": by_scheme, "persons_total": persons_total,
        "persons_with_non_wikidata_id": c.execute("SELECT COUNT(DISTINCT entity_id) FROM external_id WHERE scheme <> 'wikidata' AND entity_id IN (SELECT person_id FROM person)").fetchone()[0],
        "wikidata_snapshots": snaps, "phase4_snapshot_sparql_kinds": loaders.phase4_person_kinds(),
        "rag_v3_person_records": v3_person_ids,
        "movielens_links": {"movies": len(ml), "with_imdb": sum(1 for m in ml if m["imdb"]), "with_tmdb": sum(1 for m in ml if m["tmdb"]),
                            "persons": 0},
        "conclusion_persons": ("no local archive carries IMDb (nm) or TMDb person identifiers: the targeted Wikidata responses hold "
                               "label/birth/death only and the film snapshots hold films. The Italian dump pages of persons were not "
                               "scanned for external links (hypothesis: not a source of nm ids)."),
    }


# ------------------------------------------------------------------------------------------- duplicates
def duplicates(ctx: Context) -> tuple[dict, dict[str, list[dict]]]:
    c = ctx.cinema
    works = ctx.works
    cand: dict[str, list[dict]] = {"work_multiple_ids": [], "work_homonyms": [], "person_pairs": [], "id_conflicts": []}
    ml_by_imdb: dict[str, list[dict]] = collections.defaultdict(list)
    ml_by_tmdb: dict[str, list[dict]] = collections.defaultdict(list)
    for m in ctx.ml:
        if m["imdb"]:
            ml_by_imdb[m["imdb"]].append(m)
        if m["tmdb"]:
            ml_by_tmdb[m["tmdb"]].append(m)
    pname = {w: n for w, n in c.execute("SELECT entity_id, name FROM entity_name WHERE is_primary = 1")}
    # ---- works with more than one identifier of the same scheme
    for scheme in ("imdb_title", "tmdb_movie", "tmdb_tv", "tvdb_series", "eidr"):
        rows = c.execute("SELECT entity_id, GROUP_CONCAT(value, ' '), GROUP_CONCAT(is_primary, ' ') FROM external_id "
                         "WHERE scheme = ? GROUP BY entity_id HAVING COUNT(*) > 1", (scheme,)).fetchall()
        for w, vals, prim in rows:
            values = vals.split()
            ev = "no_external_evidence"
            if scheme == "imdb_title":
                present = [v for v in values if v in ml_by_imdb]
                ev = "all_ids_are_distinct_movielens_films" if len(present) == len(values) else ("one_id_in_movielens" if present else ev)
            cand["work_multiple_ids"].append({"work_id": w, "scheme": scheme, "values": values, "is_primary": prim.split(),
                                              "title": pname.get(w), "kind": works[w][0], "year": works[w][1], "evidence": ev})
    # ---- works that carry BOTH a TMDb movie id and a TMDb TV id (different schemes, so not caught above)
    for w, movie, tv in c.execute("SELECT a.entity_id, a.value, b.value FROM external_id a JOIN external_id b ON a.entity_id = b.entity_id "
                                  "AND a.scheme = 'tmdb_movie' AND b.scheme = 'tmdb_tv'"):
        cand["work_multiple_ids"].append({"work_id": w, "scheme": "tmdb_movie+tmdb_tv", "values": [movie, tv], "is_primary": [],
                                          "title": pname.get(w), "kind": works[w][0], "year": works[w][1], "evidence": "movie_and_tv_id_on_one_work"})
    # ---- same normalised title and year among screen works
    groups: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
    for w, (kind, year) in works.items():
        if kind in ("episode", "season") or not year or w not in pname:
            continue
        groups[(util.norm_title(pname[w]), year)].append(w)
    directors: dict[int, set[int]] = collections.defaultdict(set)
    for w, p in c.execute("SELECT work_id, person_id FROM credit WHERE role = 'director'"):
        directors[w].add(p)
    class_counter: collections.Counter[str] = collections.Counter()
    for (key, year), ws in sorted(groups.items()):
        if len(ws) < 2:
            continue
        for a, b in combinations(ws[:6], 2):
            da, db = directors.get(a, set()), directors.get(b, set())
            cls = ("duplicate_candidate_same_director" if da & db else
                   "homonym_different_directors" if da and db else "undetermined_director_unknown")
            ida = {s: sorted(ctx.rev[a].get(s, [])) for s in ("imdb_title", "tmdb_movie", "wikidata")}
            idb = {s: sorted(ctx.rev[b].get(s, [])) for s in ("imdb_title", "tmdb_movie", "wikidata")}
            class_counter[cls] += 1
            cand["work_homonyms"].append({"title": pname[a], "year": year, "kinds": [works[a][0], works[b][0]], "works": [a, b],
                                          "class": cls, "ids_a": ida, "ids_b": idb})
    # ---- people: same normalised name
    pgroups: dict[str, list[int]] = collections.defaultdict(list)
    birth = {p: y for p, y in c.execute("SELECT person_id, birth_year FROM person")}
    for p, name in c.execute("SELECT n.entity_id, n.name_norm FROM entity_name n JOIN person ON person_id = n.entity_id WHERE n.is_primary = 1"):
        pgroups[name].append(p)
    pw: dict[int, set[tuple[int, str]]] = collections.defaultdict(set)
    shared_names = {n: ps for n, ps in pgroups.items() if len(ps) > 1}
    needed = {p for ps in shared_names.values() for p in ps}
    for p, w, role in c.execute("SELECT person_id, work_id, role FROM credit"):
        if p in needed:
            pw[p].add((w, role))
    pclass: collections.Counter[str] = collections.Counter()
    oversized = 0
    for name, ps in sorted(shared_names.items()):
        if len(ps) > 12:
            oversized += 1
            pclass["group_too_large_to_pair"] += 1
            continue
        for a, b in combinations(sorted(ps), 2):
            same_work = pw[a] & pw[b]
            works_only = {w for w, _ in pw[a]} & {w for w, _ in pw[b]}
            ya, yb = birth.get(a), birth.get(b)
            if same_work:
                cls = "same_person_candidate_strong_shared_work_and_role"
            elif works_only:
                cls = "same_person_candidate_shared_work_other_role"
            elif ya and yb and ya == yb:
                cls = "same_person_candidate_same_birth_year"
            elif ya and yb and ya != yb:
                cls = "homonym_different_birth_year"
            else:
                cls = "undetermined_birth_year_missing"
            pclass[cls] += 1
            if not cls.startswith("homonym"):
                cand["person_pairs"].append({"name": name, "persons": [a, b], "birth_years": [ya, yb], "class": cls,
                                             "shared": sorted(works_only)[:5]})
    # ---- identifier conflicts across sources
    conflict_counter: collections.Counter[str] = collections.Counter()
    imdb_w, qid_w = ctx.imdb_to_work(), ctx.qid_map()
    for r in ctx.v3:
        w = qid_w.get(r["wikidata_id"])
        if w is None:
            continue
        have = ctx.rev[w].get("imdb_title", []) if r["imdb_id"] else []
        if r["imdb_id"] and have and r["imdb_id"] not in have:
            conflict_counter["rag_v3_imdb_differs_from_cinema_for_same_qid"] += 1
            cand["id_conflicts"].append({"type": "v3_vs_cinema_imdb", "qid": r["wikidata_id"], "v3": r["imdb_id"], "cinema": have})
    for m in ctx.ml:
        if m["imdb"] in imdb_w and m["tmdb"]:
            w = imdb_w[m["imdb"]]
            mine = ctx.rev[w].get("tmdb_movie", []) + ctx.rev[w].get("tmdb_tv", [])
            if mine and m["tmdb"] not in mine:
                conflict_counter["movielens_tmdb_differs_from_cinema_for_same_imdb"] += 1
                cand["id_conflicts"].append({"type": "ml_vs_cinema_tmdb", "imdb": m["imdb"], "ml_tmdb": m["tmdb"], "cinema_tmdb": mine})
    conflict_counter["movielens_imdb_shared_by_several_movies"] = sum(1 for v in ml_by_imdb.values() if len(v) > 1)
    conflict_counter["movielens_tmdb_shared_by_several_movies"] = sum(1 for v in ml_by_tmdb.values() if len(v) > 1)
    for name, snap in (("film", ctx.film_snap), ("series", ctx.series_snap)):
        by_imdb: dict[str, list[str]] = collections.defaultdict(list)
        for q, e in snap["entities"].items():
            for v in e.get("imdb_title", []):
                by_imdb[v].append(q)
        multi = {v: qs for v, qs in by_imdb.items() if len(qs) > 1}
        conflict_counter[f"snapshot_{name}_imdb_id_on_several_qids"] = len(multi)
        for v, qs in list(multi.items())[:200]:
            cand["id_conflicts"].append({"type": f"snapshot_{name}_one_imdb_several_qids", "imdb": v, "qids": qs})
    summary = {
        "works_multiple_ids": dict(collections.Counter(r["scheme"] for r in cand["work_multiple_ids"])),
        "works_multiple_ids_evidence": dict(collections.Counter(r["evidence"] for r in cand["work_multiple_ids"] if r["scheme"] == "imdb_title")),
        "work_homonym_pairs_by_class": dict(class_counter), "person_name_groups": len(shared_names),
        "person_groups_oversized_not_paired": oversized, "person_pairs_by_class": dict(pclass),
        "id_conflicts": dict(conflict_counter),
        "note": "candidates only; no merge is performed and none is proposed as certain",
    }
    return summary, cand


# --------------------------------------------------------------------------------------- field coverage
def coverage(ctx: Context) -> dict:
    c = ctx.cinema
    imdb_ml = {m["imdb"]: m for m in ctx.ml if m["imdb"]}
    work_imdb = {e[0]: v for v, e in ctx.ids.get("imdb_title", {}).items()}
    fields = {
        "director": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'director')",
        "cast": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'cast')",
        "cast_with_character": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'cast' AND c.character_name IS NOT NULL)",
        "cast_with_billing_order": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'cast' AND c.billing_order IS NOT NULL)",
        "writer": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'writer')",
        "composer": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'composer')",
        "cinematographer": "EXISTS(SELECT 1 FROM credit c WHERE c.work_id = w.work_id AND c.role = 'cinematographer')",
        "genre": "EXISTS(SELECT 1 FROM work_genre g WHERE g.work_id = w.work_id)",
        "country": "EXISTS(SELECT 1 FROM work_country g WHERE g.work_id = w.work_id)",
        "language": "EXISTS(SELECT 1 FROM work_language g WHERE g.work_id = w.work_id)",
        "company": "EXISTS(SELECT 1 FROM work_company g WHERE g.work_id = w.work_id)",
        "award_result": "EXISTS(SELECT 1 FROM award_result g WHERE g.work_id = w.work_id)",
        "release_dates": "EXISTS(SELECT 1 FROM work_release g WHERE g.work_id = w.work_id)",
        "release_with_type": "EXISTS(SELECT 1 FROM work_release g WHERE g.work_id = w.work_id AND g.kind <> 'unspecified')",
        "relation": "EXISTS(SELECT 1 FROM work_relation g WHERE g.work_id = w.work_id OR g.related_work_id = w.work_id)",
        "franchise": "EXISTS(SELECT 1 FROM work_franchise g WHERE g.work_id = w.work_id)",
        "financial": "EXISTS(SELECT 1 FROM work_financial g WHERE g.work_id = w.work_id)",
        "runtime": "w.runtime_min IS NOT NULL",
        "release_year": "w.release_year IS NOT NULL",
        "original_title": "EXISTS(SELECT 1 FROM entity_name n WHERE n.entity_id = w.work_id AND n.kind = 'original')",
        "imdb_id": "EXISTS(SELECT 1 FROM external_id x WHERE x.entity_id = w.work_id AND x.scheme = 'imdb_title')",
        "tmdb_id": "EXISTS(SELECT 1 FROM external_id x WHERE x.entity_id = w.work_id AND x.scheme IN ('tmdb_movie','tmdb_tv'))",
        "rating_any_source": "0",
    }
    select = ", ".join(f"SUM({expr})" for expr in fields.values())
    by_kind: dict[str, Any] = {}
    for row in c.execute(f"SELECT w.kind, COUNT(*), {select} FROM work w GROUP BY w.kind"):
        by_kind[row[0]] = {"works": row[1], **{f: {"n": row[2 + i] or 0, "pct": pct(row[2 + i] or 0, row[1])} for i, f in enumerate(fields)}}
    # relevance-weighted coverage of films: ML film with n_ratings >= 50 present in cinema
    flags_sql = f"SELECT w.work_id, w.release_year, {select.replace('SUM(', '(')} FROM work w WHERE w.kind = 'film'"
    names = list(fields)
    weighted = {"films_total": 0, "films_in_movielens_ge50": 0,
                "all_films": collections.Counter(), "ml_ge50": collections.Counter()}
    by_decade: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.Counter())
    for row in c.execute(flags_sql):
        wid, year, vals = row[0], row[1], row[2:]
        weighted["films_total"] += 1
        imdb = work_imdb.get(wid)
        ml = imdb_ml.get(imdb) if imdb else None
        heavy = bool(ml and ml["n"] >= 50)
        weighted["films_in_movielens_ge50"] += heavy
        dec = by_decade[_decade(year)]
        dec["films"] += 1
        for f, v in zip(names, vals):
            if v:
                weighted["all_films"][f] += 1
                dec[f] += 1
                if heavy:
                    weighted["ml_ge50"][f] += 1
    out_weighted = {"films_total": weighted["films_total"], "films_in_movielens_ge50": weighted["films_in_movielens_ge50"],
                    "all_films_pct": {f: pct(weighted["all_films"][f], weighted["films_total"]) for f in names},
                    "movielens_ge50_films_pct": {f: pct(weighted["ml_ge50"][f], weighted["films_in_movielens_ge50"]) for f in names}}
    decade_pct = {d: {"films": v["films"], **{f: pct(v[f], v["films"]) for f in ("director", "cast", "cast_with_character", "genre", "runtime", "award_result", "company", "imdb_id")}}
                  for d, v in sorted(by_decade.items())}
    persons = c.execute("SELECT COUNT(*), SUM(birth_year IS NOT NULL), SUM(death_year IS NOT NULL), SUM(birth_country_id IS NOT NULL) FROM person").fetchone()
    cast_size = c.execute("SELECT AVG(n), MAX(n) FROM (SELECT COUNT(*) n FROM credit WHERE role = 'cast' GROUP BY work_id)").fetchone()
    return {"by_kind": by_kind, "films_weighted": out_weighted, "films_by_decade": decade_pct,
            "persons": {"total": persons[0], "birth_year": persons[1], "death_year": persons[2], "birth_country": persons[3]},
            "cast_per_work": {"avg": round(cast_size[0], 2), "max": cast_size[1]},
            "ratings_tables_in_cinema": 0}


# ------------------------------------------------------------------------------------- added value
def added_value(ctx: Context) -> dict:
    """What each local source could add that cinema does not hold yet (measured counts, no import)."""
    c = ctx.cinema
    imdb_w = ctx.imdb_to_work()
    qid_w = ctx.qid_map()
    # MovieLens aggregates and tags for works already in cinema
    in_cinema = [m for m in ctx.ml if m["imdb"] in imdb_w]
    tags = dict(ctx.ml_db.execute("SELECT movie_id, COUNT(*) FROM (SELECT movie_id, tag_norm, COUNT(DISTINCT user_id) u FROM tags GROUP BY movie_id, tag_norm HAVING u >= 2) GROUP BY movie_id").fetchall())
    ml_part = {
        "works_in_cinema_with_movielens_stats": sum(1 for m in in_cinema if m["n"] >= 1),
        "with_ge50_ratings": sum(1 for m in in_cinema if m["n"] >= 50),
        "ratings_covered": sum(m["n"] for m in in_cinema),
        "ratings_total": sum(m["n"] for m in ctx.ml),
        "works_with_tags_ge2_users": sum(1 for m in in_cinema if m["movie_id"] in tags),
        "tags_ge2_users_total_pairs": int(ctx.ml_db.execute("SELECT COUNT(*) FROM (SELECT movie_id, tag_norm FROM tags GROUP BY movie_id, tag_norm HAVING COUNT(DISTINCT user_id) >= 2)").fetchone()[0]),
        "genres_in_movielens_vs_cinema": "MovieLens has 19 coarse genres; cinema holds 38 canonical genres: no gain expected (hypothesis).",
    }
    # RAG v3 cast: ordered list and characters versus cinema credits
    credit_pairs = collections.defaultdict(set)
    has_character: set[tuple[int, int]] = set()
    for w, p, ch in c.execute("SELECT work_id, person_id, character_name FROM credit WHERE role = 'cast'"):
        credit_pairs[w].add(p)
        if ch:
            has_character.add((w, p))
    person_w = ctx.qid_map(persons=True)
    v3_pairs = in_both = new_pairs = with_char = char_for_existing = unlinked = char_new_for_existing = 0
    films_with_actor_list = 0
    for r in ctx.v3:
        w = qid_w.get(r["wikidata_id"])
        if r["actors"]:
            films_with_actor_list += 1
        for q, ch in r["actors"]:
            v3_pairs += 1
            if not q:
                unlinked += 1
                continue
            p = person_w.get(q)
            if w is not None and p is not None and p in credit_pairs.get(w, ()):
                in_both += 1
                char_for_existing += bool(ch)
                char_new_for_existing += bool(ch) and (w, p) not in has_character
            else:
                new_pairs += 1
            with_char += bool(ch)
    v3_part = {"films_with_actor_list": films_with_actor_list, "actor_rows": v3_pairs, "unlinked_actor_rows": unlinked,
               "already_in_cinema_credits": in_both, "not_in_cinema_credits": new_pairs, "rows_with_character": with_char,
               "character_available_for_existing_credits": char_for_existing,
               "character_new_for_existing_credits": char_new_for_existing,
               "cinema_cast_credits_with_character": len(has_character),
               "note": "list order is the page order of the infobox: a billing-order proxy (hypothesis, not verified against a billing source)"}
    snaps = {name: s["cast"] for name, s in (("film_snapshot", ctx.film_snap), ("series_snapshot", ctx.series_snap))}
    return {"movielens": ml_part, "rag_v3_cast": v3_part, "wikidata_cast_qualifiers": snaps,
            "s5": {"series_not_in_cinema_by_qid": sum(1 for r in ctx.s5["series"] if r["qid"] and r["qid"] not in qid_w),
                   "tv_movies_not_in_cinema_by_qid": sum(1 for r in ctx.s5["tv_movies"] if r["qid"] and r["qid"] not in qid_w),
                   "uncertain_not_in_cinema_by_qid": sum(1 for r in ctx.s5["uncertain"] if r["qid"] and r["qid"] not in qid_w),
                   "episodes_summary": ctx.s5["episodes_summary"][0],
                   "cinema_episodes": c.execute("SELECT COUNT(*) FROM work WHERE kind = 'episode'").fetchone()[0]}}


# --------------------------------------------------------------------------------------------- dump
def dump_summary(ctx: Context) -> dict:
    rec = ctx.dump_records()
    if rec is None:
        return {"scanned": False}
    films = [r for r in rec if r["kind"] == "film_page"]
    rejected = ctx.pages["rejected"]
    candidates = ctx.pages["candidates"]
    works = ctx.works
    pname_year = collections.defaultdict(list)
    for key, ws in ctx.names.items():
        for w in ws:
            pname_year[(key, works[w][1])].append(w)
    rej = [r for r in films if r["page_id"] in rejected]
    matched_cinema = 0
    for r in rej:
        k = util.norm_title(util.strip_qualifier(r["title"]))
        if r["year"] and (pname_year.get((k, r["year"])) or pname_year.get((k, r["year"] - 1)) or pname_year.get((k, r["year"] + 1))):
            matched_cinema += 1
    reasons = collections.Counter(rejected[r["page_id"]][1] for r in rej)
    heading_by_reason = collections.Counter((rejected[r["page_id"]][1], bool(r["plot_heading"])) for r in rej)
    return {
        "scanned": True, "film_infobox_pages": len(films), "accepted_page_ids_in_dump_scan": sum(1 for r in films if r["page_id"] in candidates),
        "rejected_page_ids_in_dump_scan": len(rej), "rejected_reasons": dict(reasons),
        "rejected_with_plot_heading_found_by_scan": {f"{k[0]}:{k[1]}": v for k, v in heading_by_reason.items()},
        "rejected_with_year": sum(1 for r in rej if r["year"]), "rejected_by_decade": dict(sorted(collections.Counter(_decade(r["year"]) for r in rej).items())),
        "rejected_matching_a_cinema_work_by_title_and_year": matched_cinema,
        "rejected_without_match_in_cinema": len(rej) - matched_cinema,
        "film_pages_neither_accepted_nor_rejected": sum(1 for r in films if r["page_id"] not in candidates and r["page_id"] not in rejected),
    }
