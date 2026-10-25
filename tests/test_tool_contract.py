from __future__ import annotations

from app import CONFIG
from orchestrator import LLMOrchestrator
from tool.rag.FromQueryEmbeddingToRes.tool_interface import RagTool


def test_app_config_has_orchestrator_and_rag_sections() -> None:
    assert "orchestrator" in CONFIG
    assert "rag" in CONFIG
    assert "conversation" in CONFIG["orchestrator"]
    assert "retrieval" in CONFIG["rag"]
    assert "generation" in CONFIG["rag"]


def test_rag_tool_returns_structured_results() -> None:
    tool = RagTool(config=CONFIG["rag"])
    result = tool.run(query="film con fantasia e avventura", params={}, conversation_history=[])

    assert "query" in result
    assert "chunks" in result
    assert isinstance(result["chunks"], list)
    assert "metadata" in result
    assert result["metadata"]["k_finale"] == CONFIG["rag"]["retrieval"]["k_finale"]


def test_orchestrator_sees_registered_tool() -> None:
    orchestrator = LLMOrchestrator(config=CONFIG, tools=[RagTool(config=CONFIG["rag"])])
    tools = orchestrator.list_tools()

    assert any(tool["name"] == "rag_search" for tool in tools)
