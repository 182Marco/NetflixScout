"""`rag_search`: the film retriever as a tool of the agent. Evidence only (chunks, facts, trace); the answer is written by the orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from turn import OUTCOME_EMPTY, OUTCOME_OK, TOOL_PARAM_TURN_ID, tool_outcome

from .models import FilmIndexToolInput
from .params import resolve_retrieval
from .retrieval.adapter import run_film_index

RAG_TOOL_NAME = "rag_search"


@dataclass
class RagTool:
    """Film search over `wikipedia_films_it_v3` (about 41,000 films with the plot of Italian Wikipedia)."""

    name: str = RAG_TOOL_NAME
    description: str = (
        "Search the film index (about 41,000 films with the plot of Italian Wikipedia, up to November 2026) for recommendations and "
        "searches by plot, themes, mood, genre, setting, era, style, people, year or country, including requests that cite films to be "
        "like or unlike, franchises or traits to exclude. Returns the best films; the answer is written elsewhere."
    )
    input_schema: dict[str, Any] = field(default_factory=lambda: FilmIndexToolInput.model_json_schema())
    config: dict[str, Any] = field(default_factory=dict)

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        # The user's standalone query drives the search; the planner's `arguments.query` is only a hint for the query parser
        # (real case: "Film simili a Mare dentro, che affrontino temi e atmosfere analoghi" named no theme).
        planner_query = str(arguments.get("query") or "").strip()
        arguments["query"] = query or planner_query
        payload = FilmIndexToolInput(query=arguments["query"])
        hint = planner_query if planner_query and planner_query != payload.query else None
        # The planner's `k_finale` is applied to a copy of the config, clamped to the configured limits; unusable values never fail the turn.
        retrieval, overridden = resolve_retrieval(self.config.get("retrieval") or {}, arguments)
        arguments.pop(TOOL_PARAM_TURN_ID, None)
        result = run_film_index(config={**self.config, "retrieval": retrieval}, query=payload.query, query_hint=hint)

        chunks = [chunk.model_dump(mode="json") for chunk in result.chunks]
        # After the rerank `score` is the reranker's; the retrieval similarity (0-1) and the place in the wide K are kept apart.
        similarity = {c.id: (rank, c.score) for rank, c in enumerate(result.candidates, start=1)}

        def with_similarity(chunk: dict) -> dict:
            rank, score = similarity.get(chunk.get("id"), (None, None))
            return {**chunk, "similarity": score, "rank_before": rank}

        reranked = [with_similarity(c.model_dump(mode="json")) for c in (result.reranked or result.chunks)]

        return {
            "query": result.query,
            "chunks": chunks,
            "outcome": tool_outcome(OUTCOME_OK if chunks else OUTCOME_EMPTY),
            "metadata": {
                "k_finale": retrieval.get("k_finale"),
                "collection": self.config.get("vectorstore", {}).get("collection"),
                **({"films": result.films} if result.films else {}),
                **({"search_notes": result.notes} if result.notes else {}),
            },
            # Procedure steps for the presenters (same shape as turn.TraceStep).
            # Kept outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": [
                {
                    "kind": "retrieval",
                    "title": "K largo",
                    "data": {
                        "retrieval_params": {
                            "effective": {
                                k: (v.value if hasattr(v, "value") else v)
                                for k, v in retrieval.items()
                                if k == "k_finale"
                            },
                            "overridden": sorted(overridden),
                        },
                        "standalone_query": query,
                        "planner_query": planner_query or None,
                        "embedded_text": result.embedded_text,
                        "signals": result.signals.model_dump(mode="json") if result.signals else None,
                        "references": result.references or None,
                        "chunks": [c.model_dump(mode="json") for c in result.candidates],
                    },
                },
                {
                    "kind": "rerank",
                    "title": "Reranking",
                    "data": {
                        # Who really ranked the pool: the LLM reorder (`llm`) or the penalty order after a reorder error.
                        "backend": result.rerank_engine or "llm",
                        "rerank_query": result.rerank_query,
                        "chunks": reranked,
                    },
                },
                {
                    "kind": "selection",
                    "title": "K stretto",
                    "data": {
                        "chunks": [with_similarity(c) for c in chunks],
                    },
                },
            ],
        }

