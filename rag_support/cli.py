from __future__ import annotations

from rag_support.models import RagChunk


def print_header() -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║  🎬 NETFLIXSCOUT — RAG SEARCH" + " " * 38 + "║")
    print("╚" + "═" * 68 + "╝")
    print("\nDigita una domanda sui film oppure 'exit'/'quit' per uscire.\n")


def print_mode(runtime_config: dict) -> None:
    print("\n⚙️  MODALITÀ")
    print(f"   🔍 Search       : {runtime_config['retrieval']['search_mode'].value}")
    print(f"   🧠 Reranker     : {runtime_config['rerank']['backend'].value}")
    print(f"   📚 K largo      : {runtime_config['retrieval']['k_largo']}")
    print(f"   🎯 K finale     : {runtime_config['retrieval']['k_finale']}")


def print_final_answer(answer: str) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║  🤖  RISPOSTA FINALE DELL'LLM" + " " * 38 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    print(answer)
    print()
    print("═" * 70)
    print("✅ RAG PIPELINE COMPLETATA")
    print("═" * 70)


def _print_chunks(
    title: str,
    chunks: list[dict | RagChunk],
    emoji: str,
) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  {emoji}  {title.upper():<62}║")
    print("╚" + "═" * 68 + "╝")

    for index, chunk in enumerate(chunks, start=1):
        if isinstance(chunk, RagChunk):
            chunk_id = chunk.id
            score = chunk.score
            source = chunk.source
            testo = chunk.testo
            movie_id = chunk.movie_id
            chunk_title = chunk.title
            release_date = chunk.release_date
            release_year = chunk.release_year
            genres = chunk.genres
            cast = chunk.cast
        else:
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


def _print_retrieval_compact(
    title: str,
    chunks: list[dict],
    emoji: str,
) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  {emoji}  {title.upper():<62}║")
    print("╚" + "═" * 68 + "╝")

    for chunk in chunks:
        chunk_title = chunk.get("title") or "N/A"
        year = chunk.get("release_year") or chunk.get("release_date") or "N/A"
        print(f"  {chunk_title} ({year})")
