"""Descriptions of the v3 additions (tables, columns, public views). Kept apart from `schema_notes.py`, which describes the runtime v2 schema and must not
know tables that file does not have. `apply(N)` adds them in memory for the v3 map (`generate_v3.py`) and for the v3 policy (`generate.py --v3`)."""
from __future__ import annotations

from contextlib import contextmanager

from cinema_db import schema_v3 as V3

GROUP = {"work_rating": "work", "work_status": "work", "external_id_candidate": "entity", "entity_claim": "provenance", "entity_canonical": "entity"}
GROUP_ML = {"ml_movie": "work", "ml_genre": "work", "work_ml_genre": "work", "work_tag": "work"}
COLUMNS = {
    "work_rating.work_id": "The rated work.", "work_rating.source_id": "Who rated: IMDb voters, MovieLens users, later critics (a row of `source`).",
    "work_rating.value": "The rating on the source's own scale.", "work_rating.scale_max": "Top of that scale (10 for IMDb, 5 for MovieLens).",
    "work_rating.vote_count": "How many votes the value summarises.", "work_rating.audience": "`audience` (viewers) or `critics`.",
    "work_rating.as_of": "Date of the data (IMDb: acquisition date of the dataset; MovieLens: last rating in the dataset).",
    "work_rating.source_ref": "The source's own identifier for the rated item (IMDb tconst, MovieLens id).",
    "entity_claim.entity_id": "The entity the value belongs to.",
    "entity_claim.field": "Which field: kind, release_year, release_date, runtime_min, imdb_title_type (lost a priority decision); imdb_alt_* (what IMDb says about a SECONDARY id of the work, source_ref = that id); imdb_title_previous_primary; reconciliation_released_hold; imdb_person_possibly_existing_person (new IMDb person that is only a candidate of an existing one).",
    "entity_claim.value": "The valid value that did NOT win the priority decision, as text.", "entity_claim.source_id": "The source that stated this value.",
    "entity_claim.source_ref": "The source's reference for it.", "entity_claim.retrieved_at": "When it was acquired, when known.",
    "external_id_candidate.entity_id": "The entity the identifier is suspected for.", "external_id_candidate.scheme": "Identifier scheme (imdb_name, imdb_title).",
    "external_id_candidate.value": "The suspected identifier. Never used as a join key.",
    "external_id_candidate.tier": "Why it was not attached: weak match, conflict, shared by several entities, name and birth year only, unconfirmed record, episode number only.",
    "external_id_candidate.evidence": "Short text with the evidence found.", "external_id_candidate.source_id": "The source that suggested the identifier.",
    "work_status.work_id": "The work.", "work_status.entry_route": "How the work entered: the original catalogues, one of the IMDb routes, or `imdb_episode` (an IMDb episode of a series that already had episodes).",
    "work_status.identification": "How reliably it was identified: catalogue, IMDb id given by MovieLens, title+year+director confirmed, `imdb_title_year_unique` (unique title within a year), `imdb_title_year_unique_director_mismatch` (same rule, but the Italian page names a director IMDb does not list: NOT a verified identity), type confirmed, or `imdb_episode_parent_id` (episode linked to its series by IMDb ids).", "work_status.plot_status": "`with_plot` (RAG catalogue) or `without_plot` (Italian page too short); empty when not tracked.",
    "entity_canonical.entity_id": "The entity that is the SAME real person as canonical_entity_id (never deleted: rows, credits and ids stay).",
    "entity_canonical.canonical_entity_id": "The surviving person the public views show instead.", "entity_canonical.reason": "Why the two are one person.",
    "entity_canonical.evidence": "JSON: the IMDb id, IMDb birth/death years and the shared credits.", "entity_canonical.source_id": "The source that decided it.",
    "work_status.completeness": "`rich` (director, cast, genre and runtime), `basic` (some of them) or `skeleton` (none).",
}



COLUMNS_ML = {
    "ml_movie.movie_id": "MovieLens' own id of the film.", "ml_movie.imdb_id": "IMDb title id MovieLens gives for the film (null when it gives none).",
    "ml_movie.ml_title": "Title as MovieLens writes it (a leading article can be at the end: 'Matrix, The').", "ml_movie.ml_year": "Year in the MovieLens title.",
    "ml_movie.n_ratings": "How many MovieLens users rated the film (0 = none).", "ml_movie.avg_rating": "Mean rating on the MovieLens scale 1-5 (null when nobody rated it).",
    "ml_movie.work_id": "The catalogue work this film is; null when the film is not in the catalogue (then `reason` says why).",
    "ml_movie.reason": "Why the film is not in the catalogue, from a closed list of verifiable causes (a non-film type of IMDb, adult, no year, held as a possible duplicate, identifier unknown, episode not confirmed...).",
    "ml_genre.ml_genre_id": "Key.", "ml_genre.name": "MovieLens genre name (Action, Sci-Fi, Film-Noir...).",
    "work_ml_genre.work_id": "The work.", "work_ml_genre.ml_genre_id": "A MovieLens genre of the work.",
    "work_tag.tag_norm": "The tag users gave, normalised (lower case, single spaces).", "work_tag.work_id": "The tagged work.", "work_tag.n_users": "How many distinct MovieLens users gave this tag to the work.",
}
VIEWS_ML = {
    "v_ml_movie": "MovieLens films with their rating (mean 1-5 and number of ratings) and, when the film is in the catalogue, the work it is. status=excluded rows have no work and say why (reason). Filter rankings on status='in_catalogue'.",
    "v_ml_genre": "MovieLens genres of a work (its own list, NOT the genres of v_work_genre).",
    "v_work_tag": "MovieLens tags of a work with the number of distinct users who gave each.",
}
VIEW_COLUMNS_ML = {
    "v_ml_movie": {
        "movie_id": ("integer", "MovieLens id of the film."), "work_id": ("integer", "Catalogue work (null when excluded)."), "work_title": ("text", "Primary title of the work."),
        "work_year": ("integer", "Release year of the work."), "work_kind": ("text", "Kind of the work (film, short, tv_film, miniseries...)."),
        "imdb_id": ("text", "IMDb id given by MovieLens."), "ml_title": ("text", "Title as MovieLens writes it."), "ml_year": ("integer", "Year in the MovieLens title."),
        "avg_rating": ("real", "MovieLens mean rating, scale 1-5."), "n_ratings": ("integer", "Number of MovieLens ratings."),
        "status": ("text", "in_catalogue or excluded."), "reason": ("text", "Why excluded (null when in the catalogue)."),
    },
    "v_ml_genre": {"work_id": ("integer", "The work."), "genre": ("text", "MovieLens genre.")},
    "v_work_tag": {"work_id": ("integer", "The work."), "tag": ("text", "Normalised tag."), "n_users": ("integer", "Distinct MovieLens users who gave it.")},
}

# Tables of the v3 file a full scan of which twice in one statement is refused (see executor._check_plan).
LARGE_TABLES_V3: tuple[str, ...] = ()
LARGE_TABLES_ML = ("work_tag", "work_ml_genre")

VIEWS = {
    "v_work_status": "How reliably each work was identified: `identity_level` is verified, rule_based or uncertain. Use it to keep uncertain identities apart from verified ones.",
    "v_work_rating": "Ratings of works, one row per work and source (IMDb viewers, MovieLens users): value on the source's own scale, number of votes, date of the data. Never averaged or converted.",
    "v_entity_claim": "Provenance: values that did not become the main value of a work or person (alternative year, runtime, kind), what IMDb says about a secondary id, and why an identity is as it is.",
    "v_external_id_candidate": "Identifiers suspected for an entity but NOT attached (weak or conflicting evidence): visible, never a join key.",
    "v_entity_canonical": "Persons recorded as the same human: the merged person, the canonical person that the other views show, and the evidence. Empty rows mean no merge.",
}
_WORK_REF = {"work_id": ("integer", "Work key."), "work_title": ("text", "Primary title of the work."), "work_year": ("integer", "Release year of the work."),
             "work_kind": ("text", "Kind of the work (film, series, season, episode...).")}
VIEW_COLUMNS = {
    "v_work_status": {
        **_WORK_REF, "entry_route": ("text", "How the work entered: catalogue, imdb_movielens, imdb_itwiki_page, imdb_itwiki_page_rule, imdb_recovered_mixed_page or imdb_episode."),
        "identification": ("text", "Detailed identification label (see work_status)."),
        "identity_level": ("text", "verified (catalogue, MovieLens id, title+year+director, type, episode by ids), rule_based (unique title within a year) or uncertain (that rule, but the page names a director IMDb does not list)."),
        "plot_status": ("text", "with_plot, without_plot or empty."), "completeness": ("text", "rich, basic or skeleton."),
    },
    "v_work_rating": {
        **_WORK_REF, "source": ("text", "Who rated: imdb-datasets or movielens-32m-aggregates."), "audience": ("text", "audience (viewers) or critics."),
        "rating": ("real", "The rating on the source's own scale."), "scale_max": ("real", "Top of that scale (10 for IMDb, 5 for MovieLens)."),
        "vote_count": ("integer", "How many votes the rating summarises."), "as_of": ("text", "Date of the data."),
    },
    "v_entity_claim": {
        "entity_id": ("integer", "The work or person the value belongs to."), "entity_type": ("text", "work or person."), "name": ("text", "Primary name of the entity."),
        "field": ("text", "Which field or fact (kind, release_year, runtime_min, imdb_alt_*, identity_confirmed_by, wikipedia_it_page_not_attached, imdb_person_possibly_existing_person...)."),
        "value": ("text", "The value, as text."), "source": ("text", "The source that stated it."), "source_ref": ("text", "The source's reference (an IMDb id, a page id, a MovieLens id)."),
        "retrieved_at": ("text", "When it was acquired, when known."),
    },
    "v_external_id_candidate": {
        "entity_id": ("integer", "The entity the identifier is suspected for."), "entity_type": ("text", "work or person."), "name": ("text", "Primary name of the entity."),
        "scheme": ("text", "Identifier scheme (imdb_name, imdb_title)."), "value": ("text", "The suspected identifier."),
        "tier": ("text", "Why it was not attached: weak_single_title, conflict_birth_year, conflict_several_candidates, shared_by_several_entities, name_and_birth_year_only, ids_reliable_false_unconfirmed or episode_number_only."),
        "evidence": ("text", "Short text with the evidence found."), "source": ("text", "The source that suggested the identifier."),
    },
    "v_entity_canonical": {
        "merged_entity_id": ("integer", "The person recorded as the same human as the canonical one."), "merged_name": ("text", "Primary name of the merged person."),
        "canonical_entity_id": ("integer", "The surviving person the other views show."), "canonical_name": ("text", "Primary name of the canonical person."),
        "reason": ("text", "Why they are one person."), "evidence": ("text", "JSON: the IMDb id, IMDb birth/death years and the shared credits."), "source": ("text", "The source that decided it."),
    },
}


@contextmanager
def applied(N, movielens: bool = False):
    """Add the v3 descriptions to the notes module `N` for the duration of a block, then restore it (the v2 generators must never see them)."""
    names = ("TABLES", "TABLE_GROUP", "COLUMNS", "VIEWS", "VIEW_COLUMNS")
    saved = {n: dict(getattr(N, n)) for n in names}
    large = N.LARGE_TABLES
    try:
        N.LARGE_TABLES = tuple(large) + LARGE_TABLES_V3
        N.TABLES.update(V3.NOTES_V3)
        N.TABLE_GROUP.update(GROUP)
        N.COLUMNS.update(COLUMNS)
        N.VIEWS.update(VIEWS)
        N.VIEW_COLUMNS.update(VIEW_COLUMNS)
        if movielens:
            N.TABLES.update(V3.NOTES_ML)
            N.TABLE_GROUP.update(GROUP_ML)
            N.COLUMNS.update(COLUMNS_ML)
            N.VIEWS.update(VIEWS_ML)
            N.VIEW_COLUMNS.update(VIEW_COLUMNS_ML)
            N.LARGE_TABLES = tuple(N.LARGE_TABLES) + LARGE_TABLES_ML
        yield N
    finally:
        N.LARGE_TABLES = large
        for n, d in saved.items():
            getattr(N, n).clear()
            getattr(N, n).update(d)
