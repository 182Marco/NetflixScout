from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import RagToolInput
from .pipeline import run_rag

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
        if query:
            arguments["query"] = query
        payload = RagToolInput(**arguments)
        result = run_rag(config=self.config, query=payload.query, history=conversation_history)

        chunks = [chunk.model_dump(mode="json") for chunk in result.chunks]

        return {
            "query": result.query,
            "chunks": chunks,
            "metadata": {
                "search_mode": result.search_mode.value,
                "rerank_backend": result.rerank_backend.value,
                "k_finale": self.config.get("retrieval", {}).get("k_finale"),
                "collection": self.config.get("vectorstore", {}).get("collection"),
            },
            # Procedure steps for the presenters (same shape as turn.TraceStep).
            # Kept outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": [
                {
                    "kind": "retrieval",
                    "title": "K largo",
                    "data": {
                        "search_mode": result.search_mode.value,
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
