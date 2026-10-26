from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from openai import OpenAI

from answer_stream import AnswerFieldStream
from data_coverage import coverage_rule

from turn import (
    OUTCOME_EMPTY,
    OUTCOME_OK,
    RESULT_FOLLOW_UP,
    STAGE_ANSWERING,
    STEP_PLANNING,
    STEP_QUERY_REWRITE,
    STEP_TOOL_OUTCOME,
    STEP_TOOL_SELECTION,
    TOOL_PARAM_TURN_ID,
    NullObserver,
    TraceStep,
    TurnObserver,
)

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
# Per-turn limits used when the config does not set them: planner calls, seconds of the tool
# loop, and tokens spent by the planner calls (see `_Limits`).
DEFAULT_MAX_ITERATIONS = 12
DEFAULT_MAX_EXECUTION_TIME = 180
DEFAULT_TOKEN_BUDGET = 200_000
# Characters of one tool result shown to the planner when it chooses the next step.
STEP_SUMMARY_CHARS = 2500


class _Limits:
    """The per-turn limits of one `run`: planner calls, wall-clock seconds and planner tokens.

    `exceeded()` is checked before every further planner call, so a step that would start after
    a limit is reached never starts; the turn then answers with the results it already has.
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.max_iterations = max(int(config.get("max_iterations", DEFAULT_MAX_ITERATIONS)), 1)
        self.max_execution_time = float(config.get("max_execution_time", DEFAULT_MAX_EXECUTION_TIME))
        self.token_budget = int(config.get("token_budget", DEFAULT_TOKEN_BUDGET))
        self.started = time.monotonic()
        self.iterations = 0
        self.tokens = 0

    def record(self, response: Any) -> None:
        """Count one planner call and the tokens its response reports (0 when it reports none)."""
        self.iterations += 1
        total = getattr(getattr(response, "usage", None), "total_tokens", None)
        if isinstance(total, int):
            self.tokens += total

    def exceeded(self) -> str | None:
        """The stop reason of the first limit already reached, else None."""
        if self.iterations >= self.max_iterations:
            return STOP_MAX_ITERATIONS
        if time.monotonic() - self.started >= self.max_execution_time:
            return STOP_MAX_EXECUTION_TIME
        if self.tokens >= self.token_budget:
            return STOP_TOKEN_BUDGET
        return None


@dataclass
class _Plan:
    """One planner decision: the tool to run and whether another step is expected after it."""

    tool: str
    arguments: dict[str, Any]
    standalone_query: str
    more_steps: bool = False
    # Parts of the request, each with the tool that answers it: [{"part": ..., "tool": ...}].
    parts: list[dict[str, str]] = field(default_factory=list)
    # Why the planner could not decide and a default tool was used (None: it decided).
    fallback: str | None = None


# Codes of `decision["planning"]["fallbacks"]`: moments the turn went on with less than planned.
FALLBACK_PLANNER_FAILED = "planner_failed"
FALLBACK_LOW_CONFIDENCE = "low_confidence"
FALLBACK_UNKNOWN_TOOL = "unknown_tool"
FALLBACK_NEXT_STEP = "next_step_failed"
FALLBACK_MAX_CALLS = "max_tool_calls"
# Stop reasons of the per-turn limits that `_Limits` enforces; each is also its fallback code.
STOP_MAX_ITERATIONS = "max_iterations"
STOP_MAX_EXECUTION_TIME = "max_execution_time"
STOP_TOKEN_BUDGET = "token_budget"
LIMIT_STOPS = (FALLBACK_MAX_CALLS, STOP_MAX_ITERATIONS, STOP_MAX_EXECUTION_TIME, STOP_TOKEN_BUDGET)
FALLBACK_ANSWER = "answer_failed"

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


# Contract of the next-step answer (stated to the planner in `NEXT_STEP_FORMAT`): `{"done": true}` ends the
# turn. A null or empty `tool_name`, or one of these words, is the same signal ONLY because the contract says
# so, and only if the planner does not also say `done: false` or `more_steps: true`. Anything else that names
# no tool (`{}`, a lone `confidence`, `done: false`, a string for `done`...) is an incomplete answer.
STOP_TOOL_NAMES = frozenset({"done", "none", "stop"})

NEXT_STEP_FORMAT = (
    "\nFormato di QUESTA risposta (prevale su quello indicato sopra per il primo passo; non scrivere "
    "standalone_query, parts né needs_clarification): per concludere rispondi {\"done\": true}. Equivale a "
    "concludere anche {\"tool_name\": null}, oppure un tool_name uguale a \"done\", \"none\" o \"stop\", "
    "purché more_steps non sia true e done non sia false. Per continuare rispondi con tool_name, arguments, "
    "confidence e more_steps. Non rispondere mai con un oggetto privo sia di done sia di tool_name."
)

NEXT_DONE = "done"
NEXT_STEP = "step"
NEXT_INCOMPLETE = "incomplete"


def _classify_next_step(payload: dict[str, Any]) -> tuple[str, str | None]:
    """`(kind, tool_name)` of the planner's answer for the next step.

    `done`: `{"done": true}` (a real boolean), or a stop signal of the contract (`tool_name` null, empty or
    `done`/`none`/`stop`) not contradicted by `done: false` or `more_steps: true`. `step`: a tool is named.
    `incomplete`: anything else, a contradiction included. Pure.
    """
    if payload.get("done") is True:
        return NEXT_DONE, None
    if "done" in payload and payload["done"] is not False and payload["done"] is not None:
        return NEXT_INCOMPLETE, None  # "true", 1...: not the boolean the contract asks for
    keys = [key for key in ("tool_name", "tool") if key in payload]
    if not keys:
        return NEXT_INCOMPLETE, None
    values = [payload[key] for key in keys]
    named = next((v.strip() for v in values if isinstance(v, str) and v.strip().lower() not in STOP_TOOL_NAMES | {""}), None)
    if named is not None:
        return NEXT_STEP, named
    stop_signal = all(v is None or (isinstance(v, str) and v.strip().lower() in STOP_TOOL_NAMES | {""}) for v in values)
    if stop_signal and payload.get("done") is not False and payload.get("more_steps") is not True:
        return NEXT_DONE, None
    return NEXT_INCOMPLETE, None


# Keys of the planner's answers the loop knows; any other key is reported as `<key>`.
_PLANNER_KEYS = frozenset(
    {
        "standalone_query", "tool_name", "tool", "arguments", "confidence", "parts", "more_steps", "done",
        "needs_clarification", "clarification_question",
    }
)


def _scalar(value: Any) -> Any:
    """Booleans, numbers and null as they are; any string only by its type (never free text)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


def _planner_detail(payload: Any, known_tools: Iterable[str]) -> dict[str, Any]:
    """What the planner answered for the next step, for the diagnostics, without free text or arguments:
    the known key names (others as `<key>`), the scalar fields the loop reads, and the tool name only if it
    is one of the app's tools or a stop word of the contract (else `<str>`)."""
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    detail: dict[str, Any] = {"keys": [key if key in _PLANNER_KEYS else "<key>" for key in list(payload)[:12]]}
    for name in ("done", "confidence", "more_steps"):
        if name in payload:
            detail[name] = _scalar(payload[name])
    for name in ("tool_name", "tool"):
        if name in payload:
            value = payload[name]
            known = isinstance(value, str) and (value in set(known_tools) or value.strip().lower() in STOP_TOOL_NAMES | {""})
            detail[name] = value if known else _scalar(value)
    return detail


def _follow_up(tool_result: dict[str, Any]) -> dict[str, Any] | None:
    """The tool's offer to give more (`turn.RESULT_FOLLOW_UP`), only when it says it is available."""
    follow_up = tool_result.get(RESULT_FOLLOW_UP)
    return follow_up if isinstance(follow_up, dict) and follow_up.get("available") is True else None


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


def _split_structured_output(text: str) -> tuple[str, list[Any]]:
    """`(answer, lists)` of the structured final output; ValueError if it is not usable."""
    payload = json.loads(text)
    answer = payload.get("answer") if isinstance(payload, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("structured final output without an answer")
    lists = payload.get("lists")
    return answer.strip(), lists if isinstance(lists, list) else []


FALLBACK_NO_ANSWER = "Non ho abbastanza informazioni per rispondere."

# Events of the Responses API stream that end the answer (anything else is progress or ignored).
EVENT_TEXT_DELTA = "response.output_text.delta"
EVENT_REFUSAL = ("response.refusal.delta", "response.refusal.done")
EVENT_COMPLETED = "response.completed"
EVENT_ABNORMAL_END = ("response.incomplete", "response.failed", "error")


def _consume_stream(
    events: Iterable[Any],
    raw: list[str],
    show: Callable[[str], None],
    decoder: AnswerFieldStream | None,
) -> str | None:
    """Read the stream of the final answer: the raw text goes to `raw`, the text to show goes
    to `show` (decoded from the `answer` field when `decoder` is given). Returns None when the
    response completed, else why it did not (`refusal`, the event type, `no_final_event`).
    An exception of the stream propagates to the caller."""
    refused = False
    for event in events:
        kind = getattr(event, "type", None)
        if kind == EVENT_TEXT_DELTA:
            delta = getattr(event, "delta", None) or ""
            raw.append(delta)
            show(decoder.feed(delta) if decoder else delta)
        elif kind in EVENT_REFUSAL:
            refused = True
        elif kind == EVENT_COMPLETED:
            return "refusal" if refused else None
        elif kind in EVENT_ABNORMAL_END:
            return kind
    return "no_final_event"


def _close(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


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
        failures: list[str] | None = None,
        final_output: Mapping[str, Any] | None = None,
        lists_out: list[Any] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """The answer text, written by ONE streamed call; a failure is appended to `failures`.

        `on_delta` gets the text as the model writes it (with `final_output`, the decoded text of
        the `answer` field of the JSON, never JSON). Every answer reaches it, also the fallback.

        With `final_output` (web only: `{"text_format", "instructions", "answer_field"}`) the same
        call asks for a strict JSON `{"answer", "lists"}`; `answer` is returned and the raw `lists`
        are added to `lists_out`. If the stream fails (call, refusal, incomplete, invalid JSON):
        the text already shown is the answer (no lists); with none shown, the fallback text. Never
        a second call.
        """
        results = tool_results or [tool_result or {}]
        instructions = self._final_instructions([r.get("tool_name") for r in results])
        extra: dict[str, Any] = {}
        decoder: AnswerFieldStream | None = None
        if final_output:
            instructions = f"{instructions} {final_output['instructions']}"
            extra["text"] = {"format": final_output["text_format"]}
            decoder = AnswerFieldStream(final_output.get("answer_field", "answer"))

        shown: list[str] = []

        def show(text: str) -> None:
            if text:
                shown.append(text)
                if on_delta:
                    on_delta(text)

        raw: list[str] = []
        stream: Any = None
        try:
            stream = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=instructions,
                input=self._build_final_context(
                    query=query,
                    tool_result=tool_result,
                    tool_results=tool_results,
                    conversation_history=conversation_history,
                    unexecuted=unexecuted,
                ),
                stream=True,
                **extra,
            )
            ended = _consume_stream(stream, raw, show, decoder)
        except Exception:
            ended = "error"
        finally:
            _close(stream)

        if ended is None:
            text = "".join(raw).strip()
            try:
                if final_output:
                    answer, lists = _split_structured_output(text)
                    if lists_out is not None:
                        lists_out.extend(lists)
                    return answer
                if text:
                    return text
                show(FALLBACK_NO_ANSWER)
                return FALLBACK_NO_ANSWER
            except ValueError:
                pass  # invalid JSON or no answer: the failure path below

        if failures is not None:
            failures.append(FALLBACK_ANSWER)
        already_shown = "".join(shown).strip()
        if already_shown:
            return already_shown  # the user saw it: that is the answer
        fallback = self._fallback_answer(results)
        show(fallback)
        return fallback

    @staticmethod
    def _fallback_answer(results: list[dict[str, Any]]) -> str:
        chunks = [
            chunk
            for result in results
            for chunk in (result.get("result", {}).get("chunks") or result.get("chunks") or [])
        ]
        if not chunks:
            return FALLBACK_NO_ANSWER
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

    def _coverage_for(self, allowed: list[str]) -> dict[str, Any]:
        coverage = self.orchestrator_config.get("data_coverage") or {}
        return {tool: info for tool, info in coverage.items() if tool in allowed}

    def _planning_instructions(self, allowed: list[str], decision_prompt: str) -> str:
        return (
            self.orchestrator_config.get("instructions", decision_prompt)
            + coverage_rule(self._coverage_for(allowed))
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
        limits: _Limits | None = None,
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
            if limits:
                limits.record(response)
            payload = json.loads(response.output_text.strip())
        except Exception:
            return _Plan(
                required[0] if required else self._fallback_tool_name(allowed),
                {},
                query,
                fallback=None if required else FALLBACK_PLANNER_FAILED,
            )

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
        return _Plan(
            self._fallback_tool_name(allowed),
            {},
            standalone_query,
            fallback=FALLBACK_UNKNOWN_TOOL if tool_name not in allowed else FALLBACK_LOW_CONFIDENCE,
        )

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
        # A tool that offers more describes its result itself (`follow_up.summary`): the planner
        # needs to see what was given and what was left out, not the first characters of it.
        follow_up = call.result.get(RESULT_FOLLOW_UP)
        summary = follow_up.get("summary") if isinstance(follow_up, dict) else None
        lines = [
            f"Tool {call.tool}, arguments: {json.dumps(call.arguments, ensure_ascii=False, default=str)}",
            *([summary] if isinstance(summary, str) and summary else self._result_lines(call.result)),
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
        limits: _Limits | None = None,
    ) -> tuple[_Plan | None, str, dict[str, Any] | None]:
        """Next step of the turn after `calls` and why the turn stops when there is none.

        Never falls back to a tool: if the planner fails or is unsure, the turn answers with
        what it already has. Returns (plan, "", detail) or (None, stop_reason, detail); `detail` is the
        sanitized description of the planner's answer (`_planner_detail`), None if there was no answer.
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
        follow_up = _follow_up(calls[-1].result)
        follow_up_text = (
            f"Il tool {calls[-1].tool} indica che può dare altro ({', '.join(map(str, follow_up.get('reasons') or []))}). "
            "Valuta se ciò che hai basta per la richiesta dell'utente: se no, scegli il passo "
            "successivo (con questo o un altro tool) usando i titoli e le sezioni elencati sopra; "
            'se sì, rispondi esattamente {"done": true}, senza altre chiavi: il formato del primo '
            "passo non vale per questa risposta.\n\n"
            if follow_up
            else ""
        )
        try:
            response = self.client.responses.create(
                model=self.orchestrator_config.get("llm_model", "gpt-5.6-luna"),
                instructions=self._planning_instructions(allowed, "") + NEXT_STEP_FORMAT,
                input=[
                    *list(conversation_history or []),
                    {"role": "user", "content": query},
                    {
                        "role": "user",
                        "content": (
                            f"Passi già eseguiti in questo turno:\n{done}\n\n{pending_text}{follow_up_text}"
                            "Se i dati bastano a rispondere a tutta la richiesta, ritorna "
                            '{"done": true}. Altrimenti ritorna il passo successivo come JSON '
                            "con chiavi tool_name, arguments, confidence, more_steps (true solo "
                            "se dopo questo passo ne serve ancora un altro), usando i dati già "
                            "ottenuti (titoli, nomi) e senza ripetere un passo già eseguito."
                        ),
                    },
                ],
            )
            if limits:
                limits.record(response)
            payload = json.loads(response.output_text.strip())
        except Exception:
            return None, "planner_failed", None

        detail = _planner_detail(payload, allowed)
        if not isinstance(payload, dict):
            return None, "planner_failed", detail
        kind, tool_name = _classify_next_step(payload)
        if kind == NEXT_DONE:
            return None, "done", detail
        if kind == NEXT_INCOMPLETE:
            return None, "planner_incomplete", detail
        confidence = payload.get("confidence")
        threshold = float(self.orchestrator_config.get("tool_confidence_threshold", 0.6))
        if tool_name not in allowed or (confidence is not None and confidence < threshold):
            return None, "unknown_tool_or_low_confidence", detail
        plan = _Plan(tool_name, payload.get("arguments") or {}, standalone_query, payload.get("more_steps") is True)
        return plan, "", detail

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

    @staticmethod
    def _emit(observer: TurnObserver, step: TraceStep) -> None:
        """Give a step to the observer as it happens; a broken observer never breaks the turn."""
        try:
            observer.step(step)
        except Exception:
            pass

    @staticmethod
    def _emit_status(observer: TurnObserver, stage: str) -> None:
        try:
            observer.status(stage)
        except Exception:
            pass

    @staticmethod
    def _planning(
        parts: list[dict[str, str]],
        calls: list[_Call],
        pending: list[dict[str, str]],
        stop_reason: str,
        fallbacks: list[str],
        planner_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        planning = {
            "parts": parts,
            "tools": [call.tool for call in calls],
            "pending": pending,
            "stop_reason": stop_reason,
            "fallbacks": list(fallbacks),
        }
        if planner_output is not None:
            # What the planner last answered for the next step, sanitized (no free text, no arguments).
            planning["planner_output"] = planner_output
        return planning

    @staticmethod
    def _emit_delta(observer: TurnObserver, text: str) -> None:
        try:
            observer.answer_delta(text)
        except Exception:
            pass

    @staticmethod
    def _purpose(plan: _Plan, calls: list[_Call], parts: list[dict[str, str]], standalone_query: str) -> str:
        """What this step looks for, in words: the planner's part for this tool, else the query."""
        done = sum(call.tool == plan.tool for call in calls)
        mine = [part["part"] for part in parts if part["tool"] == plan.tool]
        return mine[done] if done < len(mine) else standalone_query[:160]

    @staticmethod
    def _outcome(tool_result: dict[str, Any]) -> dict[str, Any]:
        """The tool's own `outcome`; tools that set none are judged by having chunks."""
        outcome = tool_result.get("outcome")
        if isinstance(outcome, dict) and outcome.get("status"):
            return {"status": outcome["status"], "reason": outcome.get("reason")}
        return {"status": OUTCOME_OK if tool_result.get("chunks") else OUTCOME_EMPTY, "reason": None}

    def run(
        self,
        *,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        tool_overrides: dict[str, Any] | None = None,
        observer: TurnObserver | None = None,
        final_output: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the tools the request needs, one after the other, then answer.

        The first planner call picks the first tool (and says whether more are needed); each
        later step is planned from the results so far. The loop ends when the planner is done,
        repeats a step, `max_tool_calls_per_turn` runs have happened, or a limit of
        `max_iterations` (planner calls), `max_execution_time` (seconds) or `token_budget`
        (planner tokens) is reached. The result keeps
        `tool` and `result` of the first call; `tools` and `calls` list every call in order.

        `observer` gets every step as it happens (`query_rewrite`, then per tool a
        `tool_selection` before the call and a `tool_outcome` plus the tool trace after it,
        `planning` last), so a channel can show the work while the user waits. The returned
        dict does not depend on it.

        `final_output` (web channel only, see `web_lists.final_output`) makes the final answer
        call return the answer plus structured list references in the same call; they come
        back as `final_lists`. Without it nothing changes.
        """
        observer = observer or NullObserver()
        limits = _Limits(self.orchestrator_config)
        plan = self._plan_first(query=query, conversation_history=conversation_history, limits=limits)
        standalone_query = plan.standalone_query
        self._emit(
            observer,
            TraceStep(
                kind=STEP_QUERY_REWRITE,
                title="Query usata dai tool",
                data={"original": query, "used": standalone_query, "rewritten": standalone_query != query},
            ),
        )
        if plan.tool == CLARIFICATION:
            # No tool and no final-answer call: nothing was looked up, so nothing is shown.
            self._emit(
                observer,
                TraceStep(kind=STEP_TOOL_SELECTION, title="Tool scelto", data={"tool": None, "clarification": True}),
            )
            self._emit_delta(observer, plan.arguments["question"])
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
        fallbacks: list[str] = [plan.fallback] if plan.fallback else []
        stop_reason = "complete"
        current: _Plan | None = plan
        planner_output: dict[str, Any] | None = None
        while current is not None:
            key = f"{current.tool}:{json.dumps(current.arguments, sort_keys=True, default=str)}"
            if key in seen:
                stop_reason = "repeated_step"
                break
            seen.add(key)
            self._emit(
                observer,
                TraceStep(
                    kind=STEP_TOOL_SELECTION,
                    title="Tool scelto",
                    data={
                        "tool": current.tool,
                        "purpose": self._purpose(current, calls, parts, standalone_query),
                        "arguments": current.arguments,
                    },
                ),
            )
            started = time.monotonic()
            tool_result = self.tools[current.tool].run(
                query=standalone_query,
                params={**(tool_overrides or {}), TOOL_PARAM_TURN_ID: turn_id, **current.arguments},
                conversation_history=conversation_history,
            )
            tool_result = self._enrich(current.tool, {**tool_result, "turn_id": turn_id})
            tool_result.pop("turn_id", None)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            calls.append(_Call(current.tool, current.arguments, tool_result))
            outcome = self._outcome(tool_result)
            self._emit(
                observer,
                TraceStep(
                    kind=STEP_TOOL_OUTCOME,
                    title="Esito",
                    data={"tool": current.tool, "elapsed_ms": elapsed_ms, **outcome},
                ),
            )
            for trace_step in tool_result.get("trace", []):
                self._emit(observer, TraceStep(**trace_step))
            if self._required_tool_names():
                stop_reason = "required_tools"
                break
            if not (current.more_steps or _pending_parts(parts, calls) or _follow_up(tool_result)):
                stop_reason = "complete"
                break
            if len(calls) >= limit:
                stop_reason = "max_tool_calls"
                break
            if exceeded := limits.exceeded():
                stop_reason = exceeded
                break
            current, stop_reason, planner_output = self._plan_next(
                query=query,
                standalone_query=standalone_query,
                conversation_history=conversation_history,
                calls=calls,
                parts=parts,
                limits=limits,
            )

        if stop_reason in LIMIT_STOPS:
            fallbacks.append(stop_reason)
        elif stop_reason in ("planner_failed", "planner_incomplete", "unknown_tool_or_low_confidence"):
            fallbacks.append(FALLBACK_NEXT_STEP)
        pending = _pending_parts(parts, calls)
        unexecuted = [f"{p['part']} (tool previsto: {p['tool']}, motivo: {stop_reason})" for p in pending]
        results = [{"tool_name": call.tool, **call.result} for call in calls]
        # Before the answer, so the lines about what was not searched come before the text. Only
        # the failure of the answer itself is known later (second, minimal step below).
        if len(calls) > 1 or pending or fallbacks:
            self._emit(
                observer,
                TraceStep(
                    kind=STEP_PLANNING,
                    title="Pianificazione",
                    data=self._planning(parts, calls, pending, stop_reason, fallbacks, planner_output),
                ),
            )
        self._emit_status(observer, STAGE_ANSWERING)
        final_lists: list[Any] = []
        answer_failures: list[str] = []
        final_answer = self._generate_final_answer(
            query=query,
            tool_result=results[0] if len(results) == 1 else None,
            tool_results=results if len(results) > 1 else None,
            conversation_history=conversation_history,
            unexecuted=unexecuted,
            failures=answer_failures,
            final_output=final_output,
            lists_out=final_lists,
            on_delta=lambda text: self._emit_delta(observer, text),
        )
        if answer_failures:
            self._emit(
                observer,
                TraceStep(
                    kind=STEP_PLANNING,
                    title="Pianificazione",
                    data=self._planning([], calls, [], stop_reason, answer_failures),
                ),
            )
        fallbacks.extend(answer_failures)
        planning = self._planning(parts, calls, pending, stop_reason, fallbacks, planner_output)

        return {
            "tool": calls[0].tool,
            "tools": [call.tool for call in calls],
            "calls": [{"tool": c.tool, "arguments": c.arguments, "result": c.result} for c in calls],
            "standalone_query": standalone_query,
            "result": calls[0].result,
            "planning": planning,
            "final_answer": final_answer,
            "final_lists": final_lists,
        }
