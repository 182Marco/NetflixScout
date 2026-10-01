from __future__ import annotations

from aikit import apri_collection, genera

from rag_support.models import RagChunk, RagResult
from rag_support.retrieval import _rerank, _retrieve
from rag_support.runtime import _resolve_runtime_config


def run_rag(
    *,
    config: dict,
    query: str,
    history: list[dict] | None = None,
) -> RagResult:
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
    generation_result = genera(
        final_chunks,
        query,
        model=runtime_config["generation"]["model"],
        instructions=runtime_config["generation"]["instructions"],
        storia=history,
        return_usage=True,
    )

    return RagResult(
        query=query,
        search_mode=runtime_config["retrieval"]["search_mode"],
        rerank_backend=runtime_config["rerank"]["backend"],
        answer=generation_result["text"],
        chunks=[RagChunk(**c) for c in final_chunks],
        input_tokens=generation_result.get("input_tokens"),
        output_tokens=generation_result.get("output_tokens"),
    )
