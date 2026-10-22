from __future__ import annotations

from .constraints import constraint_report
from .models import RagChunk, RagResult
from .retrieval import _build_signal_aware_query, _rerank, _retrieve
from .runtime import _resolve_runtime_config
from .vectorstore import apri_collection


def run_rag(
    *,
    config: dict,
    query: str,
    history: list[dict] | None = None,
) -> RagResult:
    """Run retrieval and reranking only; return structured evidence to the orchestrator."""
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

    signals = _build_signal_aware_query(query, runtime_config)
    retrieved = _retrieve(query, runtime_config, signals=signals)
    final_chunks = _rerank(query, retrieved, runtime_config)

    return RagResult(
        query=query,
        search_mode=runtime_config["retrieval"]["search_mode"],
        rerank_backend=runtime_config["rerank"]["backend"],
        chunks=[RagChunk(**c) for c in final_chunks],
        candidates=[RagChunk(**c) for c in retrieved],
        input_tokens=None,
        output_tokens=None,
        signals=signals,
        embedded_text=signals.semantic_query or query,
        constraints=constraint_report(signals, final_chunks),
    )
