from __future__ import annotations
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field

from aikit import (
    apri_collection,
    cerca_bm25,
    cerca_hybrid,
    costruisci_indice_bm25,
    db_dir_for_backend,
    definisci_tool,
    genera,
    recupera,
    rerank_cohere,
    rerank_llm,
)


class SearchMode(str, Enum):
    semantic = "semantic"
    hybrid = "hybrid"
    bm25 = "bm25"


class RerankBackend(str, Enum):
    cohere = "cohere"
    llm = "llm"


RAG_CONFIG = {
    "retrieval": {
        "search_mode": SearchMode.semantic,
        "k_largo": 10,
        "k_finale": 3,
        "rrf_costante": 60,
    },
    "rerank": {
        "backend": RerankBackend.cohere,
        "cohere_model": "rerank-v3.5",
        "llm_model": "gpt-5.6-luna",
    },
    "generation": {
        "model": "gpt-5.6-luna",
        "instructions": (
            "Rispondi alla domanda usando solo le informazioni nei documenti del messaggio. "
            "Non cercare su internet. "
            "Non usare id film o markup nella risposta. "
            "Prima del consiglio riporta titolo, anno e genere tra parentesi. "
            "Poi spiega le motivazioni del consiglio con tono informale, caldo e amabile, "
            "citando i passaggi specifici che motivano la scelta. "
            "Se la risposta non e presente nei documenti, rispondi esattamente: \"Non lo trovo nei documenti.\""
        ),
    },
    "embedding": {
        "backend": "openai",
        "model": "text-embedding-3-small",
    },
    "vectorstore": {
        "collection": "netflix_scout",
        "db_dir": None,
    },
}


class RagChunk(BaseModel):
    id: str
    testo: str
    score: float
    source: str | None = None
    movie_id: str | None = None
    title: str | None = None
    release_date: str | None = None
    release_year: str | None = None
    genres: str | None = None
    cast: str | None = None


class RagResult(BaseModel):
    query: str
    search_mode: SearchMode
    rerank_backend: RerankBackend
    answer: str
    chunks: list[RagChunk]


class RagToolInput(BaseModel):
    """Run the NetflixScout RAG pipeline on a natural language query."""

    query: str = Field(min_length=1)


QUERY = "Trova film simili a Inception per struttura narrativa, ma senza usare necessariamente fantascienza o sogni."

def _resolve_runtime_config(config: dict) -> dict:
    db_root = Path("dbVettoriale")
    vectorstore_config = dict(config["vectorstore"])
    embedding_config = dict(config["embedding"])

    if vectorstore_config["db_dir"]:
        db_dir = Path(vectorstore_config["db_dir"])
        effective_backend = embedding_config["backend"]
    else:
        openai_dir = db_root / "openai"
        local_dir = db_root / "local"

        if openai_dir.exists() and not local_dir.exists():
            effective_backend = "openai"
        elif local_dir.exists() and not openai_dir.exists():
            effective_backend = "local"
        else:
            effective_backend = embedding_config["backend"]

        db_dir = db_dir_for_backend(effective_backend)

    runtime_config = {
        **config,
        "retrieval": dict(config["retrieval"]),
        "rerank": dict(config["rerank"]),
        "generation": dict(config["generation"]),
        "embedding": {**embedding_config, "backend": effective_backend},
        "vectorstore": {**vectorstore_config, "db_dir": db_dir},
    }

    return runtime_config


def _retrieve(query: str, config: dict) -> list[dict]:
    collection = apri_collection(
        config["vectorstore"]["collection"],
        db_dir=config["vectorstore"]["db_dir"],
    )

    if config["retrieval"]["search_mode"] == SearchMode.semantic:
        return recupera(
            query,
            collection_name=config["vectorstore"]["collection"],
            k=config["retrieval"]["k_largo"],
            embedding_backend=config["embedding"]["backend"],
            embedding_model=config["embedding"]["model"],
            db_dir=config["vectorstore"]["db_dir"],
        )

    indice_bm25 = costruisci_indice_bm25(collection)

    if config["retrieval"]["search_mode"] == SearchMode.hybrid:
        risultati_semantici = recupera(
            query,
            collection_name=config["vectorstore"]["collection"],
            k=config["retrieval"]["k_largo"],
            embedding_backend=config["embedding"]["backend"],
            embedding_model=config["embedding"]["model"],
            db_dir=config["vectorstore"]["db_dir"],
        )
        risultati_bm25 = cerca_bm25(query, indice_bm25, config["retrieval"]["k_largo"])
        return cerca_hybrid(
            risultati_semantici,
            risultati_bm25,
            config["retrieval"]["k_largo"],
            rrf_costante=config["retrieval"]["rrf_costante"],
        )

    return cerca_bm25(query, indice_bm25, config["retrieval"]["k_largo"])


def _rerank(query: str, chunks: list[dict], config: dict) -> list[dict]:
    if config["rerank"]["backend"] == RerankBackend.cohere:
        ranked = rerank_cohere(
            query,
            chunks,
            model=config["rerank"]["cohere_model"],
        )
    else:
        ranked = rerank_llm(
            query,
            chunks,
            model=config["rerank"]["llm_model"],
        )

    return ranked[: config["retrieval"]["k_finale"]]


def run_rag(config: dict = RAG_CONFIG, query: str = QUERY) -> RagResult:
    runtime_config = _resolve_runtime_config(config)

    collection = apri_collection(
        runtime_config["vectorstore"]["collection"],
        db_dir=runtime_config["vectorstore"]["db_dir"],
    )

    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty. Run `python buildSemanticDb.py "
            "--embedding-backend <backend>` before querying."
        )

    retrieved = _retrieve(query, runtime_config)
    final_chunks = _rerank(query, retrieved, runtime_config)
    answer = genera(
        final_chunks,
        query,
        model=runtime_config["generation"]["model"],
        instructions=runtime_config["generation"]["instructions"],
    )

    return RagResult(
        query=query,
        search_mode=runtime_config["retrieval"]["search_mode"],
        rerank_backend=runtime_config["rerank"]["backend"],
        answer=answer,
        chunks=[RagChunk(**c) for c in final_chunks],
    )


RAG_TOOL_NAME = "rag_search"
RAG_TOOL = definisci_tool(RagToolInput, RAG_TOOL_NAME)
REGISTERED_TOOLS = [RAG_TOOL]


def execute_tool(
    name: str,
    arguments: dict,
    config: dict = RAG_CONFIG,
) -> str:
    if name != RAG_TOOL_NAME:
        raise ValueError(f"Unknown tool: {name}")

    payload = RagToolInput(**arguments)
    result = run_rag(config=config, query=payload.query)

    return result.model_dump_json(indent=2)


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
            title = chunk.title
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
            title = chunk.get("title")
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
        if title:
            print(f"  🎞️ TITLE    : {title}")
        if release_year or release_date:
            print(f"  📅 YEAR     : {release_year or release_date}")
        if genres:
            print(f"  🏷️ GENRES   : {genres}")
        if cast:
            print(f"  👥 CAST     : {cast}")
        print(f"  📝 TESTO    : \"{preview}\"")


if __name__ == "__main__":
    runtime_config = _resolve_runtime_config(RAG_CONFIG)

    collection = apri_collection(
        runtime_config["vectorstore"]["collection"],
        db_dir=runtime_config["vectorstore"]["db_dir"],
    )

    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty. Run `python buildSemanticDb.py "
            "--embedding-backend <backend>` before querying."
        )

    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║  🎬 NETFLIXSCOUT — RAG SEARCH" + " " * 38 + "║")
    print("╚" + "═" * 68 + "╝")

    print(f"\n🔎 QUERY")
    print(f"   \"{QUERY}\"")

    print(f"\n⚙️  MODALITÀ")
    print(f"   🔍 Search       : {runtime_config['retrieval']['search_mode'].value}")
    print(f"   🧠 Reranker     : {runtime_config['rerank']['backend'].value}")
    print(f"   📚 K largo      : {runtime_config['retrieval']['k_largo']}")
    print(f"   🎯 K finale     : {runtime_config['retrieval']['k_finale']}")

    retrieved = _retrieve(QUERY, runtime_config)

    _print_chunks(
        f"K LARGO — {len(retrieved)} CHUNK RECUPERATI",
        retrieved,
        "📚",
    )

    final_chunks = _rerank(QUERY, retrieved, runtime_config)

    _print_chunks(
        f"RERANKING — {len(final_chunks)} CHUNK SELEZIONATI",
        final_chunks,
        "🏆",
    )

    answer = genera(
        final_chunks,
        QUERY,
        model=runtime_config["generation"]["model"],
        instructions=runtime_config["generation"]["instructions"],
    )

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
