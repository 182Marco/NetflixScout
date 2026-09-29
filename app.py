from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from aikit import hybrid
from aikit import rag
from aikit import rerank
from aikit import vectorstore
from aikit.tools import definisci_tool


class SearchMode(str, Enum):
    semantic = "semantic"
    hybrid = "hybrid"
    bm25 = "bm25"


class RerankBackend(str, Enum):
    cohere = "cohere"
    llm = "llm"


class RagConfig(BaseModel):
    k_largo: int = Field(default=10, ge=1)
    k_finale: int = Field(default=3, ge=1)
    modello_cohere: str = Field(default="rerank-v3.5", min_length=1)
    modello_llm: str = Field(default="gpt-5.6-luna", min_length=1)
    pausa: int = Field(default=6, ge=0)
    search_mode: SearchMode = SearchMode.semantic
    rerank_backend: RerankBackend = RerankBackend.cohere
    collection: str = Field(default="netflix_scout", min_length=1)
    vector_db_dir: str = Field(default="semanticDb", min_length=1)
    rrf_costante: int = Field(default=60, ge=1)


class RagChunk(BaseModel):
    id: str
    testo: str
    score: float
    source: str | None = None


class RagResult(BaseModel):
    query: str
    search_mode: SearchMode
    rerank_backend: RerankBackend
    answer: str
    chunks: list[RagChunk]


class RagToolInput(BaseModel):
    """Run the NetflixScout RAG pipeline on a natural language query."""

    query: str = Field(min_length=1)


CONFIG = RagConfig()
QUERY = "Consigliami film con temi di redenzione e solitudine."


def _apply_config(config: RagConfig) -> None:
    db_dir = Path(config.vector_db_dir)
    vectorstore.CHROMA_DIR = db_dir

    rag.CONFIG["collection"] = config.collection
    rag.CONFIG["k"] = config.k_largo
    rag.CONFIG["modello"] = config.modello_llm

    hybrid.CONFIG["k"] = config.k_finale
    hybrid.CONFIG["candidati"] = config.k_largo
    hybrid.CONFIG["rrf_costante"] = config.rrf_costante

    rerank.CONFIG["k_largo"] = config.k_largo
    rerank.CONFIG["k_finale"] = config.k_finale
    rerank.CONFIG["modello_cohere"] = config.modello_cohere
    rerank.CONFIG["modello_llm"] = config.modello_llm
    rerank.CONFIG["pausa"] = config.pausa


def _retrieve(query: str, config: RagConfig) -> list[dict]:
    if config.search_mode == SearchMode.semantic:
        return rag.recupera(query, config.k_largo)

    hybrid.costruisci_indice_bm25()
    if config.search_mode == SearchMode.hybrid:
        return hybrid.cerca_hybrid(query, config.k_largo)
    return hybrid.cerca_bm25(query, config.k_largo)


def _rerank(query: str, chunks: list[dict], config: RagConfig) -> list[dict]:
    if config.rerank_backend == RerankBackend.cohere:
        ranked = rerank.rerank_cohere(query, chunks)
    else:
        ranked = rerank.rerank_llm(query, chunks)
    return ranked[: config.k_finale]


def run_rag(config: RagConfig = CONFIG, query: str = QUERY) -> RagResult:
    _apply_config(config)

    collection = vectorstore.apri_collection(config.collection)
    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty. Run `python buildSemanticDb.py` before querying."
        )

    retrieved = _retrieve(query, config)
    final_chunks = _rerank(query, retrieved, config)
    answer = rag.genera(final_chunks, query)

    return RagResult(
        query=query,
        search_mode=config.search_mode,
        rerank_backend=config.rerank_backend,
        answer=answer,
        chunks=[RagChunk(**c) for c in final_chunks],
    )


RAG_TOOL_NAME = "rag_search"
RAG_TOOL = definisci_tool(RagToolInput, RAG_TOOL_NAME)
REGISTERED_TOOLS = [RAG_TOOL]


def execute_tool(name: str, arguments: dict, config: RagConfig = CONFIG) -> str:
    if name != RAG_TOOL_NAME:
        raise ValueError(f"Unknown tool: {name}")
    payload = RagToolInput(**arguments)
    result = run_rag(config=config, query=payload.query)
    return result.model_dump_json(indent=2)


if __name__ == "__main__":
    output = run_rag(config=CONFIG, query=QUERY)
    print(json.dumps(output.model_dump(), indent=2, ensure_ascii=False))