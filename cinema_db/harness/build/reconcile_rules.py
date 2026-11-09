"""Pure decision rules of the phase-9 reconciliation (owner decisions of 2026-11-08). No I/O: the build gathers the facts, these functions decide.

Every rule is deliberately conservative: when a fact is missing the answer is "do not act" and the case stays visible as a candidate or in the
archive of held titles. Nothing here merges by name alone.
"""
from __future__ import annotations

import re

from cinema_db.harness.build import title_keys as TK

FILM_LIKE_KINDS = ("film", "short", "tv_film")
RUNTIME_FAR_MIN = 15  # two records of "the same" film whose runtimes differ by more than this are not the same film
UNIQUE_RULE_CONFLICT_REASON = "director_on_page_matches_no_candidate"


def primary_imdb_id(candidates: list[dict]) -> str:
    """The primary IMDb title id among several ids of one work.

    Each candidate is {"tconst", "known" (IMDb has a record), "title_match" (IMDb title equals a name of the work), "votes"}.
    Order: known to IMDb, then title equal to the work's name, then more votes, then the lexicographically smaller id. Independent of the input order."""
    return min(candidates, key=lambda c: (not c["known"], not c["title_match"], -(c["votes"] or 0), c["tconst"]))["tconst"]


def merge_check(imdb_birth: int | None, imdb_death: int | None, a: dict, b: dict, shared_credit: bool) -> tuple[bool, str]:
    """May two cinema persons that resolved to the SAME IMDb person be treated as one? `a`/`b`: {"birth", "death"} (years or None).

    The shared IMDb id alone is no evidence (both were matched to it through the same work and name). What decides: a credit on the same work
    and role, an IMDb birth year that no person contradicts, equal birth years if both are known, and no death year IMDb does not confirm."""
    if not shared_credit:
        return False, "no_shared_credit_with_the_same_role"
    if imdb_birth is None:
        return False, "imdb_birth_unknown"
    for p in (a, b):
        if p["birth"] is not None and abs(p["birth"] - imdb_birth) > 1:
            return False, "birth_contradicts_imdb"
    if a["birth"] is None and b["birth"] is None:
        return False, "no_birth_year_to_confirm"
    if a["birth"] is not None and b["birth"] is not None and a["birth"] != b["birth"]:
        return False, "birth_years_differ"
    for p in (a, b):
        if p["death"] is not None and (imdb_death is None or p["death"] != imdb_death):
            return False, "death_contradicts_imdb"
    return True, "ok"


def merge_survivor(a: dict, b: dict) -> tuple[int, int]:
    """(survivor, merged) person ids: the one with a birth year, else more credits, else the lower id. Persons: {"id", "birth", "credits"}."""
    best = max((a, b), key=lambda p: (p["birth"] is not None, p["credits"], -p["id"]))
    other = b if best is a else a
    return best["id"], other["id"]


def shared_id_owner(row: dict, imdb_death: int | None, person_deaths: dict[int, int | None], persons_with_imdb_id: set[int]) -> int | None:
    """The one person who owns an IMDb id claimed by several cinema persons, or None.

    `row` is a classified shared-id case. The id goes to a person only if their birth year equals IMDb's, EVERY other claimant has a known and
    different birth year (so the others are certainly someone else), the death year (if both known) agrees, and they carry no other IMDb id."""
    if row.get("class") != "id_belongs_to_one_person_birth_year_decides":
        return None
    matching = row["evidence"]["birth_matches_imdb"]
    if len(matching) != 1:
        return None
    owner = matching[0]
    if any(e["person_id"] != owner and e.get("birth") is None for e in row["entities"]):
        return None
    if len(row["evidence"]["birth_contradicts_imdb"]) != len(row["entities"]) - 1:
        return None
    death = person_deaths.get(owner)
    if death is not None and imdb_death is not None and death != imdb_death:
        return None
    if owner in persons_with_imdb_id:
        return None
    return owner


def release_class(candidate_kinds: list[str], same_director: bool, checks: list[dict]) -> str | None:
    """Is a title held back for "same title and year as an existing work" a DIFFERENT work? Returns the proof class or None (stay held).

    A: every existing candidate is not a film-like work (a series, an episode...): a different kind of work.
    Otherwise, if the directors agree the title stays held; else EVERY film-like candidate must carry another IMDb id that IMDb knows and
    differ from the held title either by IMDb directors (both known, disjoint: B) or by runtime (both known, far apart: B2).
    `checks`: one dict per film-like candidate {"other_id_known", "directors_disjoint", "runtime_far"}."""
    film_like = [k for k in candidate_kinds if k in FILM_LIKE_KINDS]
    if not film_like:
        return "A_existing_work_is_not_film_like"
    if same_director or not checks:
        return None
    verdicts = []
    for chk in checks:
        if not chk["other_id_known"]:
            return None
        if chk["directors_disjoint"]:
            verdicts.append("B_other_imdb_id_and_disjoint_imdb_directors")
        elif chk["runtime_far"]:
            verdicts.append("B2_other_imdb_id_and_runtime_far")
        else:
            return None
    return "B_other_imdb_id_and_disjoint_imdb_directors" if "B_other_imdb_id_and_disjoint_imdb_directors" in verdicts else verdicts[0]


def identification_for_rule(page_reason: str) -> str:
    """Reliability label of a work entered by the unique-title rule: a page that names a director IMDb does not list for the only candidate is
    a separate, weaker stratum (measured: shorts 2.9 % wrong against 0 % when the page names no director)."""
    return "imdb_title_year_unique_director_mismatch" if page_reason == UNIQUE_RULE_CONFLICT_REASON else "imdb_title_year_unique"


WEAK_IDENTIFICATIONS = ("imdb_title_year_unique", "imdb_title_year_unique_director_mismatch")


def movielens_title_keys(title: str) -> set[str]:
    """Comparable forms of a MovieLens title ("Cidade de Deus (City of God) (2002)", "Kingdom, The (1994)"): the whole title, each parenthesised alternative and the title without them."""
    base = re.sub(r"\s*\(\d{4}\)\s*$", "", title or "")
    parts = [base, re.sub(r"\s*\([^()]*\)", "", base), *re.findall(r"\(([^()]*)\)", base)]
    keys: set[str] = set()
    for part in parts:
        keys |= TK.title_keys(part)
    return keys


def movielens_confirms_identity(ml_entries: list[tuple], imdb_titles: list[str | None], imdb_year: int | None) -> bool:
    """Is the IMDb id that MovieLens gives for a film consistent with the IMDb record itself? Yes if a MovieLens title (any form) equals an IMDb title
    (primary or original, in its own script) and the years differ by at most one. `ml_entries`: (movie_id, title, year). An English translation that matches
    neither is NOT consistent: the link is then not used to confirm anything."""
    imdb_keys: set[str] = set()
    for t in imdb_titles:
        imdb_keys |= TK.title_keys(t)
    return any(movielens_title_keys(title) & imdb_keys and year and imdb_year and abs(year - imdb_year) <= 1 for _id, title, year in ml_entries)


def weak_page_replaces_movielens(page_identification: str, ml_confirms: bool) -> bool:
    """A weak source never lowers a more reliable classification already acquired: a page identified only by the unique-title rule (with or without a
    director conflict) replaces the MovieLens entry only when MovieLens' own title and year do not agree with the IMDb record."""
    return not (page_identification in WEAK_IDENTIFICATIONS and ml_confirms)
