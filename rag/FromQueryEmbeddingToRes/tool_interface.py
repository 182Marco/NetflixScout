from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from turn import OUTCOME_EMPTY, OUTCOME_OK, tool_outcome

from .constraints import constraint_summary
from .models import RagToolInput
from .pipeline import run_rag
from .retrieval_params import resolve_retrieval

RAG_TOOL_NAME = "rag_search"


@dataclass
class RagTool:
    """RAG retrieval tool used by an orchestrator for movie search and reranking."""

    name: str = RAG_TOOL_NAME
    description: str = (
        "Search the NetflixScout knowledge base for relevant movie plots and metadata. "
        "Returns the final reranked chunk set without generating a user-facing answer."
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: RagToolInput.model_json_schema()
    )
    config: dict[str, Any] = field(default_factory=dict)

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        # The user's standalone query drives the search; the planner's `arguments.query` is only
        # a hint for the query parser (real case: "Film simili a Mare dentro, che affrontino
        # temi e atmosfere analoghi" named no theme and replaced richer user context).
        planner_query = str(arguments.get("query") or "").strip()
        arguments["query"] = query or planner_query
        payload = RagToolInput(query=arguments["query"])
        hint = planner_query if planner_query and planner_query != payload.query else None
        # The planner's retrieval choices are applied to a copy of the config, clamped to the
        # configured limits; unusable values fall back to the defaults and never fail the turn.
        retrieval, overridden = resolve_retrieval(self.config.get("retrieval") or {}, arguments)
        call_config = {**self.config, "retrieval": retrieval}
        result = run_rag(config=call_config, query=payload.query, history=conversation_history, query_hint=hint)

        chunks = [chunk.model_dump(mode="json") for chunk in result.chunks]

        return {
            "query": result.query,
            "chunks": chunks,
            "outcome": tool_outcome(OUTCOME_OK if chunks else OUTCOME_EMPTY),
            "metadata": {
                "search_mode": result.search_mode.value,
                "rerank_backend": result.rerank_backend.value,
                "k_finale": retrieval.get("k_finale"),
                "collection": self.config.get("vectorstore", {}).get("collection"),
                # The prompt gets one readable line per film and constraint; the full report
                # (statuses, evidence) stays in the trace.
                **({"constraints_summary": constraint_summary(result.constraints)} if result.constraints else {}),
            },
            # Procedure steps for the presenters (same shape as turn.TraceStep).
            # Kept outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": [
                {
                    "kind": "retrieval",
                    "title": "K largo",
                    "data": {
                        "search_mode": result.search_mode.value,
                        "retrieval_params": {
                            "effective": {
                                k: (v.value if hasattr(v, "value") else v)
                                for k, v in retrieval.items()
                                if k in ("search_mode", "k_finale", "k_largo", "fetch_k", "genre_boost")
                            },
                            "overridden": sorted(overridden),
                        },
                        "standalone_query": query,
                        "planner_query": planner_query or None,
                        "embedded_text": result.embedded_text,
                        "signals": result.signals.model_dump(mode="json") if result.signals else None,
                        "chunks": [c.model_dump(mode="json") for c in result.candidates],
                    },
                },
                {
                    "kind": "rerank",
                    "title": "Reranking",
                    "data": {
                        "backend": result.rerank_backend.value,
                        "rerank_query": result.rerank_query,
                        "constraints": result.constraints,
                        "chunks": chunks,
                    },
                },
            ],
        }


RAG_TOOL = RagTool(config={})
REGISTERED_TOOLS = [RAG_TOOL]


def execute_tool(
    name: str,
    arguments: dict,
    config: dict,
) -> str:
    if name != RAG_TOOL_NAME:
        raise ValueError(f"Unknown tool: {name}")

    tool = RagTool(config=config)
    result = tool.run(query=arguments.get("query", ""), params=arguments)
    import json

    return json.dumps(result, ensure_ascii=False, indent=2)
