"""Run the evaluation cases through `MovieDbTool`.

Offline by default: the parser is replaced by a scripted client that returns each
case's expected query, so the run checks SQL, guard and result mapping on the fixture
DB for free. `--live-parser` uses the real LLM parser (costs API credits).

    python -m movie_db.harness.evaluation.run_eval [--live-parser]
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from movie_db.config import MovieDbConfig, load_movie_db_config
from movie_db.harness.fixtures.build_fixture_db import build_fixture_db
from tool.movie_db.movie_db_tool import MovieDbTool
from tool.movie_db.sql.queries import build_query
from tool.movie_db.sql.repository import effective_limit

from .cases import CASES, EVAL_OVERRIDES, EvalCase


class ScriptedParserClient:
    """OpenAI-like client whose `responses.create` returns the expected query of each case."""

    def __init__(self, cases: tuple[EvalCase, ...]) -> None:
        self._answers = {
            case.question: json.dumps(case.expected.model_dump(mode="json", exclude_none=True))
            for case in cases
        }
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        return type("Response", (), {"output_text": self._answers[kwargs["input"]]})()


@dataclass
class CaseResult:
    case: EvalCase
    operation: str | None
    titles: list[str] = field(default_factory=list)
    error: str | None = None
    # SQL statements run, as in the trace, and those the expected query would run.
    executed: list[dict[str, Any]] = field(default_factory=list)
    expected_executed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def operation_ok(self) -> bool:
        if self.operation == self.case.expected.operation.value:
            return True
        equivalent = {operation.value for operation in self.case.equivalent_operations()}
        return self.operation in equivalent and self.executed == self.expected_executed

    @property
    def titles_ok(self) -> bool:
        expected = list(self.case.expected_titles)
        return self.titles[: len(expected)] == expected

    @property
    def passed(self) -> bool:
        return self.error is None and self.operation_ok and self.titles_ok


def run_cases(
    cases: tuple[EvalCase, ...],
    *,
    config: MovieDbConfig,
    client: Any,
) -> list[CaseResult]:
    tool = MovieDbTool(config=config, client=client)
    results = []
    for case in cases:
        output = tool.run(query=case.question, params={}, conversation_history=[])
        expected_sql = build_query(
            case.expected,
            limit=effective_limit(case.expected, config.query),
            min_ratings=config.query.min_ratings,
        )
        results.append(
            CaseResult(
                case=case,
                operation=output["metadata"]["operation"],
                titles=[chunk["title"] for chunk in output["chunks"]],
                error=output["metadata"].get("error"),
                executed=[query for step in output["trace"] for query in step["data"]["queries"]],
                expected_executed=[expected_sql.model_dump(mode="json")],
            )
        )
    return results


def eval_config(db_path: Path) -> MovieDbConfig:
    from app import build_runtime_config

    runtime = build_runtime_config({"movie_db": {**EVAL_OVERRIDES["movie_db"], "db_path": str(db_path)}})
    return load_movie_db_config(runtime["movie_db"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate the movie DB tool on the fixture DB.")
    parser.add_argument("--live-parser", action="store_true", help="Use the real LLM parser (costs credits).")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fixture.sqlite3"
        config = eval_config(db_path)
        build_fixture_db(db_path, config.ingestion)
        if args.live_parser:
            from dotenv import load_dotenv
            from openai import OpenAI

            load_dotenv()
            client: Any = OpenAI()
        else:
            client = ScriptedParserClient(CASES)
        results = run_cases(CASES, config=config, client=client)

    for result in results:
        mark = "✅" if result.passed else "❌"
        equivalent = (
            f" (equivalent to {result.case.expected.operation.value}: same SQL)"
            if result.passed and result.operation != result.case.expected.operation.value
            else ""
        )
        print(f"{mark} {result.case.question}{equivalent}")
        if not result.passed:
            print(f"   operation: {result.operation} (expected {result.case.expected.operation.value})")
            print(f"   titles: {result.titles} (expected {list(result.case.expected_titles)})")
            if result.error:
                print(f"   error: {result.error}")
    passed = sum(result.passed for result in results)
    print(f"\n{passed}/{len(results)} cases passed")


if __name__ == "__main__":
    main()
