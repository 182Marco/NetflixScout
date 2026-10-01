from __future__ import annotations

from aikit import (
    apri_collection,
    cerca_bm25,
    cerca_hybrid,
    costruisci_indice_bm25,
    recupera,
    rerank_cohere,
    rerank_llm,
)

from rag_support.models import RerankBackend, SearchMode


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
