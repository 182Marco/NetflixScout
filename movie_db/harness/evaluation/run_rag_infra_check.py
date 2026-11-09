"""Infrastructure check of the two RAGs WITHOUT any model call (no embedding, no parser, no reorder): the REAL retrievers (`film_index.search.search`, `series_rag.retrieval.search`)
run on the REAL Qdrant collections, with query vectors taken from vectors already stored in those collections. It proves: the collections are readable, the vector size and norm
match the configured embedding, the filters (year, country, director, level, series, exclusions) are evaluated by Qdrant, the penalty for unwanted traits changes the ranking, the
results carry the identifiers needed to continue in `cinema_sql`, and the continuation resolves without ambiguity.

    python -m movie_db.harness.evaluation.run_rag_infra_check [--cinema-db FILE]

It does NOT prove semantic quality for a text query (that needs a real embedding of the text and the LLM parser: the live evaluation). Read-only on Qdrant and on the database.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
from qdrant_client import QdrantClient, models

import app as app_module
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool
from tool.rag.film.retrieval import search as FS
from tool.rag.film.retrieval.adapter import film_facts
from tool.rag.film.retrieval.index import FilmIndex
from tool.rag.film.retrieval.models import Signals, TitleRef
from tool.rag.series import retrieval as SR

ROOT = Path(__file__).resolve().parents[3]
URL = "http://127.0.0.1:6333"
TT = re.compile(r"^tt\d{7,9}$")
FILMS = {"Inception": "tt1375666", "The Matrix": "tt0133093", "Amélie": "tt0211915", "Parasite": "tt6751668", "Toy Story": "tt0114709", "Il postino": "tt0110877",
         "Psycho": "tt0054215", "La città incantata": "tt0245429"}
SERIES = ["Dark", "Breaking Bad", "Lost", "Black Mirror", "The Wire", "Chernobyl"]


class Result:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, bool(ok), detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
        return bool(ok)


def vector_of(q: QdrantClient, collection: str, flt: models.Filter) -> tuple[np.ndarray, dict] | None:
    pts, _ = q.scroll(collection, scroll_filter=flt, limit=1, with_payload=True, with_vectors=True)
    return (np.array(pts[0].vector, dtype=float), pts[0].payload) if pts else None


def stored_embed(vectors: dict[str, np.ndarray]):
    """An `embed` that returns the stored vector registered for a text key: nothing is ever sent anywhere."""
    def embed(texts: list[str]) -> np.ndarray:
        return np.stack([vectors[t] for t in texts])
    return embed


def cinema_resolution(tool: CinemaSqlTool, imdb_ids: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for imdb in imdb_ids:
        status = tool.run(query="x", params={"operation": "find_work", "imdb_id": imdb})["metadata"]["cinema_db"]["status"]
        out[status] = out.get(status, 0) + 1
    return out


def films(q: QdrantClient, tool: CinemaSqlTool, res: Result) -> None:
    print("\n== RAG FILM  (wikipedia_films_it_v3)")
    cfg = app_module.CONFIG["rag"]
    index = FilmIndex(url=URL, collection=cfg["vectorstore"]["collection"])
    info = q.get_collection(index.collection)
    res.check("collection readable and complete", index.count() == 41138 == info.points_count and info.status.value == "green", f"{index.count()} points, status {info.status.value}")
    res.check("vector size and metric match the configured embedding", info.config.params.vectors.size == cfg["embedding"]["dimensions"] == 1536 and info.config.params.vectors.distance.value == "Cosine",
              f"size {info.config.params.vectors.size}, {info.config.params.vectors.distance.value}, model {cfg['embedding']['model']}")
    settings = FS.Settings(pool=cfg["film_index"]["pool"])
    seen_ids: list[str] = []
    ranks = []
    for name, imdb in FILMS.items():
        got = vector_of(q, index.collection, models.Filter(must=[models.FieldCondition(key="imdb_id", match=models.MatchValue(value=imdb))]))
        if not got:
            res.check(f"stored vector of {name}", False, "not in the collection"); continue
        vec, payload = got
        key = f"§{imdb}"
        out = FS.search(index, stored_embed({key: vec}), Signals(positive_it=key, positive_en=key), name, k=6, settings=settings)
        ids = [f.imdb_id for f in out.films]
        seen_ids += [i for i in ids if i]
        ranks.append(ids[0] == imdb and out.films[0].score > 0.999)
        print(f"     {name:20} -> " + " | ".join(f"{f.title} ({f.year})" for f in out.films[1:6]))
    res.check("each stored film is its own nearest neighbour (cosine ≈ 1) through the real retriever", all(ranks) and len(ranks) == len(FILMS), f"{sum(ranks)}/{len(FILMS)}")
    # filters evaluated by Qdrant
    vec, _ = vector_of(q, index.collection, models.Filter(must=[models.FieldCondition(key="imdb_id", match=models.MatchValue(value="tt1375666"))]))
    emb = stored_embed({"§p": vec})
    base = dict(positive_it="§p", positive_en="§p")
    t0 = time.perf_counter()
    out = FS.search(index, emb, Signals(**base, year_from=2005, year_to=2015), "x", k=10, settings=settings)
    res.check("year filter", out.films and all(2005 <= (f.year or 0) <= 2015 for f in out.films), f"{len(out.films)} films, {(time.perf_counter() - t0) * 1000:.0f} ms")
    out = FS.search(index, emb, Signals(**base, directors=["Christopher Nolan"]), "x", k=10, settings=settings)
    res.check("director filter", out.films and all(any("nolan" in d.casefold() for d in f.directors) for f in out.films), f"{len(out.films)} films: " + ", ".join(f.title for f in out.films[:5]))
    out = FS.search(index, emb, Signals(**base, countries=["Francia"]), "x", k=10, settings=settings)
    res.check("country filter", out.films and all("Francia" in f.countries for f in out.films), f"{len(out.films)} films")
    out = FS.search(index, emb, Signals(**base, actors=["Leonardo DiCaprio"]), "x", k=10, settings=settings)
    res.check("actor filter", out.films and all(any("dicaprio" in c.casefold() for c in (f.cast or [])) for f in out.films), f"{len(out.films)} films: " + ", ".join(f.title for f in out.films[:4]))
    # exclusions: a cited film and its franchise leave the list; the penalty for an unwanted trait reorders
    mvec, _ = vector_of(q, index.collection, models.Filter(must=[models.FieldCondition(key="imdb_id", match=models.MatchValue(value="tt0133093"))]))
    emb2 = stored_embed({"§m": mvec, "§p": vec})
    plain = FS.search(index, emb2, Signals(positive_it="§m", positive_en="§m"), "x", k=10, settings=settings)
    cited = TitleRef(title_it="Matrix", title_original="The Matrix", year=1999, summary_it="x", summary_en="x")
    excl = FS.search(index, emb2, Signals(positive_it="§m", positive_en="§m", avoid_titles=[cited], avoid_franchise_names=["Matrix"]), "x", k=10, settings=settings)
    res.check("a cited film and its franchise are excluded", any("matrix" in f.title.casefold() for f in plain.films) and not any("matrix" in f.title.casefold() for f in excl.films),
              f"with: {[f.title for f in plain.films[:4]]} → without: {[f.title for f in excl.films[:4]]}")
    pen = FS.search(index, emb2, Signals(positive_it="§p", positive_en="§p", avoid_descriptions_it=["§m"], avoid_descriptions_en=["§m"]), "x", k=10, settings=settings)
    nopen = FS.search(index, emb2, Signals(positive_it="§p", positive_en="§p"), "x", k=10, settings=settings)
    res.check("the penalty for an unwanted trait changes the ranking", [f.imdb_id for f in pen.films] != [f.imdb_id for f in nopen.films],
              f"{len({f.imdb_id for f in pen.films} & {f.imdb_id for f in nopen.films})}/10 films in common")
    # what the planner would be given, and the hand-over
    facts = [film_facts(f, i, with_imdb_id=True) for i, f in enumerate(nopen.films, start=1)]
    res.check("every result carries a well-formed imdb_id in the planner facts", all(TT.match(str(x.get("imdb_id"))) for x in facts), f"{sum(bool(TT.match(str(x.get('imdb_id')))) for x in facts)}/{len(facts)}")
    status = cinema_resolution(tool, sorted(set(seen_ids)))
    res.check("those ids resolve in cinema_sql without ambiguity", status.get("ok", 0) == len(set(seen_ids)), f"{status} over {len(set(seen_ids))} distinct films")


def series(q: QdrantClient, tool: CinemaSqlTool, res: Result) -> None:
    print("\n== RAG SERIE  (wikipedia_series_it_v1)")
    cfg = app_module.CONFIG["series_rag"]
    index = SR.SeriesIndex(url=URL, collection=cfg["collection"])
    info = q.get_collection(index.collection)
    res.check("collection readable and complete", index.count() == 101706 == info.points_count and info.status.value == "green", f"{index.count()} points, status {info.status.value}")
    res.check("vector size and metric match the configured embedding", info.config.params.vectors.size == cfg["embedding_dimensions"] == 1536 and info.config.params.vectors.distance.value == "Cosine",
              f"size {info.config.params.vectors.size}, {info.config.params.vectors.distance.value}, model {cfg['embedding_model']}")
    settings = SR.Settings(pool=cfg["pool"])
    ids: list[str] = []
    selfhit = []
    for title in SERIES:
        hit = index.find_titles(title, levels=("series",), eligible_only=True)
        if not hit:
            res.check(f"series «{title}» in the catalogue", False); continue
        got = vector_of(q, index.collection, models.Filter(must=[models.FieldCondition(key="record_id", match=models.MatchValue(value=hit[0].record_id))]))
        vec = got[0]
        key = f"§{title}"
        out = SR.search(index, stored_embed({key: vec}), SR.SeriesSignals(level="series", positive_it=key, positive_en=key), k=6, settings=settings)
        selfhit.append(out.items and out.items[0].record_id == hit[0].record_id and all(i.entity_type == "series" for i in out.items))
        ids += [i.imdb_id for i in out.items if i.imdb_id]
        print(f"     {title:14} -> " + " | ".join(f"{i.title} ({i.year})" for i in out.items[1:6]))
    res.check("each stored series is its own nearest neighbour and every result is at the requested level (series)", all(selfhit) and len(selfhit) == len(SERIES), f"{sum(map(bool, selfhit))}/{len(SERIES)}")
    dark = index.find_titles("Dark", levels=("series",), eligible_only=True)[0]
    vec = vector_of(q, index.collection, models.Filter(must=[models.FieldCondition(key="record_id", match=models.MatchValue(value=dark.record_id))]))[0]
    emb = stored_embed({"§d": vec})
    base = dict(positive_it="§d", positive_en="§d")
    out = SR.search(index, emb, SR.SeriesSignals(level="series", year_from=2015, year_to=2022, **base), k=8, settings=settings)
    res.check("year filter", out.items and all(2015 <= (i.year or 0) <= 2022 for i in out.items), f"{len(out.items)} series")
    out = SR.search(index, emb, SR.SeriesSignals(level="series", avoid_titles=["Dark"], **base), k=8, settings=settings)
    res.check("a cited series is excluded", out.items and not any(i.title.casefold().startswith("dark") for i in out.items), f"{[i.title for i in out.items[:4]]}")
    out = SR.search(index, emb, SR.SeriesSignals(level="episode", **base), k=5, settings=settings)
    res.check("episode level returns episodes of a named parent series", out.items and all(i.entity_type == "episode" and i.series_title for i in out.items), f"{[(i.series_title, i.season_number, i.episode_number) for i in out.items[:3]]}")
    out = SR.search(index, emb, SR.SeriesSignals(level="tv_movie", **base), k=5, settings=settings)
    res.check("TV-movie level", out.items and all(i.entity_type == "tv_movie" for i in out.items), f"{[i.title for i in out.items[:4]]}")
    out = SR.search(index, emb, SR.SeriesSignals(level="series", series_title="Lost", positive_it="x", positive_en="x"), k=5, settings=settings)
    res.check("a named series is found by title lookup (no vector)", out.items and out.notes.get("title_match"), f"{[(i.title, i.year) for i in out.items]}")
    out = SR.search(index, emb, SR.SeriesSignals(level="episode", series_title="Lost", season_number=2, list_children=True, positive_it="x", positive_en="x"), k=5, settings=settings)
    numbers = [i.episode_number for i in out.items if i.episode_number is not None]
    res.check("episodes of a season are listed by navigation (no vector), the numbered ones in ascending order", out.items and out.notes.get("listing") and numbers == sorted(numbers) and len(numbers) > 0,
              f"{len(out.items)} episodes, {len(out.items) - len(numbers)} without a number (known gap of the numbering: episode LISTS go to tvmaze_search)")
    out = SR.search(index, emb, SR.SeriesSignals(level="episode", series_title="Serie che non esiste xyz", list_children=True, positive_it="x", positive_en="x"), k=5, settings=settings)
    res.check("a series the catalogue does not have returns nothing, never a guess", not out.items and "series_not_in_index" in out.notes)
    status = cinema_resolution(tool, sorted(set(ids)))
    res.check("series ids handed over resolve in cinema_sql (the rest answer not_found → TMDb fallback)", status.get("ok", 0) >= 0.7 * max(len(set(ids)), 1) and not status.get("ambiguous"), f"{status} over {len(set(ids))} distinct series")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cinema-db", default=str(__import__("cinema_db.harness.candidate", fromlist=["EXPECTED_PATH"]).EXPECTED_PATH))
    args = ap.parse_args(argv)
    q = QdrantClient(url=URL, timeout=120)
    tool = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=args.cinema_db, max_queries_per_turn=40, default_limit=10))
    res = Result()
    films(q, tool, res)
    series(q, tool, res)
    failed = [r for r in res.rows if not r[1]]
    print(f"\n{len(res.rows) - len(failed)}/{len(res.rows)} checks passed. No model was called; this is NOT a test of semantic quality for text queries.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
