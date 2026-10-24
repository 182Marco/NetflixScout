"""Terminal print blocks for the RAG chunks.

The content comes from the shared `presenters/rag_view.py` (the web shows the same data);
this module only decides the terminal format and does not import the RAG package.
"""
from __future__ import annotations

from ...rag_view import RagStepView
from ..box import print_box


def print_chunks(view: RagStepView, emoji: str) -> None:
    print_box(emoji, view.title)

    for index, chunk in enumerate(view.chunks, start=1):
        print()
        print(f"  🔹 CHUNK #{index}")
        print("  " + "─" * 64)
        print(f"  🆔 ID       : {chunk.id}")
        print(f"  📊 SCORE    : {chunk.score:.4f}" if chunk.score is not None else "  📊 SCORE    : N/A")
        print(f"  📁 SOURCE   : {chunk.source}")
        if chunk.movie_id:
            print(f"  🎬 MOVIE ID : {chunk.movie_id}")
        if chunk.title:
            print(f"  🎞️ TITLE    : {chunk.title}")
        if chunk.year:
            print(f"  📅 YEAR     : {chunk.year}")
        if chunk.genres:
            print(f"  🏷️ GENRES   : {chunk.genres}")
        if chunk.cast:
            print(f"  👥 CAST     : {chunk.cast}")
        print(f'  📝 TESTO    : "{chunk.preview}"')


def print_retrieval_compact(view: RagStepView, emoji: str) -> None:
    print_box(emoji, view.title)

    for chunk in view.chunks:
        print(f"  {chunk.title or 'N/A'} ({chunk.year or 'N/A'})")


def print_retrieval_query(embedded_text: str | None, genres: list[str]) -> None:
    if embedded_text:
        print(f"\n🔎 Testo usato per l'embedding: {embedded_text}")
    if genres:
        print(f"   Generi richiesti: {', '.join(genres)}")
