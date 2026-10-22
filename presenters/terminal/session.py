"""Terminal session blocks: startup banner, RAG mode, input prompt and goodbye."""
from __future__ import annotations


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


def print_goodbye() -> None:
    print("\nChiusura chat. A presto!")


def read_query() -> str:
    query = input("\n" * 2 + "Tu > ").strip()
    print("\n")
    return query
