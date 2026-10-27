"""Terminal print blocks for the RAG chunks.

The content comes from the shared `presenters/rag_view.py` (the web shows the same data);
this module only decides the terminal format and does not import the RAG package.
"""
from __future__ import annotations

from ...rag_view import RagStepView
from ..box import print_box
from ..texts import texts


def print_chunks(view: RagStepView, emoji: str, language: str = "it") -> None:
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
        print(f'  📝 {texts(language)["plot"]:<8}: "{chunk.preview}"')


def print_retrieval_compact(view: RagStepView, emoji: str) -> None:
    print_box(emoji, view.title)

    for chunk in view.chunks:
        print(f"  {chunk.title or 'N/A'} ({chunk.year or 'N/A'})")


def print_retrieval_query(embedded_text: str | None, genres: list[str], language: str = "it") -> None:
    text = texts(language)
    if embedded_text:
        print(f"\n🔎 {text['embedded']}: {embedded_text}")
    if genres:
        print(f"   {text['genres']}: {', '.join(genres)}")


def print_retrieval_params(params: dict, overridden: list[str], language: str = "it") -> None:
    if not params:
        return
    text = texts(language)
    parts = [f"{k}={v}{'*' if k in overridden else ''}" for k, v in params.items()]
    print(f"\n⚙️  {text['params']}: {', '.join(parts)}" + (f"  (* {text['by_planner']})" if overridden else ""))


def print_references(view: RagStepView, language: str = "it") -> None:
    """Which cited movies gave a real vector to the search and how (no vectors are ever printed)."""
    if not view.references and not view.reference_note:
        return
    text = texts(language)
    state = f"{text['guided']} ({view.reference_strategy})" if view.reference_steered else text["not_guided"]
    print(f"\n🎯 {text['references']}: {state}" + (f" - {view.reference_note}" if view.reference_note else ""))
    for ref in view.references:
        role = text["similar"] if ref.role == "positive" else text["different"]
        how = ref.source or "-"
        extra = []
        if ref.tmdb_calls:
            extra.append(f"{ref.tmdb_calls} {text['tmdb_calls']}")
        if ref.embedding_created:
            extra.append(text["embedding_created"])
        if ref.reason:
            extra.append(ref.reason)
        print(f"   {role} {ref.title}{f' ({ref.year})' if ref.year else ''}: {ref.status} [{how}]"
              + (f" - {', '.join(extra)}" if extra else ""))
