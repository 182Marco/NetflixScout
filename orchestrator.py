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
                genres = chunk.get("genres") or ""
                score = chunk.get("score")
                summary_lines.append(
                    f"[{idx}] {title + ' ' + year if title or year else ''} | generi={genres} "
                    f"| score={score} | {text[:600]}"
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

    def _fallback_tool_name(self, allowed: list[str]) -> str:
        fallback = self.orchestrator_config.get("fallback_tool") or allowed[0]
        return fallback if fallback in self.tools else allowed[0]

    def _plan_turn(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        """Pick the tool and rewrite the query as standalone, in a single LLM call.

        Returns (tool_name, arguments, standalone_query). The standalone query is a
        property of the turn, not of the tool: it is used whatever tool runs, also when
        the tool comes from `required_tools` or from the fallback. If the LLM call fails,
        the original query is used.
        """
        allowed = self._allowed_tool_names()
        if not allowed:
            raise ValueError("No tools are available to the orchestrator.")

        history = list(conversation_history or [])
        required = self._required_tool_names()
        # First turn: nothing to resolve from history and no tool choice to make.
        if required and not history:
            return required[0], {}, query

        decision_prompt = (
            "Decidi quale tool usare per rispondere alla query. "
            "Ritorna un JSON con queste chiavi: standalone_query, tool_name, arguments, confidence. "
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
                # Full history, unchanged and in order: a stable prompt prefix lets the
                # provider's prompt caching reuse it across turns.
                input=[
                    *history,
                    {"role": "user", "content": query},
                ],
            )
            payload = json.loads(response.output_text.strip())
        except Exception:
            return (required[0] if required else self._fallback_tool_name(allowed)), {}, query

        rewritten = str(payload.get("standalone_query") or "").strip()
        standalone_query = rewritten if history and rewritten else query

        if required:
            return required[0], {}, standalone_query

        tool_name = payload.get("tool_name") or payload.get("tool") or allowed[0]
        arguments = payload.get("arguments") or {}
        confidence = payload.get("confidence")
        threshold = float(self.orchestrator_config.get("tool_confidence_threshold", 0.6))
        if tool_name in allowed and (confidence is None or confidence >= threshold):
            return tool_name, arguments, standalone_query
        return self._fallback_tool_name(allowed), {}, standalone_query

    def run(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        tool_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_name, args, standalone_query = self._plan_turn(
            query=query,
            conversation_history=conversation_history,
        )
        tool = self.tools[tool_name]
        tool_result = tool.run(
            query=standalone_query,
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
            "standalone_query": standalone_query,
            "result": tool_result,
            "final_answer": final_answer,
        }
