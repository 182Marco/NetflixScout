from __future__ import annotations

import json
from typing import Any, Protocol, Sequence, runtime_checkable

from openai import OpenAI


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        ...


class LLMOrchestrator:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        tools: Sequence[Tool],
        client: OpenAI | None = None,
    ) -> None:
        self.config = config
        self.tools = {tool.name: tool for tool in tools}
        self.client = client or OpenAI()
        self.orchestrator_config = config.get("orchestrator", {})

    def _build_final_context(
        self,
        *,
        query: str,
        tool_result: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        chunks = tool_result.get("chunks") or []
        metadata = tool_result.get("metadata") or {}

        summary_lines = [
            f"Domanda utente: {query}",
            f"Tool usato: {tool_result.get('tool_name') or 'unknown'}",
        ]
        if metadata:
            summary_lines.append(f"Metadata: {json.dumps(metadata, ensure_ascii=False)}")
        if chunks:
            summary_lines.append("Risultati strutturati:")
            for idx, chunk in enumerate(chunks[:10], start=1):
                text = str(chunk.get("testo") or chunk.get("content") or "").strip()
                title = chunk.get("title") or ""
                year = chunk.get("release_year") or chunk.get("release_date") or ""
                score = chunk.get("score")
                summary_lines.append(
                    f"[{idx}] {title + ' ' + year if title or year else ''} | score={score} | {text[:600]}"
                )

        history = list(conversation_history or [])
        message_payload = "\n".join(summary_lines)
        return [
            *history,
            {"role": "user", "content": message_payload},
        ]

    def _generate_final_answer(
        self,
        *,
        query: str,
        tool_result: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        try:
            response = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=(
                    "Sei l'orchestratore di un sistema multi-tool. "
                    "Usa esclusivamente i risultati strutturati ricevuti dal tool. "
                    "Non inventare informazioni. "
                    "Se i risultati non contengono dati sufficienti, rispondi in modo trasparente. "
                    "Scrivi una risposta finale chiara, utile e veritiera per l'utente."
                ),
                input=self._build_final_context(
                    query=query,
                    tool_result=tool_result,
                    conversation_history=conversation_history,
                ),
            )
            return (response.output_text or "").strip() or "Non ho abbastanza informazioni per rispondere."
        except Exception:
            chunks = tool_result.get("result", {}).get("chunks") or tool_result.get("chunks") or []
            if not chunks:
                return "Non ho abbastanza informazioni per rispondere."
            return "\n\n".join(
                chunk.get("testo", "")
                for chunk in chunks[:3]
                if isinstance(chunk, dict) and (chunk.get("testo") or chunk.get("content"))
            )

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }
            for tool in self.tools.values()
        ]

    def _tool_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
                "strict": False,
            }
            for tool in self.tools.values()
        ]

    def _allowed_tool_names(self) -> list[str]:
        allowed = self.orchestrator_config.get("allowed_tools")
        if not allowed:
            return list(self.tools)
        available = [tool_name for tool_name in allowed if tool_name in self.tools]
        if available:
            return available
        return list(self.tools)

    def _required_tool_names(self) -> list[str]:
        required = self.orchestrator_config.get("required_tools") or []
        return [tool_name for tool_name in required if tool_name in self.tools]

    def _select_tool(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        allowed = self._allowed_tool_names()
        if not allowed:
            raise ValueError("No tools are available to the orchestrator.")

        required = self._required_tool_names()
        if required:
            return required[0], {}

        decision_prompt = (
            "Decidi quale tool usare per rispondere alla query. "
            "Ritorna un JSON con queste chiavi: tool_name, arguments, confidence. "
            "Se non sei sicuro, usa il fallback tool."
        )

        try:
            response = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=(
                    self.orchestrator_config.get("instructions", decision_prompt)
                    + "\nAllowed tools: "
                    + ", ".join(allowed)
                ),
                input=[
                    *((conversation_history or [])[: self.orchestrator_config.get("memory_window_size", 12)]),
                    {"role": "user", "content": query},
                ],
            )
            payload = json.loads(response.output_text.strip())
            tool_name = payload.get("tool_name") or payload.get("tool") or allowed[0]
            arguments = payload.get("arguments") or {}
            confidence = payload.get("confidence")
            threshold = float(self.orchestrator_config.get("tool_confidence_threshold", 0.6))
            if tool_name in self.tools and (confidence is None or confidence >= threshold):
                return tool_name, arguments
        except Exception:
            pass

        fallback = self.orchestrator_config.get("fallback_tool") or allowed[0]
        if fallback in self.tools:
            return fallback, {}
        return allowed[0], {}

    def run(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        tool_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_name, args = self._select_tool(
            query=query,
            conversation_history=conversation_history,
        )
        tool = self.tools[tool_name]
        tool_result = tool.run(
            query=query,
            params={**(tool_overrides or {}), **args},
            conversation_history=conversation_history,
        )

        final_answer = self._generate_final_answer(
            query=query,
            tool_result={"tool_name": tool_name, **tool_result},
            conversation_history=conversation_history,
        )

        return {
            "tool": tool_name,
            "result": tool_result,
            "final_answer": final_answer,
        }
