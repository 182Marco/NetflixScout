from __future__ import annotations

from aikit import definisci_tool

from rag_support.models import RagToolInput
from rag_support.pipeline import run_rag

RAG_TOOL_NAME = "rag_search"
RAG_TOOL = definisci_tool(RagToolInput, RAG_TOOL_NAME)
REGISTERED_TOOLS = [RAG_TOOL]


def execute_tool(
    name: str,
    arguments: dict,
    config: dict,
) -> str:
    if name != RAG_TOOL_NAME:
        raise ValueError(f"Unknown tool: {name}")

    payload = RagToolInput(**arguments)
    result = run_rag(config=config, query=payload.query)

    return result.model_dump_json(indent=2)
