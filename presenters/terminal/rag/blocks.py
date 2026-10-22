"""Terminal print blocks for the RAG chunks.

Chunks may be dicts or Pydantic models (e.g. `RagChunk`): this module does not import
the RAG package, so presenters stay independent from the core and import cycles are avoided.
"""
from __future__ import annotations

from typing import Any

from ..box import print_box


def print_chunks(
    title: str,
    chunks: list[Any],
    emoji: str,
) -> None:
    print_box(emoji, title)

    for index, chunk in enumerate(chunks, start=1):
        if hasattr(chunk, "model_dump"):
            chunk = chunk.model_dump()
        chunk_id = chunk.get("id")
        score = chunk.get("score")
        source = chunk.get("source")
        testo = chunk.get("testo", "")
        movie_id = chunk.get("movie_id")
        chunk_title = chunk.get("title")
        release_date = chunk.get("release_date")
        release_year = chunk.get("release_year")
        genres = chunk.get("genres")
        cast = chunk.get("cast")

        preview = testo[:200] + "..."

        print()
        print(f"  🔹 CHUNK #{index}")
        print("  " + "─" * 64)
        print(f"  🆔 ID       : {chunk_id}")
        print(f"  📊 SCORE    : {score:.4f}")
        print(f"  📁 SOURCE   : {source}")
        if movie_id:
            print(f"  🎬 MOVIE ID : {movie_id}")
        if chunk_title:
            print(f"  🎞️ TITLE    : {chunk_title}")
        if release_year or release_date:
            print(f"  📅 YEAR     : {release_year or release_date}")
        if genres:
            print(f"  🏷️ GENRES   : {genres}")
        if cast:
            print(f"  👥 CAST     : {cast}")
        print(f'  📝 TESTO    : "{preview}"')


def print_retrieval_compact(
    title: str,
    chunks: list[dict],
    emoji: str,
) -> None:
    print_box(emoji, title)

    for chunk in chunks:
        chunk_title = chunk.get("title") or "N/A"
        year = chunk.get("release_year") or chunk.get("release_date") or "N/A"
        print(f"  {chunk_title} ({year})")


def print_retrieval_query(embedded_text: str | None, genres: list[str]) -> None:
    if embedded_text:
        print(f"\n🔎 Testo usato per l'embedding: {embedded_text}")
    if genres:
        print(f"   Generi richiesti: {', '.join(genres)}")
