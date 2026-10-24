from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from openai import OpenAI

from turn import TOOL_PARAM_TURN_ID

DEFAULT_FINAL_INSTRUCTIONS = (
    "Sei l'orchestratore di un sistema multi-tool. "
    "Usa esclusivamente i risultati strutturati ricevuti dal tool. "
    "Non inventare informazioni. "
    "Se i risultati non contengono dati sufficienti, rispondi in modo trasparente. "
    "Scrivi una risposta finale chiara, utile e veritiera per l'utente."
)

# Planner decision with no tool: the request cannot be answered without information only the
# user has (e.g. "that Sorrentino movie" with no history). The planner's question is the answer.
CLARIFICATION = "clarification"

# Ceiling of tool runs in one turn when `orchestrator.max_tool_calls_per_turn` is not set.
DEFAULT_MAX_TOOL_CALLS = 10
# Characters of one tool result shown to the planner when it chooses the next step.
STEP_SUMMARY_CHARS = 2500


@dataclass
class _Plan:
    """One planner decision: the tool to run and whether another step is expected after it."""

    tool: str
    arguments: dict[str, Any]
    standalone_query: str
    more_steps: bool = False
    # Parts of the request, each with the tool that answers it: [{"part": ..., "tool": ...}].
    parts: list[dict[str, str]] = field(default_factory=list)

MAX_PARTS = 6


def _parse_parts(payload: dict[str, Any], allowed: list[str]) -> list[dict[str, str]]:
    """The planner's `parts`, keeping only well-formed entries that name an allowed tool."""
    raw = payload.get("parts")
    if not isinstance(raw, list):
        return []
    parts = []
    for item in raw[:MAX_PARTS]:
        if isinstance(item, dict) and item.get("tool") in allowed and str(item.get("part") or "").strip():
            parts.append({"part": str(item["part"]).strip()[:200], "tool": item["tool"]})
    return parts


def _pending_parts(parts: list[dict[str, str]], calls: list[_Call]) -> list[dict[str, str]]:
    """Parts whose tool has not run yet in this turn."""
    ran = {call.tool for call in calls}
    return [part for part in parts if part["tool"] not in ran]


@dataclass
class _Call:
    """One tool run of the turn."""

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)


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


@runtime_checkable
class Enricher(Protocol):
    """Completes the result of one tool before the final answer (e.g. TMDb metadata for RAG hits).

    It must keep the tool result contract (`query`, `chunks`, `metadata`, `trace`) and must
    not reorder `chunks`.
    """

    def enrich(self, *, tool_result: dict[str, Any]) -> dict[str, Any]:
        ...


class LLMOrchestrator:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        tools: Sequence[Tool],
        client: OpenAI | None = None,
        enrichers: Mapping[str, Enricher] | None = None,
    ) -> None:
        self.config = config
        self.tools = {tool.name: tool for tool in tools}
        self.client = client or OpenAI()
        # Tool name -> enricher run on that tool's result, in the same turn.
        self.enrichers = dict(enrichers or {})
        self.orchestrator_config = config.get("orchestrator", {})

    def _build_final_context(
        self,
        *,
        query: str,
        tool_result: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        unexecuted: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Prompt of the final answer. `tool_results` (a turn with several tools, in
        execution order) takes the place of `tool_result`; each result keeps its `tool_name`."""
        results = tool_results or [tool_result or {}]
        summary_lines = [f"Domanda utente: {query}"]
        if len(results) == 1:
            summary_lines.append(f"Tool usato: {results[0].get('tool_name') or 'unknown'}")
            summary_lines.extend(self._result_lines(results[0]))
        else:
            names = ", ".join(str(r.get("tool_name") or "unknown") for r in results)
            summary_lines.append(f"Tool usati, in ordine di esecuzione: {names}")
            for number, result in enumerate(results, start=1):
                summary_lines.append(f"--- Risultato {number}: tool {result.get('tool_name') or 'unknown'}")
                summary_lines.extend(self._result_lines(result))

        if unexecuted:
            summary_lines.append(
                "Parti della richiesta NON eseguite (nessun tool le ha cercate, quindi non c'è "
                "nessun esito da riportare): " + "; ".join(unexecuted)
            )

        history = list(conversation_history or [])
        message_payload = "\n".join(summary_lines)
        return [
            *history,
            {"role": "user", "content": message_payload},
        ]

    @staticmethod
    def _result_lines(tool_result: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        metadata = tool_result.get("metadata") or {}
        if metadata:
            lines.append(f"Metadata: {json.dumps(metadata, ensure_ascii=False)}")
        chunks = tool_result.get("chunks") or []
        if chunks:
            lines.append("Risultati strutturati:")
            for idx, chunk in enumerate(chunks[:10], start=1):
                text = str(chunk.get("testo") or chunk.get("content") or "").strip()
                title = chunk.get("title") or ""
                year = chunk.get("release_year") or chunk.get("release_date") or ""
                genres = chunk.get("genres") or ""
                score = chunk.get("score")
                lines.append(
                    f"[{idx}] {title + ' ' + year if title or year else ''} | generi={genres} "
                    f"| score={score} | {text[:600]}"
                )
        return lines

    def _final_instructions(self, tool_name: str | Sequence[str] | None) -> str:
        """`final_instructions` plus the rules of every tool that ran, if it has any
        (`tool_final_instructions`): turns of other tools do not carry them."""
        base = self.orchestrator_config.get("final_instructions") or DEFAULT_FINAL_INSTRUCTIONS
        names = [tool_name] if isinstance(tool_name, str) or tool_name is None else list(tool_name)
        rules = self.orchestrator_config.get("tool_final_instructions") or {}
        extras = list(dict.fromkeys(rules[name] for name in names if name and rules.get(name)))
        return " ".join([base, *extras])

    def _generate_final_answer(
        self,
        *,
        query: str,
        tool_result: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        unexecuted: list[str] | None = None,
    ) -> str:
        results = tool_results or [tool_result or {}]
        try:
            response = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=self._final_instructions([r.get("tool_name") for r in results]),
                input=self._build_final_context(
                    query=query,
                    tool_result=tool_result,
                    tool_results=tool_results,
                    conversation_history=conversation_history,
                    unexecuted=unexecuted,
                ),
            )
            return (response.output_text or "").strip() or "Non ho abbastanza informazioni per rispondere."
        except Exception:
            chunks = [
                chunk
                for result in results
                for chunk in (result.get("result", {}).get("chunks") or result.get("chunks") or [])
            ]
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

    def _catalog_text(self, tool_names: list[str]) -> str:
        """Name, description and parameters of the allowed tools, for the planning prompt."""
        return "\n".join(
            json.dumps(
                {
                    "name": name,
                    "description": self.tools[name].description,
                    "parameters": self.tools[name].input_schema,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for name in tool_names
        )

    def _planning_instructions(self, allowed: list[str], decision_prompt: str) -> str:
        return (
            self.orchestrator_config.get("instructions", decision_prompt)
            + "\nAllowed tools: "
            + ", ".join(allowed)
            + "\nTool catalog (arguments must follow the tool parameters):\n"
            + self._catalog_text(allowed)
        )

    def _plan_first(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> _Plan:
        """First planner decision of the turn (see `_plan_turn`), plus `more_steps`."""
        allowed = self._allowed_tool_names()
        if not allowed:
            raise ValueError("No tools are available to the orchestrator.")

        history = list(conversation_history or [])
        required = self._required_tool_names()
        # First turn: nothing to resolve from history and no tool choice to make.
        if required and not history:
            return _Plan(required[0], {}, query)

        decision_prompt = (
            "Decidi quale tool usare per rispondere alla query. "
            "Ritorna un JSON con queste chiavi: standalone_query, tool_name, arguments, confidence. "
            "Se non sei sicuro, usa il fallback tool."
        )

        try:
            response = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=self._planning_instructions(allowed, decision_prompt),
                # Full history, unchanged and in order: a stable prompt prefix lets the
                # provider's prompt caching reuse it across turns.
                input=[
                    *history,
                    {"role": "user", "content": query},
                ],
            )
            payload = json.loads(response.output_text.strip())
        except Exception:
            return _Plan(required[0] if required else self._fallback_tool_name(allowed), {}, query)

        rewritten = str(payload.get("standalone_query") or "").strip()
        standalone_query = rewritten if history and rewritten else query

        if required:
            return _Plan(required[0], {}, standalone_query)

        question = str(payload.get("clarification_question") or "").strip()
        if payload.get("needs_clarification") is True and question:
            return _Plan(CLARIFICATION, {"question": question}, standalone_query)

        tool_name = payload.get("tool_name") or payload.get("tool") or allowed[0]
        arguments = payload.get("arguments") or {}
        confidence = payload.get("confidence")
        threshold = float(self.orchestrator_config.get("tool_confidence_threshold", 0.6))
        if tool_name in allowed and (confidence is None or confidence >= threshold):
            parts = _parse_parts(payload, allowed)
            # A part for another tool means another step, whatever `more_steps` says.
            more_steps = payload.get("more_steps") is True or any(p["tool"] != tool_name for p in parts)
            return _Plan(tool_name, arguments, standalone_query, more_steps, parts)
        return _Plan(self._fallback_tool_name(allowed), {}, standalone_query)

    def _plan_turn(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        """Pick the first tool and rewrite the query as standalone, in a single LLM call.

        Returns (tool_name, arguments, standalone_query). The standalone query is a
        property of the turn, not of the tool: it is used whatever tool runs, also when
        the tool comes from `required_tools` or from the fallback. If the LLM call fails,
        the original query is used. `CLARIFICATION` (with `{"question": ...}`) means no
        tool: the planner set `needs_clarification` and wrote the question. Never with
        `required_tools`. Later steps of the same turn come from `_plan_next`.
        """
        plan = self._plan_first(query=query, conversation_history=conversation_history)
        return plan.tool, plan.arguments, plan.standalone_query

    def _summarize_call(self, call: _Call) -> str:
        lines = [
            f"Tool {call.tool}, arguments: {json.dumps(call.arguments, ensure_ascii=False, default=str)}",
            *self._result_lines(call.result),
        ]
        return "\n".join(lines)[:STEP_SUMMARY_CHARS]

    def _plan_next(
        self,
        *,
        query: str,
        standalone_query: str,
        conversation_history: list[dict[str, str]] | None,
        calls: list[_Call],
        parts: list[dict[str, str]] | None = None,
    ) -> tuple[_Plan | None, str]:
        """Next step of the turn after `calls` and why the turn stops when there is none.

        Never falls back to a tool: if the planner fails or is unsure, the turn answers with
        what it already has. Returns (plan, "") or (None, stop_reason).
        """
        allowed = self._allowed_tool_names()
        done = "\n\n".join(f"[Passo {i}] {self._summarize_call(c)}" for i, c in enumerate(calls, start=1))
        pending = _pending_parts(parts or [], calls)
        pending_text = (
            "Parti della richiesta ancora senza risultati (tool previsto): "
            + json.dumps(pending, ensure_ascii=False)
            + ". Scegli il tool di una di queste parti, con i dati già ottenuti; ritorna done solo "
            "se quei dati rendono la parte impossibile.\n\n"
            if pending
            else ""
        )
        try:
            response = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=self._planning_instructions(allowed, ""),
                input=[
                    *list(conversation_history or []),
                    {"role": "user", "content": query},
                    {
                        "role": "user",
                        "content": (
                            f"Passi già eseguiti in questo turno:\n{done}\n\n{pending_text}"
                            "Se i dati bastano a rispondere a tutta la richiesta, ritorna "
                            '{"done": true}. Altrimenti ritorna il passo successivo come JSON '
                            "con chiavi tool_name, arguments, confidence, more_steps (true solo "
                            "se dopo questo passo ne serve ancora un altro), usando i dati già "
                            "ottenuti (titoli, nomi) e senza ripetere un passo già eseguito."
                        ),
                    },
                ],
            )
            payload = json.loads(response.output_text.strip())
        except Exception:
            return None, "planner_failed"

        if not isinstance(payload, dict):
            return None, "planner_failed"
        if payload.get("done") is True:
            return None, "done"
        tool_name = payload.get("tool_name") or payload.get("tool")
        confidence = payload.get("confidence")
        threshold = float(self.orchestrator_config.get("tool_confidence_threshold", 0.6))
        if tool_name not in allowed or (confidence is not None and confidence < threshold):
            return None, "unknown_tool_or_low_confidence"
        plan = _Plan(tool_name, payload.get("arguments") or {}, standalone_query, payload.get("more_steps") is True)
        return plan, ""

    def _enrich(self, tool_name: str, tool_result: dict[str, Any]) -> dict[str, Any]:
        """Run the tool's enricher, if any; a failing enricher never breaks the turn."""
        enricher = self.enrichers.get(tool_name)
        if enricher is None:
            return tool_result
        try:
            return enricher.enrich(tool_result=tool_result)
        except Exception:
            metadata = {**(tool_result.get("metadata") or {}), "enrichment_error": True}
            return {**tool_result, "metadata": metadata}

    def run(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        tool_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the tools the request needs, one after the other, then answer.

        The first planner call picks the first tool (and says whether more are needed); each
        later step is planned from the results so far. The loop ends when the planner is done,
        repeats a step, or `max_tool_calls_per_turn` runs have happened. The result keeps
        `tool` and `result` of the first call; `tools` and `calls` list every call in order.
        """
        plan = self._plan_first(query=query, conversation_history=conversation_history)
        standalone_query = plan.standalone_query
        if plan.tool == CLARIFICATION:
            # No tool and no final-answer call: nothing was looked up, so nothing is shown.
            return {
                "tool": None,
                "tools": [],
                "calls": [],
                "clarification": True,
                "standalone_query": standalone_query,
                "result": {"query": standalone_query, "chunks": [], "metadata": {}, "trace": []},
                "final_answer": plan.arguments["question"],
            }

        limit = max(int(self.orchestrator_config.get("max_tool_calls_per_turn", DEFAULT_MAX_TOOL_CALLS)), 1)
        turn_id = uuid.uuid4().hex
        calls: list[_Call] = []
        seen: set[str] = set()
        parts = plan.parts
        stop_reason = "complete"
        current: _Plan | None = plan
        while current is not None:
            key = f"{current.tool}:{json.dumps(current.arguments, sort_keys=True, default=str)}"
            if key in seen:
                stop_reason = "repeated_step"
                break
            seen.add(key)
            tool_result = self.tools[current.tool].run(
                query=standalone_query,
                params={**(tool_overrides or {}), TOOL_PARAM_TURN_ID: turn_id, **current.arguments},
                conversation_history=conversation_history,
            )
            tool_result = self._enrich(current.tool, {**tool_result, "turn_id": turn_id})
            tool_result.pop("turn_id", None)
            calls.append(_Call(current.tool, current.arguments, tool_result))
            if self._required_tool_names():
                stop_reason = "required_tools"
                break
            if not (current.more_steps or _pending_parts(parts, calls)):
                stop_reason = "complete"
                break
            if len(calls) >= limit:
                stop_reason = "max_tool_calls"
                break
            current, stop_reason = self._plan_next(
                query=query,
                standalone_query=standalone_query,
                conversation_history=conversation_history,
                calls=calls,
                parts=parts,
            )

        pending = _pending_parts(parts, calls)
        unexecuted = [f"{p['part']} (tool previsto: {p['tool']}, motivo: {stop_reason})" for p in pending]
        results = [{"tool_name": call.tool, **call.result} for call in calls]
        final_answer = self._generate_final_answer(
            query=query,
            tool_result=results[0] if len(results) == 1 else None,
            tool_results=results if len(results) > 1 else None,
            conversation_history=conversation_history,
            unexecuted=unexecuted,
        )
        planning = {
            "parts": parts,
            "tools": [call.tool for call in calls],
            "pending": pending,
            "stop_reason": stop_reason,
        }

        return {
            "tool": calls[0].tool,
            "tools": [call.tool for call in calls],
            "calls": [{"tool": c.tool, "arguments": c.arguments, "result": c.result} for c in calls],
            "standalone_query": standalone_query,
            "result": calls[0].result,
            "planning": planning,
            "final_answer": final_answer,
        }
