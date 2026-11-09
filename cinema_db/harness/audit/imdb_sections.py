"""A1 analyses on top of the A0 `Context` and the IMDb staging file. Pure functions of the archives; no network.

Heuristics are named in the output. Matching never merges anything: it produces tiers and candidates.
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3
from typing import Any

from . import imdb_load as L
from . import util
from .sections import Context, _decade
from .util import pct

FILMISH = ("movie", "tvMovie", "short", "video", "tvSpecial", "tvShort")
TYPE_CLASS = {"movie": "lungometraggio", "short": "cortometraggio", "tvShort": "cortometraggio", "tvSeries": "serie", "tvMiniSeries": "serie",
              "tvEpisode": "episodio", "tvMovie": "film_tv", "tvSpecial": "film_tv", "video": "altro", "videoGame": "altro", "tvPilot": "altro"}
CATEGORY_TO_ROLE = {"actor": "cast", "actress": "cast", "self": "cast", "archive_footage": "cast", "archive_sound": "cast", "director": "director",
                    "writer": "writer", "producer": "producer", "composer": "composer", "cinematographer": "cinematographer", "editor": "editor",
                    "production_designer": "production_designer"}
KIND_TO_TYPES = {"film": {"movie", "video"}, "short": {"short", "tvShort"}, "tv_film": {"tvMovie", "tvSpecial", "video", "movie"},
                 "series": {"tvSeries", "tvMiniSeries"}, "miniseries": {"tvMiniSeries", "tvSeries"}, "episode": {"tvEpisode"}}
MIN_THRESHOLDS = (1, 5, 10, 20, 50, 100, 500, 1000, 5000, 10000)


def _tdict(st: sqlite3.Connection) -> dict[str, tuple]:
    return {r[0]: r[1:] for r in st.execute("SELECT tconst, type, ptitle, otitle, adult, start, runtime, genres, pnorm, onorm FROM title")}


# ------------------------------------------------------------------------------------------------ works
def works_vs_imdb(ctx: Context, st: sqlite3.Connection) -> tuple[dict, list[dict]]:
    titles = _tdict(st)
    works = ctx.works
    rev = ctx.rev
    runtime = {w: r for w, r in ctx.cinema.execute("SELECT work_id, runtime_min FROM work")}
    genres = {w for (w,) in ctx.cinema.execute("SELECT DISTINCT work_id FROM work_genre")}
    matrix: collections.Counter = collections.Counter()
    missing_by_kind: collections.Counter = collections.Counter()
    present_by_kind: collections.Counter = collections.Counter()
    year_cmp: collections.Counter = collections.Counter()
    runtime_cmp: collections.Counter = collections.Counter()
    gain: collections.Counter = collections.Counter()
    adult = 0
    doubles: list[dict] = []
    for w, schemes in rev.items():
        ids = schemes.get("imdb_title")
        if not ids or w not in works:
            continue
        kind, year = works[w]
        found = [(i, titles[i]) for i in ids if i in titles]
        if len(ids) > 1:
            doubles.append({"work_id": w, "kind": kind, "year": year, "imdb_ids": ids,
                            "in_imdb_basics": [i for i in ids if i in titles], "types": {i: titles[i][0] for i in ids if i in titles},
                            "class": ("exactly_one_id_known_to_imdb" if len(found) == 1 else "all_ids_known_to_imdb" if len(found) == len(ids) else "no_id_known_to_imdb")})
        for tconst in ids[:1]:
            if tconst not in titles:
                missing_by_kind[kind] += 1
                continue
            present_by_kind[kind] += 1
            ttype, _p, _o, is_adult, start, rt, gen, _pn, _on = titles[tconst]
            matrix[(kind, ttype)] += 1
            adult += bool(is_adult)
            if year and start:
                year_cmp["equal" if year == start else "off_by_one" if abs(year - start) == 1 else "different"] += 1
            if runtime.get(w) and rt:
                runtime_cmp["equal" if runtime[w] == rt else "within_5_min" if abs(runtime[w] - rt) <= 5 else "different"] += 1
            if not runtime.get(w) and rt:
                gain["runtime_missing_in_cinema_present_in_imdb"] += 1
            if w not in genres and gen:
                gain["genres_missing_in_cinema_present_in_imdb"] += 1
            if not year and start:
                gain["year_missing_in_cinema_present_in_imdb"] += 1
    summary = {
        "cinema_works_with_imdb_id": sum(present_by_kind.values()) + sum(missing_by_kind.values()),
        "found_in_title_basics_by_kind": dict(present_by_kind), "not_in_title_basics_by_kind": dict(missing_by_kind),
        "kind_vs_imdb_type": {f"{k}|{t}": n for (k, t), n in sorted(matrix.items(), key=lambda kv: -kv[1])},
        "year_agreement": dict(year_cmp), "runtime_agreement": dict(runtime_cmp), "imdb_fills_cinema_gaps": dict(gain),
        "works_flagged_adult": adult, "double_imdb_id_classes": dict(collections.Counter(d["class"] for d in doubles)),
    }
    return summary, doubles


# ---------------------------------------------------------------------------------------- people & cast
def _person_names(ctx: Context) -> dict[int, set[str]]:
    names: dict[int, set[str]] = collections.defaultdict(set)
    persons = {p for (p,) in ctx.cinema.execute("SELECT person_id FROM person")}
    for eid, name in ctx.cinema.execute("SELECT entity_id, name FROM entity_name"):
        if eid in persons:
            names[eid].add(L.person_norm(name))
    return names


def people_and_cast(ctx: Context, st: sqlite3.Connection, imdb_of_work: dict[int, str] | None = None) -> tuple[dict, dict[str, list[dict]]]:
    """Match cinema credits to IMDb people through (title, normalised name): the only link the archives have in common.

    `imdb_of_work`: which IMDb title id stands for each work. Default (audit): the first id on record; the v3 layer passes the PRIMARY id, so a
    work with two ids is never matched against the cast list of its secondary id."""
    if imdb_of_work is None:
        imdb_of_work = {w: v[0] for w, v in ((w, s.get("imdb_title", [])) for w, s in ctx.rev.items()) if v}
    names = _person_names(ctx)
    birth = {p: b for p, b in ctx.cinema.execute("SELECT person_id, birth_year FROM person")}
    pnames = {r[0]: r[1:] for r in st.execute("SELECT nconst, name, birth, death, nnorm FROM name")}
    # per title: normalised name -> [(nconst, ordering, category, characters)]
    by_title: dict[str, dict[str, list]] = collections.defaultdict(lambda: collections.defaultdict(list))
    principal_cast_titles: dict[str, int] = collections.Counter()
    for t, ordering, n, cat, job, chars in st.execute("SELECT tconst, ordering, nconst, category, job, characters FROM principal"):
        info = pnames.get(n)
        if info:
            by_title[t][info[3]].append((n, ordering, cat, chars))
            if CATEGORY_TO_ROLE.get(cat) == "cast":
                principal_cast_titles[t] += 1
    for t, d, w in st.execute("SELECT tconst, directors, writers FROM crew"):
        if t not in by_title:
            continue
        for field, cat in ((d, "director"), (w, "writer")):
            for n in L.split_ids(field):
                info = pnames.get(n)
                if info and not any(x[0] == n for x in by_title[t][info[3]]):
                    by_title[t][info[3]].append((n, None, cat, None))
    cast_stats = collections.Counter()
    char_agree = collections.Counter()
    person_hits: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    person_titles: dict[int, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    credits_total = credits_with_imdb_title = credits_title_in_principals = credits_matched = 0
    role_matched: collections.Counter = collections.Counter()
    role_total: collections.Counter = collections.Counter()
    cinema_char = {}
    order_films: set[int] = set()
    cast_films_total: set[int] = set()
    credit_matches: list[tuple] = []  # (credit_id, nconst, ordering, characters, imdb category): used by the v3 layer
    person_flexible: set[int] = set()
    person_with_imdb_credit: set[int] = set()
    for credit_id, w, p, role, character in ctx.cinema.execute("SELECT credit_id, work_id, person_id, role, character_name FROM credit"):
        credits_total += 1
        role_total[role] += 1
        t = imdb_of_work.get(w)
        if not t:
            continue
        credits_with_imdb_title += 1
        person_with_imdb_credit.add(p)
        if role != "cast" or principal_cast_titles.get(t, 0) < 10:
            person_flexible.add(p)  # a credit that a complete IMDb list would have contained
        if role == "cast":
            cast_films_total.add(w)
        titles_map = by_title.get(t)
        if not titles_map:
            continue
        credits_title_in_principals += 1
        hit = None
        for nm in names.get(p, ()):
            for cand in titles_map.get(nm, ()):
                if CATEGORY_TO_ROLE.get(cand[2]) == role or (role == "cast" and CATEGORY_TO_ROLE.get(cand[2]) == "cast"):
                    hit = cand
                    break
            if hit:
                break
        if not hit:
            if role == "cast":
                cast_stats["unmatched_cast_title_with_10_or_more_principal_cast"
                           if principal_cast_titles.get(t, 0) >= 10 else "unmatched_cast_title_with_fewer_than_10_principal_cast"] += 1
            continue
        credits_matched += 1
        credit_matches.append((credit_id, hit[0], hit[1], hit[3], hit[2]))
        role_matched[role] += 1
        person_hits[p][hit[0]] += 1
        person_titles[p][hit[0]].add(t)
        if role == "cast":
            cast_stats["cast_credits_matched"] += 1
            if hit[1] is not None:
                cast_stats["with_ordering"] += 1
                order_films.add(w)
            chars = L.parse_characters(hit[3])
            if chars:
                cast_stats["with_characters"] += 1
                if character:
                    cast_stats["both_have_character"] += 1
                    ok = L.person_norm(character) in {L.person_norm(c) for c in chars} or any(
                        L.person_norm(character) in L.person_norm(c) or L.person_norm(c) in L.person_norm(character) for c in chars)
                    char_agree["agree" if ok else "differ"] += 1
                else:
                    cast_stats["character_new_for_cinema"] += 1
    # person-level tiers
    tiers: collections.Counter = collections.Counter()
    resolved: dict[int, dict] = {}
    nconst_owners: dict[str, set[int]] = collections.defaultdict(set)
    for p, hits in person_hits.items():
        if len(hits) > 1:
            tiers["conflict_several_nconst"] += 1
            resolved[p] = {"tier": "conflict_several_nconst", "nconst": sorted(hits)}
            continue
        n = next(iter(hits))
        info = pnames[n]
        b_c, b_i = birth.get(p), info[1]
        n_titles = len(person_titles[p][n])
        if b_c and b_i and b_c != b_i:
            tier = "conflict_birth_year"
        elif n_titles >= 2 or (b_c and b_i and b_c == b_i):
            tier = "strong"
        else:
            tier = "weak_single_title_no_birth_confirmation"
        tiers[tier] += 1
        resolved[p] = {"tier": tier, "nconst": [n], "titles": n_titles, "birth_cinema": b_c, "birth_imdb": b_i}
        nconst_owners[n].add(p)
    shared = {n: sorted(ps) for n, ps in nconst_owners.items() if len(ps) > 1}
    persons_total = len(names)
    persons_with_imdb_work = len({p for p, in ctx.cinema.execute(
        "SELECT DISTINCT person_id FROM credit WHERE work_id IN (SELECT entity_id FROM external_id WHERE scheme = 'imdb_title')")})
    unresolved = persons_total - len(resolved)
    unresolved_ids = [p for p in names if p not in resolved]
    breakdown = collections.Counter(
        "no_credit_on_a_work_with_imdb_id" if p not in person_with_imdb_credit else
        "only_cast_credits_on_titles_whose_imdb_cast_list_is_full_(10_or_more)" if p not in person_flexible else
        "other_credit_roles_or_short_imdb_lists_(possible_name_or_identity_mismatch)" for p in unresolved_ids)
    new_credit_candidates = collections.Counter()
    # IMDb principal people of cinema titles that no cinema credit matched: possible new credits (names not matched or really new)
    matched_pairs = set()
    for p, titles_by_n in person_titles.items():
        for n, ts in titles_by_n.items():
            for t in ts:
                matched_pairs.add((t, n))
    cinema_titles = {imdb_of_work[w] for w in imdb_of_work}
    for t, ordering, n, cat in st.execute("SELECT tconst, ordering, nconst, category FROM principal"):
        if t in cinema_titles and (t, n) not in matched_pairs and CATEGORY_TO_ROLE.get(cat):
            new_credit_candidates[CATEGORY_TO_ROLE[cat]] += 1
    summary = {
        "credits_total": credits_total, "credits_on_works_with_imdb_id": credits_with_imdb_title,
        "credits_whose_title_has_imdb_principals_or_crew": credits_title_in_principals,
        "credits_matched_to_an_imdb_person": credits_matched, "matched_by_role": dict(role_matched), "credits_by_role": dict(role_total),
        "persons_total": persons_total, "persons_with_a_credit_on_an_imdb_work": persons_with_imdb_work,
        "persons_resolved_by_tier": dict(tiers), "persons_resolved_total": len(resolved), "persons_unresolved": unresolved, "persons_unresolved_breakdown": dict(breakdown),
        "nconst_claimed_by_several_cinema_persons": len(shared),
        "cast_order_and_characters": {**cast_stats, "cast_credits_total": role_total.get("cast", 0),
                                       "films_with_cast_credits_and_imdb_id": len(cast_films_total), "films_that_gain_order": len(order_films),
                                       "character_comparison": dict(char_agree)},
        "imdb_credits_not_matched_to_cinema_by_role": dict(new_credit_candidates),
        "principal_cast_per_title": _distribution(list(principal_cast_titles.values())),
        "method": "title identifier + normalised person name (token set) + compatible role; birth year used only to confirm or contradict",
    }
    candidates = {
        "person_nconst": [{"person_id": p, **v} for p, v in sorted(resolved.items())],
        "nconst_shared": [{"nconst": n, "persons": ps} for n, ps in sorted(shared.items())],
        "_credit_matches": credit_matches,
    }
    return summary, candidates


def _distribution(values: list[int]) -> dict:
    if not values:
        return {}
    values = sorted(values)
    return {"titles": len(values), "min": values[0], "median": values[len(values) // 2], "p90": values[int(len(values) * 0.9)], "max": values[-1],
            "histogram": dict(sorted(collections.Counter(min(v, 10) for v in values).items()))}


# --------------------------------------------------------------------------------------- directors/crew
def crew_check(ctx: Context, st: sqlite3.Connection) -> dict:
    imdb_of_work = {w: v[0] for w, v in ((w, s.get("imdb_title", [])) for w, s in ctx.rev.items()) if v}
    pnames = {n: nn for n, nn in st.execute("SELECT nconst, nnorm FROM name")}
    crew = {t: (d, w) for t, d, w in st.execute("SELECT tconst, directors, writers FROM crew")}
    cin_dir: dict[int, set[str]] = collections.defaultdict(set)
    persons = _person_names(ctx)
    for w, p in ctx.cinema.execute("SELECT work_id, person_id FROM credit WHERE role = 'director'"):
        cin_dir[w] |= persons.get(p, set())
    counts: collections.Counter = collections.Counter()
    for w, t in imdb_of_work.items():
        if ctx.works[w][0] not in ("film", "short", "tv_film"):
            continue
        entry = crew.get(t)
        if entry is None:
            counts["title_not_in_crew_file"] += 1
            continue
        imdb_dirs = {pnames[n] for n in L.split_ids(entry[0]) if n in pnames}
        have = cin_dir.get(w, set())
        if entry[0] and not have:
            counts["imdb_has_directors_cinema_has_none"] += 1
        elif not entry[0] and have:
            counts["cinema_has_directors_imdb_has_none"] += 1
        elif not entry[0] and not have:
            counts["neither_has_directors"] += 1
        elif imdb_dirs & have:
            counts["directors_overlap"] += 1
        else:
            counts["directors_disagree_or_names_unmatched"] += 1
    return dict(counts)


# ---------------------------------------------------------------------------------------- MovieLens
def ml_missing_classification(ctx: Context, st: sqlite3.Connection) -> tuple[dict, list[dict]]:
    titles = _tdict(st)
    have_imdb = set(ctx.ids.get("imdb_title", {}))
    missing = [m for m in ctx.ml if m["imdb"] and m["imdb"] not in have_imdb]
    # candidates already in cinema under another identifier: normalised title + year within one, screen kinds only
    works = ctx.works
    cinema_by_title: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
    for key, ws in ctx.names.items():
        for w in ws:
            kind, year = works[w]
            if kind not in ("episode", "season") and year:
                cinema_by_title[(key, year)].append(w)
    director_names = {w: set() for w in ()}
    rows: list[dict] = []
    for m in missing:
        row = titles.get(m["imdb"])
        if row is None:
            klass, ttype, detail = "non_identificabile_via_imdb", None, {}
        else:
            ttype, ptitle, otitle, adult, start, runtime, genres, pn, on = row
            klass = TYPE_CLASS.get(ttype, "altro")
            detail = {"imdb_title": ptitle, "start": start, "runtime": runtime, "adult": adult, "genres": genres}
            same = []
            for key in {pn, on}:
                for dy in (0, -1, 1):
                    if start:
                        same += cinema_by_title.get((key, start + dy), [])
            if same:
                detail["cinema_candidates_same_title_year"] = sorted(set(same))[:5]
        rows.append({"movie_id": m["movie_id"], "imdb": m["imdb"], "tmdb": m["tmdb"], "ml_title": m["title"], "n_ratings": m["n"], "ml_year": m["year"],
                     "class": klass, "imdb_type": ttype, **detail})
    by_class = collections.Counter(r["class"] for r in rows)
    curve = {}
    for t in MIN_THRESHOLDS:
        sub = [r for r in rows if r["n_ratings"] >= t]
        curve[str(t)] = {"missing": len(sub), **dict(collections.Counter(r["class"] for r in sub))}
    movies = [r for r in rows if r["imdb_type"] == "movie"]
    movie_detail = {
        "movie_total": len(movies),
        "movie_with_cinema_candidate_same_title_and_year": sum(1 for r in movies if r.get("cinema_candidates_same_title_year")),
        "movie_without_cinema_candidate": sum(1 for r in movies if not r.get("cinema_candidates_same_title_year")),
        "movie_runtime_bins": dict(collections.Counter(_runtime_bin(r.get("runtime")) for r in movies)),
        "movie_flagged_adult": sum(1 for r in movies if r.get("adult")),
        "movie_documentary": sum(1 for r in movies if "Documentary" in (r.get("genres") or "")),
        "movie_by_decade": dict(sorted(collections.Counter(_decade(r.get("start")) for r in movies).items())),
        "movie_year_disagrees_with_movielens": sum(1 for r in movies if r.get("start") and r["ml_year"] and abs(r["start"] - r["ml_year"]) > 1),
    }
    by_threshold_new_movies = {}
    for t in MIN_THRESHOLDS:
        sub = [r for r in movies if r["n_ratings"] >= t]
        by_threshold_new_movies[str(t)] = {"movies": len(sub), "without_cinema_candidate": sum(1 for r in sub if not r.get("cinema_candidates_same_title_year"))}
    not_found = [r for r in rows if r["class"] == "non_identificabile_via_imdb"]
    summary = {
        "missing_total": len(rows), "by_class": dict(by_class.most_common()), "by_imdb_type": dict(collections.Counter(r["imdb_type"] or "(not in title.basics)" for r in rows).most_common()),
        "by_threshold": curve, "movies": movie_detail, "movies_by_threshold": by_threshold_new_movies,
        "not_identifiable": {"count": len(not_found), "with_tmdb_id_in_movielens": sum(1 for r in not_found if r["tmdb"]),
                             "by_threshold": {str(t): sum(1 for r in not_found if r["n_ratings"] >= t) for t in MIN_THRESHOLDS},
                             "top_by_ratings": [{"title": r["ml_title"], "imdb": r["imdb"], "n": r["n_ratings"]} for r in sorted(not_found, key=lambda r: -r["n_ratings"])[:10]]},
        "ge50": dict(collections.Counter(r["class"] for r in rows if r["n_ratings"] >= 50)),
        "ge50_movies_without_cinema_candidate": by_threshold_new_movies["50"]["without_cinema_candidate"],
    }
    return summary, rows


def _runtime_bin(minutes: int | None) -> str:
    if not minutes:
        return "unknown"
    return "<40" if minutes < 40 else "40-59" if minutes < 60 else "60-89" if minutes < 90 else "90-119" if minutes < 120 else "120+"


# ---------------------------------------------------------------------------------- Italian pages
SPLIT = re.compile(r"\s*(?:,|;|/|&|<br\s*/?>|\se\s|\sed\s|\sand\s)\s*", re.I)


def page_director_sets(raw: str | None) -> list[str]:
    return [L.person_norm(p) for p in SPLIT.split(raw or "") if p and L.person_norm(p)]


def classify_page(rec: dict, st: sqlite3.Connection, pnames: dict[str, str], crew: dict[str, str | None]) -> tuple[str, str | None, dict]:
    """(tier, chosen tconst, candidates) for one film-infobox page. Tiers: identified_without_plot / dubious / no_candidate."""
    year = rec.get("year")
    keys = {k for k in (util.norm_title(util.strip_qualifier(rec["title"])), util.norm_title(rec.get("original_title") or "")) if k}
    cands: dict[str, tuple] = {}
    if year:
        for key in keys:
            for row in st.execute("SELECT tconst, type, start, pnorm, onorm FROM title WHERE (pnorm = ? OR onorm = ?) AND type IN (%s) AND start BETWEEN ? AND ?"
                                  % ",".join("?" * len(FILMISH)), (key, key, *FILMISH, year - 1, year + 1)):
                cands[row[0]] = row
    pdirs = set(page_director_sets(rec.get("director")))
    good = []
    for t, row in cands.items():
        if row[2] != year:
            continue
        dirs = {pnames[n] for n in L.split_ids(crew.get(t)) if n in pnames}
        if pdirs and dirs & pdirs:
            good.append(t)
    if not cands:
        return "no_candidate", None, cands
    if len(good) == 1:
        return "identified_without_plot", good[0], cands
    return "dubious", None, cands


def italian_pages(ctx: Context, st: sqlite3.Connection) -> tuple[dict, list[dict]]:
    """Rejected film-infobox pages (plot too short / missing): which can enter as 'identified without plot'.

    Tiers (strict, applied in this order):
      identified_without_plot  exactly one IMDb screen title whose year equals the page year AND whose title (primary or original)
                               equals the page title or original title AND whose directors include a director named on the page;
      dubious                  one or more candidates but the three conditions do not all hold uniquely;
      no_candidate             no IMDb title of a film-like type with that title and a year within one.
    Pages whose identifier is already in cinema are reported apart (`already_in_cinema`).

    VALIDATION on ground truth: the same rules are applied to the pages of the RAG catalogue, whose IMDb id is known (`wikipedia_page_id`
    -> `imdb_id`): precision = how often an 'identified' page gets exactly that id; recall = share of those pages that get 'identified'."""
    records = ctx.dump_records()
    if records is None:
        return {"scanned": False}, []
    rejected = ctx.pages["rejected"]
    cinema_imdb = set(ctx.ids.get("imdb_title", {}))
    pnames = {n: nn for n, nn in st.execute("SELECT nconst, nnorm FROM name")}
    crew = {t: d for t, d, _ in st.execute("SELECT tconst, directors, writers FROM crew")}
    known = {r["wikipedia_page_id"]: r["imdb_id"] for r in ctx.v3 if r["wikipedia_page_id"] and r["imdb_id"]}
    out: list[dict] = []
    tiers: collections.Counter = collections.Counter()
    by_type: collections.Counter = collections.Counter()
    truth: collections.Counter = collections.Counter()
    for rec in records:
        if rec["kind"] != "film_page":
            continue
        if rec["page_id"] in known:  # ground-truth pages: not part of the output, only of the validation
            tier, chosen, _ = classify_page(rec, st, pnames, crew)
            truth["pages_with_known_imdb_id"] += 1
            truth[f"tier:{tier}"] += 1
            if tier == "identified_without_plot":
                truth["identified_correct" if chosen == known[rec["page_id"]] else "identified_wrong"] += 1
            continue
        if rec["page_id"] not in rejected:
            continue
        reason = rejected[rec["page_id"]][1]
        tier, chosen, cands = classify_page(rec, st, pnames, crew)
        label = "already_in_cinema" if chosen and chosen in cinema_imdb else tier
        tiers[label] += 1
        if label == "identified_without_plot":
            by_type[cands[chosen][1]] += 1
        out.append({"page_id": rec["page_id"], "title": rec["title"], "year": rec.get("year"), "reason": reason, "tier": label, "tconst": chosen,
                    "imdb_type": cands[chosen][1] if chosen else None, "candidates": sorted(cands)[:5], "page_director": rec.get("director")})
    ident = truth.get("identified_correct", 0) + truth.get("identified_wrong", 0)
    summary = {
        "scanned": True, "rejected_pages_evaluated": len(out), "tiers": dict(tiers),
        "new_identified_by_imdb_type": dict(by_type), "by_reason": {r: dict(collections.Counter(o["tier"] for o in out if o["reason"] == r)) for r in ("plot_too_short", "no_plot_section")},
        "pages_without_year": sum(1 for o in out if not o["year"]),
        "pages_without_director_on_page": sum(1 for o in out if not o["page_director"]),
        "validation_on_known_pages": {**dict(truth), "precision_pct": pct(truth.get("identified_correct", 0), ident),
                                      "recall_pct": pct(ident, truth.get("pages_with_known_imdb_id", 0))},
        "criteria": "see docstring of italian_pages: unique candidate, same year, title match, director match; nothing else is accepted",
    }
    return summary, out


def new_film_estimate(ml_rows: list[dict], page_rows: list[dict]) -> dict:
    """How many NEW feature-length films the two routes would bring, and how much they overlap (by IMDb identifier, IMDb type `movie` on both sides)."""
    ml_movies = {r["imdb"] for r in ml_rows if r["imdb_type"] == "movie" and not r.get("cinema_candidates_same_title_year")}
    page_ident = [r for r in page_rows if r["tier"] == "identified_without_plot" and r.get("tconst")]
    page_movies = {r["tconst"] for r in page_ident if r.get("imdb_type") == "movie"}
    return {"movielens_movies_without_cinema_candidate": len(ml_movies), "italian_pages_identified_movies": len(page_movies),
            "italian_pages_identified_all_types": len({r["tconst"] for r in page_ident}), "in_both_movies": len(ml_movies & page_movies),
            "union_movies": len(ml_movies | page_movies)}


# --------------------------------------------------------------------------------------- the 88 losses
def build_losses(ctx: Context, st: sqlite3.Connection | None = None) -> tuple[dict, list[dict]]:
    """Trace every film that is in a local source but not in cinema, and name the first point at which the build drops it.

    Rules mirror `cinema_db/harness/build/build.py` (read, not run): the film catalogue is imported whole; `series.jsonl` rows are
    skipped when `default_search_eligible` is false and imported WITHOUT identifiers when `ids_reliable` is false; `tv_movies.jsonl`
    rows are imported without identifiers when unreliable; `uncertain.jsonl` and the Wikidata snapshots are never imported by themselves.
    With the IMDb staging file each row also says what IMDb thinks the title is (type, and whether title+year agree with the record)."""
    have = set(ctx.ids.get("imdb_title", {}))
    in_ml = {m["imdb"] for m in ctx.ml if m["imdb"]}
    local = {r["imdb_id"] for r in ctx.v3 if r["imdb_id"]}
    for name in ("series", "tv_movies", "uncertain"):
        local |= {r["imdb"] for r in ctx.s5[name] if r["imdb"]}
    for snap_ in (ctx.film_snap, ctx.series_snap):
        local |= {v for e in snap_["entities"].values() for v in e.get("imdb_title", []) if util.TT.match(v)}
    wanted = local - have  # every IMDb id present in a local source and absent from cinema (the MovieLens subset is flagged)
    sources: dict[str, dict[str, list]] = {k: collections.defaultdict(list) for k in ("v3", "series", "tv_movies", "uncertain")}
    for name in ("series", "tv_movies", "uncertain"):
        for d in util.iter_jsonl(util.S5 / f"{name}.jsonl"):
            ids = d.get("ids") or {}
            t = util.imdb_tt(ids.get("imdb_id"))
            if t in wanted:
                sources[name][t].append({"record_id": d.get("record_id"), "title": d.get("title"), "year": d.get("year"), "class": d.get("catalog_class"),
                                         "eligible": d.get("default_search_eligible"), "ids_reliable": d.get("ids_reliable"), "qid": ids.get("qid"),
                                         "subtype": d.get("subtype"), "flags": d.get("flags")})
    for r in ctx.v3:
        if r["imdb_id"] in wanted:
            sources["v3"][r["imdb_id"]].append({"qid": r["wikidata_id"], "title": r["title"], "year": r["year"]})
    snap: dict[str, list[tuple[str, str, str | None]]] = collections.defaultdict(list)
    for name, s_ in (("film_snapshot", ctx.film_snap), ("series_snapshot", ctx.series_snap)):
        for qid, e in s_["entities"].items():
            for t in e.get("imdb_title", []):
                if t in wanted:
                    snap[t].append((name, qid, e.get("sitelink")))
    film_rejected = {title: reason for title, reason in ctx.pages["rejected"].values()}
    clean_excluded = {(d.get("film") or {}).get("film_id"): (d.get("exclusion") or {}).get("verdict") for d in ctx.pages["excluded"]}
    s5_excluded = {d.get("title"): d.get("reason") for d in util.iter_jsonl(util.S5 / "excluded.jsonl")}
    titles = {}
    if st is not None:
        titles = {r[0]: r[1:] for r in st.execute("SELECT tconst, type, start, pnorm, onorm FROM title")}
    cinema_by_title: dict[str, list[tuple[str, int | None]]] = collections.defaultdict(list)
    for key, ws in ctx.names.items():
        for w in ws:
            if ctx.works[w][0] not in ("episode", "season"):
                cinema_by_title[key].append((ctx.works[w][0], ctx.works[w][1]))
    rows = []
    for t in sorted(wanted):
        if not (sources["v3"].get(t) or sources["series"].get(t) or sources["tv_movies"].get(t) or sources["uncertain"].get(t) or snap.get(t)):
            continue
        trace = {k: sources[k].get(t) for k in sources if sources[k].get(t)}
        if t in snap:
            trace["snapshots"] = [list(x) for x in snap[t]]
        record = (sources["series"].get(t) or sources["tv_movies"].get(t) or sources["uncertain"].get(t) or [None])[0]
        if sources["v3"].get(t):
            point, cause = "film_catalogue", "in_film_catalogue_but_identifier_not_in_cinema"
        elif sources["series"].get(t):
            r = sources["series"][t][0]
            if not r["eligible"]:
                point, cause = "series(): default_search_eligible false", f"series_not_imported:{r['class']}"
            elif not r["ids_reliable"]:
                point, cause = "series(): ids_reliable false -> imported without identifiers", "series_imported_without_identifiers"
            else:
                point, cause = "series()", "series_imported_but_identifier_missing_unexplained"
        elif sources["tv_movies"].get(t):
            r = sources["tv_movies"][t][0]
            point, cause = ("tv_movies(): ids_reliable false -> imported without identifiers", "tv_movie_imported_without_identifiers") if not r["ids_reliable"] else ("tv_movies()", "tv_movie_identifier_missing_unexplained")
        elif sources["uncertain"].get(t):
            point, cause = "never read: uncertain.jsonl is not a build input", "series_catalogue_uncertain_records_not_imported"
        else:
            point, cause = "never read: snapshot entities are only used for records of the catalogues", "wikidata_snapshot_entity_without_catalogue_record"
            qid_title = next(((q, tt) for _, q, tt in snap[t]), (None, None))
            why = film_rejected.get(qid_title[1] or "") or None
            if why:
                point, cause = "film extraction: page rejected before the catalogue", f"snapshot_entity_page_rejected_by_film_extraction:{why}"
            elif clean_excluded.get(qid_title[0]):
                point, cause = "film cleaning: excluded from the catalogue", f"snapshot_entity_excluded_in_cleaning:{clean_excluded[qid_title[0]]}"
            elif (qid_title[1] or "") in s5_excluded:
                point, cause = "series catalogue: page excluded", f"snapshot_entity_excluded_by_series_catalogue:{s5_excluded[qid_title[1]]}"
        info = titles.get(t)
        row = {"imdb": t, "in_movielens": t in in_ml, "cause": cause, "exclusion_point": point, "trace": trace, "imdb_type": info[0] if info else None}
        if info and record:
            ok_title = util.norm_title(record.get("title") or "") in (info[2], info[3]) or util.norm_title(util.strip_qualifier(record.get("title") or "")) in (info[2], info[3])
            ok_year = bool(info[1] and record.get("year") and abs(int(record["year"]) - info[1]) <= 1) if str(record.get("year") or "").isdigit() else False
            row["imdb_confirms_record"] = {"title": ok_title, "year": ok_year}
            row["work_present_in_cinema_without_identifier"] = bool(cinema_by_title.get(util.norm_title(util.strip_qualifier(record.get("title") or ""))))
        rows.append(row)
    ml_rows = [r for r in rows if r["in_movielens"]]
    def tally(sub):
        return dict(collections.Counter(r["cause"] for r in sub).most_common())
    summary = {"identifiers_in_local_sources_not_in_cinema": len(rows), "of_which_in_movielens": len(ml_rows),
               "movielens_by_cause": tally(ml_rows), "all_by_cause": tally(rows),
               "all_by_exclusion_point": dict(collections.Counter(r["exclusion_point"] for r in rows).most_common()),
               "movielens_by_imdb_type": dict(collections.Counter(r["imdb_type"] or "(not in title.basics)" for r in ml_rows).most_common()),
               "imdb_confirms_title_and_year": {c: sum(1 for r in rows if r["cause"] == c and r.get("imdb_confirms_record", {}).get("title") and r.get("imdb_confirms_record", {}).get("year"))
                                                for c in sorted({r["cause"] for r in rows})},
               "work_present_without_identifier": {c: sum(1 for r in rows if r["cause"] == c and r.get("work_present_in_cinema_without_identifier"))
                                                   for c in sorted({r["cause"] for r in rows})},
               "note": "build report for comparison: series_not_imported:franchise_page_mixed_media 2032; series_with_unreliable_ids 754 (all series rows, not only those with an IMDb id)"}
    return summary, rows



# ----------------------------------------------------------------------------------- dubious pages
def _page_features(rec: dict, st: sqlite3.Connection, pnames: dict[str, str], crew: dict[str, str | None]) -> dict:
    """Why a page is not 'identified': the candidates and the facts that fail. Pure given the staging file."""
    tier, chosen, cands = classify_page(rec, st, pnames, crew)
    year = rec.get("year")
    pdirs = set(page_director_sets(rec.get("director")))
    exact = [t for t, row in cands.items() if row[2] == year]
    with_dir = []
    for t in exact:
        dirs = {pnames[n] for n in L.split_ids(crew.get(t)) if n in pnames}
        if pdirs and dirs & pdirs:
            with_dir.append(t)
    if not pdirs:
        reason = "no_director_on_page"
    elif not with_dir:
        reason = "director_on_page_matches_no_candidate" if exact else "only_candidates_with_year_off_by_one"
    elif len(with_dir) > 1:
        reason = "several_candidates_with_a_matching_director"
    else:
        reason = "single_match"
    return {"tier": tier, "chosen": chosen, "cands": cands, "exact": exact, "with_director": with_dir, "reason": reason, "page_directors": sorted(pdirs)}


def unique_title_year_rule(features: dict) -> str | None:
    """Rule R2 (no director needed): exactly one IMDb screen title within a year of the page year, and it has the page's exact year.
    Returns its tconst or None. Applied only if its precision on pages with a KNOWN IMDb id is at least `MIN_RULE_PRECISION`."""
    if len(features["cands"]) == 1 and len(features["exact"]) == 1:
        return features["exact"][0]
    return None


MIN_RULE_PRECISION = 99.0  # operational choice, stated in the report: measured on pages whose IMDb id is already known


def dubious_pages(ctx: Context, st: sqlite3.Connection) -> tuple[dict, list[dict], list[dict]]:
    """(summary, dubious archive rows, pages recovered by the calibrated rule). Nothing is inserted anywhere."""
    records = ctx.dump_records()
    if records is None:
        return {"scanned": False}, [], []
    rejected = ctx.pages["rejected"]
    cinema_imdb = set(ctx.ids.get("imdb_title", {}))
    pnames = {n: nn for n, nn in st.execute("SELECT nconst, nnorm FROM name")}
    crew = {t: d for t, d, _ in st.execute("SELECT tconst, directors, writers FROM crew")}
    known = {r["wikipedia_page_id"]: r["imdb_id"] for r in ctx.v3 if r["wikipedia_page_id"] and r["imdb_id"]}
    truth: collections.Counter = collections.Counter()
    for rec in records:
        if rec["kind"] == "film_page" and rec["page_id"] in known:
            f = _page_features(rec, st, pnames, crew)
            if f["tier"] == "dubious":
                truth["known_pages_dubious"] += 1
                t = unique_title_year_rule(f)
                if t:
                    truth["rule_applies"] += 1
                    truth["rule_correct" if t == known[rec["page_id"]] else "rule_wrong"] += 1
    precision = pct(truth.get("rule_correct", 0), truth.get("rule_applies", 0))
    accept = precision >= MIN_RULE_PRECISION and truth.get("rule_applies", 0) >= 100
    archive, recovered = [], []
    reasons: collections.Counter = collections.Counter()
    for rec in records:
        if rec["kind"] != "film_page" or rec["page_id"] not in rejected or not rec.get("year"):
            continue
        f = _page_features(rec, st, pnames, crew)
        if f["tier"] != "dubious":
            continue
        chosen = unique_title_year_rule(f) if accept else None
        base = {"page_id": rec["page_id"], "title": rec["title"], "year": rec.get("year"), "original_title": rec.get("original_title"),
                "page_director": rec.get("director"), "rejection": rejected[rec["page_id"]][1], "reason": f["reason"],
                "candidates": [{"tconst": t, "type": row[1], "year": row[2]} for t, row in sorted(f["cands"].items())][:8]}
        if chosen and chosen not in cinema_imdb:
            recovered.append({**base, "tconst": chosen, "rule": "unique_title_year", "imdb_type": f["cands"][chosen][1]})
        else:
            archive.append(base)
        reasons[f["reason"]] += 1
    summary = {"scanned": True, "dubious_pages": len(archive) + len(recovered), "by_reason": dict(reasons.most_common()),
               "rule_unique_title_year": {**dict(truth), "precision_pct": precision, "required_precision_pct": MIN_RULE_PRECISION, "accepted": accept},
               "recovered_by_rule": len(recovered), "left_in_archive": len(archive),
               "recovered_by_imdb_type": dict(collections.Counter(r["imdb_type"] for r in recovered))}
    return summary, archive, recovered
