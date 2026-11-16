"""`run_film_index`: the film retriever's whole path (parser -> embedding -> filtered dense search -> reorder) as one `RagResult`. Never falls back to another index."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..results import QuerySignals, RagChunk, RagResult, ReferenceTitle
from . import parser as parser_module
from .index import Film, FilmIndex
from .search import Settings, search
from .service import make_embed, make_parse, make_reorder

CANDIDATES_SHOWN = 50


@lru_cache(maxsize=4)
def _index(url: str, collection: str) -> FilmIndex:
    return FilmIndex(url=url, collection=collection)


def index_for(config: dict) -> FilmIndex:
    qdrant = (config.get("vectorstore") or {}).get("qdrant") or {}
    return _index(qdrant.get("url") or "http://127.0.0.1:6333", config["vectorstore"]["collection"])


MAX_POOL = 50


def settings_from(config: dict) -> Settings:
    fi = config.get("film_index") or {}
    rr = fi.get("rerank") or {}
    pool = max(10, min(int(fi.get("pool", MAX_POOL)), MAX_POOL))          # K-wide hard cap: never more than 50 candidates
    return Settings(pool=pool, penalty_lambda=float(fi.get("penalty_lambda", 0.5)),
                    max_genre_share=float(fi.get("max_genre_share", 0.08)), max_avoid_genres=int(fi.get("max_avoid_genres", 3)),
                    rerank_pool=min(int(rr.get("pool", 40)), pool))


def chunk_of(f: Film, rank_score: float) -> RagChunk:
    return RagChunk(
        id=f.point_id, testo=f.plot, score=rank_score, source="wikipedia", movie_id=f.film_id, title=f.title,
        release_year=str(f.year) if f.year else None, genres="; ".join(f.genres) or None, cast="; ".join(f.cast) or None,
        original_title=f.original_title, directors=f.directors, countries=f.countries, duration_minutes=f.duration_minutes,
        imdb_id=f.imdb_id, wikipedia_url=f.wikipedia_url, work_format=f.work_format, unverified=f.unverified)


def film_facts(f: Film, position: int, *, with_imdb_id: bool = False) -> dict[str, Any]:
    """What the answer may say about a film besides its plot; no URLs. `imdb_id` only when `film_index.expose_imdb_id` is on (the integrated configuration): the
    planner passes it to `cinema_sql` or `omdb_search` instead of searching the title again; the answer never states it."""
    facts = {"n": position, "imdb_id": f.imdb_id if with_imdb_id else None, "title": f.title, "original_title": f.original_title if f.original_title and f.original_title != f.title else None,
             "year": f.year, "directors": f.directors[:3], "cast": f.cast[:5], "countries": f.countries[:3],
             "duration_minutes": f.duration_minutes, "not_verified_as_a_film": True if f.unverified else None}
    return {k: v for k, v in facts.items() if v not in (None, [], "")}


def query_signals(s) -> QuerySignals:
    return QuerySignals(
        positive_signals=[s.positive_it], negative_signals=list(s.avoid_descriptions_it), hard_exclusions=list(s.avoid_franchise_names),
        semantic_query=s.positive_it, avoid_query="; ".join(s.avoid_descriptions_it),
        like_titles=[ReferenceTitle(title=t.title_original or t.title_it, year=t.year) for t in s.like_titles],
        avoid_titles=[ReferenceTitle(title=t.title_original or t.title_it, year=t.year) for t in s.avoid_titles],
        genres=list(s.keep_genres_it), excluded_genres=list(s.avoid_genres_it),
        filters={k: v for k, v in (("year_from", s.year_from), ("year_to", s.year_to), ("countries", list(s.countries)), ("directors", list(s.directors)),
                                   ("actors", list(s.actors)), ("rare_terms", list(s.rare_terms))) if v not in (None, [])})


def run_film_index(*, config: dict, query: str, query_hint: str | None = None) -> RagResult:
    fi = config.get("film_index") or {}
    index = index_for(config)
    if index.count() == 0:
        raise RuntimeError(f"The film collection '{index.collection}' is empty or missing: start Qdrant (scripts/start_qdrant.sh) and check rag.vectorstore.collection.")
    k = int(config["retrieval"]["k_finale"])
    notes: dict[str, Any] = {}
    text = query if not query_hint or query_hint.strip() == query.strip() else f"{query}\n\nPlanner rewrite: {query_hint.strip()}"
    try:
        signals = make_parse(fi.get("parser_model", "gpt-5.6-luna"), fi.get("parser_effort"))(text)
    except Exception as exc:  # noqa: BLE001  (the plain request is searched, with no exclusions, and the answer is told)
        signals = parser_module.fallback(query)
        notes["parser_failed"] = type(exc).__name__
    embed = make_embed(config["embedding"]["model"], config["embedding"].get("dimensions"))
    rr = fi.get("rerank") or {}
    reorder = make_reorder(rr) if rr.get("enabled", True) else None
    out = search(index, embed, signals, query, k=k, settings=settings_from(config), reorder=reorder)
    if out.engine == "penalty_after_error":
        notes["reorder_failed"] = True
    if out.context.dropped_genre_terms:
        notes["genre_filters_dropped"] = out.context.dropped_genre_terms
    if signals.contradictory:
        notes["contradiction"] = signals.contradiction_note or True
    if not out.films and (signals.year_from or signals.year_to or signals.countries or signals.directors or signals.actors or signals.rare_terms):
        notes["no_film_matches_the_filters"] = True
    shown_pool = out.pool[:CANDIDATES_SHOWN]
    ranked = out.reordered or out.pool[:int(rr.get("pool", 40))]
    refs = out.context.references
    return RagResult(
        query=query,
        chunks=[chunk_of(f, f.score) for f in out.films], candidates=[chunk_of(f, f.score) for f in shown_pool],
        reranked=[chunk_of(f, float(len(ranked) - i)) for i, f in enumerate(ranked)], rerank_engine=out.engine,
        signals=query_signals(signals), embedded_text=signals.positive_it,
        rerank_query=f"{signals.positive_en} | avoid: {'; '.join(signals.avoid_descriptions_en) or '-'}",
        references={"used": bool(refs), "steered": any(r["role"] == "like" for r in refs), "strategy": "centroid", "references": refs} if refs else {},
        films=[film_facts(f, i, with_imdb_id=bool(fi.get("expose_imdb_id"))) for i, f in enumerate(out.films, start=1)], notes=notes)
