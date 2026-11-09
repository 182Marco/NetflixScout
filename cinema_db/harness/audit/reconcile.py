"""Classification of the identifier conflicts and suspected duplicates found by A0/A1. NOTHING is merged or modified.

Inputs: the A1 candidate files, the cinema database (read-only) and the IMDb staging file. Output: one JSONL per family under
`cinema_db/data/audit_a1/reconciliation/` plus a summary. Each row names the entities, identifiers, the evidence found, a proposed
class and the risk of a wrong merge. Merges, if approved, belong to a NEW build with a canonical-entity map and before/after checks.
"""
from __future__ import annotations

import collections
import sqlite3
from pathlib import Path

from . import imdb_load as L
from . import util
from .sections import Context


def _chunks(items: list, size: int = 400):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _persons(ctx: Context, ids: set[int]) -> dict[int, dict]:
    c = ctx.cinema
    out: dict[int, dict] = {p: {"person_id": p} for p in ids}
    for chunk in _chunks(sorted(ids)):
        marks = ",".join("?" * len(chunk))
        for p, name in c.execute(f"SELECT entity_id, name FROM entity_name WHERE is_primary = 1 AND entity_id IN ({marks})", chunk):
            out[p]["name"] = name
        for p, b, d in c.execute(f"SELECT person_id, birth_year, death_year FROM person WHERE person_id IN ({marks})", chunk):
            out[p]["birth"], out[p]["death"] = b, d
        for p, v in c.execute(f"SELECT entity_id, value FROM external_id WHERE scheme = 'wikidata' AND entity_id IN ({marks})", chunk):
            out[p]["qid"] = v
        credits = collections.defaultdict(set)
        for p, w, role in c.execute(f"SELECT person_id, work_id, role FROM credit WHERE person_id IN ({marks})", chunk):
            credits[p].add((w, role))
        for p in chunk:
            out[p]["credits"] = credits.get(p, set())
    return out


def classify_shared_nconst(ctx: Context, st: sqlite3.Connection, shared: list[dict]) -> list[dict]:
    pids = {p for r in shared for p in r["persons"]}
    info = _persons(ctx, pids)
    rows = []
    for r in shared:
        n = r["nconst"]
        nm = st.execute("SELECT name, birth, death FROM name WHERE nconst = ?", (n,)).fetchone()
        imdb_birth = nm[1] if nm else None
        ps = [info[p] for p in r["persons"]]
        same_work_role = any(a["credits"] & b["credits"] for i, a in enumerate(ps) for b in ps[i + 1:])
        same_work = any({w for w, _ in a["credits"]} & {w for w, _ in b["credits"]} for i, a in enumerate(ps) for b in ps[i + 1:])
        matching = [p["person_id"] for p in ps if p.get("birth") and imdb_birth and p["birth"] == imdb_birth]
        contradicting = [p["person_id"] for p in ps if p.get("birth") and imdb_birth and p["birth"] != imdb_birth]
        births = {p.get("birth") for p in ps} - {None}
        if matching and contradicting:
            cls, risk, action = "id_belongs_to_one_person_birth_year_decides", "high", f"attach {n} to person {matching[0]} only; the others stay without this id (homonyms or wrongly matched)"
        elif contradicting and not matching:
            cls, risk, action = "id_probably_wrong_for_all_birth_year_contradicts", "high", "attach to none; keep as candidate"
        elif same_work_role and len(births) <= 1:
            cls, risk, action = "duplicate_probable_same_person_two_entities", "medium", "merge candidate (new build, canonical map); attach the id to the survivor"
        elif same_work and len(births) <= 1:
            cls, risk, action = "duplicate_possible_shared_work_other_role", "medium", "keep both; attach to none until a second proof"
        else:
            cls, risk, action = "homonym_or_split_no_proof", "high", "keep both; attach to none"
        rows.append({"nconst": n, "imdb_name": nm[0] if nm else None, "imdb_birth": imdb_birth,
                     "entities": [{"person_id": p["person_id"], "name": p.get("name"), "qid": p.get("qid"), "birth": p.get("birth"), "credits": len(p["credits"])} for p in ps],
                     "evidence": {"same_work_and_role": same_work_role, "same_work": same_work, "birth_matches_imdb": matching, "birth_contradicts_imdb": contradicting},
                     "class": cls, "merge_risk": risk, "proposed_action": action})
    return rows


def _core(title: str) -> str:
    """Normalised title without a leading article, so 'The Littl' Bits' and 'Littl' Bits' compare equal."""
    words = util.norm_title(title).split()
    return " ".join(words[1:] if words and words[0] in ("the", "a", "an", "il", "lo", "la", "le", "les", "el", "der", "die", "das") and len(words) > 1 else words)


def classify_double_imdb(ctx: Context, st: sqlite3.Connection, doubles: list[dict]) -> list[dict]:
    ml = {m["imdb"]: m for m in ctx.ml if m["imdb"]}
    snap_multi = collections.defaultdict(set)
    for s in (ctx.film_snap, ctx.series_snap):
        for q, e in s["entities"].items():
            for v in e.get("imdb_title", []):
                snap_multi[q].add(v)
    qid_of = {w: next(iter(s.get("wikidata", [])), None) for w, s in ctx.rev.items()}
    rows = []
    for d in doubles:
        details = []
        for t in d["imdb_ids"]:
            r = st.execute("SELECT type, ptitle, start, runtime, pnorm, onorm FROM title WHERE tconst = ?", (t,)).fetchone()
            rating = st.execute("SELECT votes FROM rating WHERE tconst = ?", (t,)).fetchone()
            details.append({"imdb": t, "known_to_imdb": bool(r), "type": r[0] if r else None, "title": r[1] if r else None, "year": r[2] if r else None,
                            "runtime": r[3] if r else None, "votes": rating[0] if rating else None, "in_movielens": t in ml, "movielens_votes": ml[t]["n"] if t in ml else None})
        known = [x for x in details if x["known_to_imdb"]]
        qid = qid_of.get(d["work_id"])
        both_in_wikidata = bool(qid and set(d["imdb_ids"]) <= snap_multi.get(qid, set()))
        if len(known) < len(details):
            cls, risk, action = "stale_id_one_unknown_to_imdb", "low", "keep the id IMDb knows as primary; keep the other as non-primary historical id"
        else:
            titles = {_core(x["title"] or "") for x in known}
            years = {x["year"] for x in known}
            types = {x["type"] for x in known}
            if len(titles) == 1 and len(years) == 1 and len(types) == 1:
                cls, risk, action = "imdb_has_two_entries_same_title_year_type", "medium", "keep both ids on the work (primary = the one with more votes); do not create a second work"
            elif len(titles) == 1:
                cls, risk, action = "same_title_different_year_or_type", "medium", "check whether the work conflates two releases; keep both ids, no split without proof"
            else:
                cls, risk, action = "different_titles_possible_conflation_of_two_works", "high", "do not merge anything; candidate for a SPLIT of the work (new build)"
        rows.append({"work_id": d["work_id"], "kind": d["kind"], "year": d["year"], "wikidata": qid, "imdb_ids": d["imdb_ids"], "details": details,
                     "evidence": {"all_ids_on_the_same_wikidata_item": both_in_wikidata}, "class": cls, "merge_risk": risk, "proposed_action": action})
    return rows


def classify_person_pairs(ctx: Context, resolved: dict[int, dict], pairs: list[dict]) -> list[dict]:
    pids = {p for r in pairs for p in r["persons"]}
    info = _persons(ctx, pids)
    rows = []
    for r in pairs:
        a, b = r["persons"]
        ia, ib = info[a], info[b]
        na, nb = (resolved.get(a) or {}).get("nconst"), (resolved.get(b) or {}).get("nconst")
        tier_a, tier_b = (resolved.get(a) or {}).get("tier"), (resolved.get(b) or {}).get("tier")
        shared = sorted(ia["credits"] & ib["credits"])[:5]
        birth_conflict = bool(ia.get("birth") and ib.get("birth") and ia["birth"] != ib["birth"])
        if na and nb and na == nb:
            cls, risk, action = "duplicate_confirmed_by_imdb_same_person_id", "low", "merge candidate in a new build; survivor = the entity with a birth year, else more credits"
        elif na and nb and na != nb and "conflict_several_nconst" not in (tier_a, tier_b):
            cls, risk, action = "homonym_distinct_imdb_people", "high", "do NOT merge: IMDb knows two different people"
        elif birth_conflict:
            cls, risk, action = "homonym_birth_years_differ", "high", "do NOT merge"
        elif shared:
            cls, risk, action = "duplicate_probable_same_name_same_role_same_work", "medium", "merge candidate after a second proof (a shared id or a birth year)"
        else:
            cls, risk, action = "undetermined", "high", "keep both"
        rows.append({"persons": [a, b], "name": r.get("name"), "qids": [ia.get("qid"), ib.get("qid")], "birth_years": [ia.get("birth"), ib.get("birth")],
                     "imdb_ids": [na, nb], "imdb_tiers": [tier_a, tier_b], "credits": [len(ia["credits"]), len(ib["credits"])], "shared_credits": [list(x) for x in shared],
                     "class": cls, "merge_risk": risk, "proposed_action": action})
    return rows


def run(ctx: Context, staging: Path, a1_dir: Path) -> dict:
    st = sqlite3.connect(f"file:{staging}?mode=ro", uri=True)
    out_dir = a1_dir / "reconciliation"
    shared = list(util.iter_jsonl(a1_dir / "candidates_nconst_shared.jsonl"))
    doubles = list(util.iter_jsonl(a1_dir / "candidates_double_imdb.jsonl"))
    resolved = {r["person_id"]: r for r in util.iter_jsonl(a1_dir / "candidates_person_nconst.jsonl")}
    pairs = [r for r in util.iter_jsonl(util.OUT_DIR / "candidates_person_pairs.jsonl") if r["class"] == "same_person_candidate_strong_shared_work_and_role"]
    families = {
        "shared_nconst": classify_shared_nconst(ctx, st, shared),
        "double_imdb_id": classify_double_imdb(ctx, st, doubles),
        "person_pairs_strong": classify_person_pairs(ctx, resolved, pairs),
    }
    summary: dict = {}
    for name, rows in families.items():
        util.write_jsonl(out_dir / f"{name}.jsonl", rows)
        summary[name] = {"cases": len(rows), "by_class": dict(collections.Counter(r["class"] for r in rows).most_common()),
                         "by_merge_risk": dict(collections.Counter(r["merge_risk"] for r in rows).most_common())}
    summary["note"] = "classification and proposal only: no entity, identifier or relation was modified"
    util.write_json(out_dir / "summary.json", summary)
    return summary
