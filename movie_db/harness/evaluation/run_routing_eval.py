"""Evaluate DB/RAG/TMDb/YouTube routing with the real classifier and planner (costs API credits).

Per case: one classifier call (`gpt-4o-mini`) and one planning call; tools never run.
The planner client is wrapped to record its raw output, so a silent fallback to
`fallback_tool` (invalid JSON, unknown tool, low confidence) is told apart from an
explicit choice. The orchestrator core is used as is. For TMDb cases the planned
arguments are also validated offline as `TmdbToolInput` (no HTTP) and must contain the
case's `expected_request`; for YouTube cases they are validated as `YoutubeToolInput` and
must match the case's `expected_video` (kinds, and no year, people or titles not given).

    python -m movie_db.harness.evaluation.run_routing_eval --live
    python -m movie_db.harness.evaluation.run_routing_eval --live --tool tmdb_search
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import ValidationError

from orchestrator import CLARIFICATION
from tmdb.models.requests import TmdbRequest, TmdbToolInput, describe_validation_errors
from turn import TOOL_PARAM_TURN_LANGUAGE
from youtube.models import YoutubeToolInput
from youtube.models import describe_validation_errors as describe_video_errors

from .routing_cases import ROUTING_CASES, RagExpectation, RequestExpectation, RoutingCase, VideoExpectation

# Optional `youtube_search` fields that must come from the request or the conversation.
_VIDEO_GIVEN_FIELDS = ("year", "director", "cast", "alternative_titles")


class RecordingClient:
    """Wrap an OpenAI-like client and keep the raw text of every `responses.create`."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.outputs: list[str] = []
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        response = self._client.responses.create(**kwargs)
        self.outputs.append(response.output_text or "")
        return response


@dataclass
class RoutingResult:
    case: RoutingCase
    is_cinema: bool | None
    tool: str
    standalone_query: str
    source: str  # "planner" or "fallback: <reason>"
    confidence: float | None = None
    error: str | None = None
    arguments: Any = None

    @property
    def requests_problem(self) -> str | None:
        """Why the planned TMDb or YouTube arguments are wrong; None when fine or not checked."""
        if self.tool != self.case.expected_tool:
            return None
        if self.case.expected_request is not None:
            return check_any_request(self.case.expected_request, self.arguments, self.standalone_query)
        if self.case.expected_video is not None:
            return check_any_video(self.case.expected_video, self.arguments, self.standalone_query)
        if self.case.expected_rag is not None:
            return check_rag(self.case.expected_rag, self.arguments)
        return None

    @property
    def standalone_ok(self) -> bool:
        text = self.standalone_query.casefold()
        return all(fragment in text for fragment in self.case.standalone_must_contain)

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.is_cinema is True
            and self.tool == self.case.expected_tool
            and self.source == "planner"
            and self.standalone_ok
            and self.requests_problem is None
        )


def _planned_payload(arguments: dict, standalone_query: str) -> dict:
    """The arguments as the tool receives them: no turn language, the standalone query."""
    payload = {key: value for key, value in arguments.items() if key != TOOL_PARAM_TURN_LANGUAGE}
    payload["query"] = standalone_query
    return payload


def _matches(expected: RequestExpectation, request: TmdbRequest) -> bool:
    if request.operation.value != expected.operation:
        return False
    for name, fragment in expected.fields:
        value = getattr(request, name, None)
        text = value.value if isinstance(value, Enum) else value
        if not isinstance(text, str) or fragment not in text.casefold():
            return False
    return set(expected.facets) <= {facet.value for facet in request.facets}


def check_requests(expected: RequestExpectation, arguments: Any, standalone_query: str) -> str | None:
    """Validate planned arguments as `TmdbTool.run` would, without running the tool."""
    if not isinstance(arguments, dict):
        return "arguments is not an object"
    try:
        parsed = TmdbToolInput.model_validate(_planned_payload(arguments, standalone_query))
    except ValidationError as exc:
        return f"invalid requests: {describe_validation_errors(exc)}"
    if any(_matches(expected, request) for request in parsed.requests):
        return None
    return f"no request matches {expected}"


def check_any_request(
    expected: RequestExpectation | tuple[RequestExpectation, ...],
    arguments: Any,
    standalone_query: str,
) -> str | None:
    """None when any of the acceptable expectations matches; otherwise the first problem."""
    options = expected if isinstance(expected, tuple) else (expected,)
    problems = [check_requests(option, arguments, standalone_query) for option in options]
    return None if any(problem is None for problem in problems) else problems[0]


def _video_problem(expected: VideoExpectation, request: YoutubeToolInput) -> str | None:
    if expected.title not in request.title.casefold():
        return f"title {request.title!r} does not contain {expected.title!r}"
    kinds = [kind.value for kind in request.kinds]
    missing = [kind for kind in expected.kinds if kind not in kinds]
    if missing:
        return f"missing kinds {missing}"
    unexpected = [kind for kind in kinds if kind not in expected.kinds + expected.extra_kinds]
    if unexpected:
        return f"kinds not requested {unexpected}"
    for name in _VIDEO_GIVEN_FIELDS:
        value = getattr(request, name)
        values = value if isinstance(value, list) else [] if value is None else [value]
        fragments = [fragment for field_name, fragment in expected.allowed if field_name == name]
        for item in values:
            if not any(fragment in str(item).casefold() for fragment in fragments):
                return f"{name} not given in the conversation"
    return None


def check_video(expected: VideoExpectation, arguments: Any, standalone_query: str) -> str | None:
    """Validate planned arguments as `YoutubeTool.run` would, without running the tool."""
    if not isinstance(arguments, dict):
        return "arguments is not an object"
    try:
        request = YoutubeToolInput.model_validate(_planned_payload(arguments, standalone_query))
    except ValidationError as exc:
        return f"invalid arguments: {describe_video_errors(exc)}"
    return _video_problem(expected, request)


def check_any_video(
    expected: VideoExpectation | tuple[VideoExpectation, ...],
    arguments: Any,
    standalone_query: str,
) -> str | None:
    """None when any of the acceptable expectations matches; otherwise the first problem."""
    options = expected if isinstance(expected, tuple) else (expected,)
    problems = [check_video(option, arguments, standalone_query) for option in options]
    return None if any(problem is None for problem in problems) else problems[0]


def check_rag(expected: RagExpectation, arguments: Any) -> str | None:
    """Check the `k_finale` the planner set, as `RagTool.run` would read it."""
    if not isinstance(arguments, dict):
        return "arguments is not an object"
    counts = expected.k_finale if isinstance(expected.k_finale, tuple) else (expected.k_finale,)
    if arguments.get("k_finale") not in counts:
        return f"k_finale {arguments.get('k_finale')!r} not in {counts}"
    return None


def select_cases(tool: str | None) -> tuple[RoutingCase, ...]:
    return tuple(case for case in ROUTING_CASES if tool is None or case.expected_tool == tool)


def _planning_source(raw: str, tool: str, orchestrator: Any) -> tuple[str, float | None]:
    try:
        payload = json.loads(raw.strip())
    except (json.JSONDecodeError, AttributeError):
        return "fallback: invalid JSON", None
    if not isinstance(payload, dict):
        return "fallback: invalid JSON", None
    chosen = payload.get("tool_name") or payload.get("tool")
    confidence = payload.get("confidence")
    if tool == CLARIFICATION and payload.get("needs_clarification") is True:
        return "planner", confidence
    if chosen != tool:
        threshold = float(orchestrator.orchestrator_config.get("tool_confidence_threshold", 0.6))
        if chosen not in orchestrator._allowed_tool_names():
            return f"fallback: unknown tool {chosen!r}", confidence
        if confidence is not None and confidence < threshold:
            return f"fallback: confidence {confidence} < {threshold}", confidence
        return f"fallback: planner chose {chosen!r}", confidence
    return "planner", confidence


def run_routing_cases(
    cases: tuple[RoutingCase, ...],
    *,
    orchestrator: Any,
    classify: Any,
    context_size: int,
) -> list[RoutingResult]:
    """`orchestrator.client` must be a `RecordingClient`."""
    recorder: RecordingClient = orchestrator.client
    results = []
    for case in cases:
        history = list(case.history)
        try:
            classification = classify(case.question, history[-context_size:] if context_size else [])
        except Exception as exc:  # noqa: BLE001
            results.append(RoutingResult(case, None, "", case.question, "not run", error=f"classifier: {exc}"))
            continue
        before = len(recorder.outputs)
        tool, arguments, standalone = orchestrator._plan_turn(query=case.question, conversation_history=history)
        if len(recorder.outputs) == before:
            source, confidence = "fallback: planner call failed", None
        else:
            source, confidence = _planning_source(recorder.outputs[-1], tool, orchestrator)
        results.append(
            RoutingResult(
                case=case,
                is_cinema=classification["is_cinema"],
                tool=tool,
                standalone_query=standalone,
                source=source,
                confidence=confidence,
                arguments=arguments,
            )
        )
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate DB/RAG/TMDb/YouTube routing with real LLM calls.")
    parser.add_argument("--live", action="store_true", required=True, help="Required: this run costs API credits.")
    parser.add_argument(
        "--tool",
        choices=sorted({case.expected_tool for case in ROUTING_CASES}),
        help="Run only the cases expecting this tool (2 API calls per case).",
    )
    args = parser.parse_args(argv)

    from functools import partial

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    import app as app_module
    from rag.FromQueryEmbeddingToRes.query_classifier import query_classifier

    # No automatic retries: one call per classifier/planner step.
    query_classifier.OpenAI = partial(OpenAI, max_retries=0)
    application = app_module.build_app()
    orchestrator = application["orchestrator"]
    orchestrator.client = RecordingClient(OpenAI(max_retries=0))

    results = run_routing_cases(
        select_cases(args.tool),
        orchestrator=orchestrator,
        classify=query_classifier.classify_query_domain,
        context_size=application["config"]["orchestrator"].get("classifier_context_messages", 0),
    )

    for result in results:
        mark = "✅" if result.passed else "❌"
        print(f"{mark} {result.case.question}")
        print(
            f"   expected={result.case.expected_tool} got={result.tool or '-'} source={result.source} "
            f"confidence={result.confidence} is_cinema={result.is_cinema}"
        )
        if result.case.history or result.standalone_query != result.case.question:
            print(f"   standalone: {result.standalone_query}")
        expects_arguments = (
            result.case.expected_request is not None
            or result.case.expected_video is not None
            or result.case.expected_rag is not None
        )
        if expects_arguments and result.tool == result.case.expected_tool:
            print(f"   arguments: {json.dumps(result.arguments, ensure_ascii=False)}")
            print(f"   requests: {result.requests_problem or 'ok'}")
        if result.error:
            print(f"   error: {result.error}")
    passed = sum(result.passed for result in results)
    calls = len(results) + len(orchestrator.client.outputs)
    print(f"\n{passed}/{len(results)} cases passed — API calls: {calls} (classifier + planner)")


if __name__ == "__main__":
    main()
