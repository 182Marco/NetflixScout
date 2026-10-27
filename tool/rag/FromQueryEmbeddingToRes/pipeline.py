from __future__ import annotations

from .constraints import constraint_report
from .models import RagChunk, RagResult, SearchMode
from .reference_flow import references_summary
from .references import ReferenceInput
from .retrieval import _build_signal_aware_query, _rerank, _retrieve, compose_rerank_query
from .runtime import _resolve_runtime_config
from .vectorstore import apri_collection


def run_rag(
    *,
    config: dict,
    query: str,
    history: list[dict] | None = None,
    query_hint: str | None = None,
    reference_flow=None,
    turn_id: str | None = None,
) -> RagResult:
    """Run retrieval and reranking only; return structured evidence to the orchestrator.

    `query` is the user's (standalone) request; `query_hint` is the planner's rewrite, used
    only as extra context for the query parser, never in place of the user's words.
    """
    runtime_config = _resolve_runtime_config(config)

    collection = apri_collection(
        runtime_config["vectorstore"]["collection"],
        store_config=runtime_config["vectorstore"],
    )

    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty. Run `python buildSemanticDb.py "
            "--embedding-backend <backend>` before querying."
        )

    signals = _build_signal_aware_query(query, runtime_config, hint=query_hint)
    references, reference_info = _resolve_references(runtime_config, signals, reference_flow, turn_id)
    retrieved = _retrieve(query, runtime_config, signals=signals, references=references)
    # The reranker scores plots in English: the semantic query states the intent better than
    # the user's words ("temi simili a Mare dentro" names no theme), and the explicit
    # requirements it omitted are appended so none is lost (see `compose_rerank_query`).
    rerank_query = compose_rerank_query(signals, query)
    final_chunks = _rerank(rerank_query, retrieved, runtime_config, signals=signals, request=query)

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
        rerank_query=rerank_query,
        constraints=constraint_report(signals, final_chunks),
        references=_references_trace(references, reference_info),
    )


def _resolve_references(config: dict, signals, reference_flow, turn_id):
    """Vectors for the movies the user cites as references, or `(None, why-not)`; never raises."""
    if not (signals.like_titles or signals.avoid_titles):
        return None, {}
    settings = config.get("reference") or {}
    if not settings.get("enabled"):
        return None, {"skipped": "disabled"}
    if config["retrieval"]["search_mode"] != SearchMode.semantic:
        return None, {"skipped": "only_the_semantic_mode_uses_references"}
    try:
        flow = reference_flow() if callable(reference_flow) else reference_flow
        if flow is None:
            return None, {"skipped": "reference_flow_unavailable"}
        refs = flow.resolve(
            [ReferenceInput(t.title, t.year) for t in signals.like_titles],
            [ReferenceInput(t.title, t.year) for t in signals.avoid_titles],
            turn_id=turn_id,
        )
        return refs, {}
    except Exception as exc:  # noqa: BLE001  (the search goes on with the description alone)
        return None, {"skipped": f"reference_flow_error:{type(exc).__name__}"}


def _references_trace(references, info: dict) -> dict:
    if references is None:
        return {"used": False, **info} if info else {}
    trace = references.trace()
    note = {"note": "no_positive_reference_resolved: plain search (a negative vector alone is not used)"} if references.negative_only else {}
    return {**note, "used": references.active, "steered": references.active, "strategy": references.strategy,
            "positive_vectors": len(references.positives()), "negative_vectors": len(references.negatives()),
            "text_vector_repeats": references.text_repeat if references.active else 0,
            "summary": references_summary(references), **trace}
