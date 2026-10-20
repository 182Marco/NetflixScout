from __future__ import annotations

import ast
import json
from pathlib import Path

import app as app_module
from movie_db.tool.movie_db_tool import MOVIE_DB_TOOL_NAME, MovieDbTool
from orchestrator import LLMOrchestrator

ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    """Planning call → `plan`; parser call → `parsed`; final answer otherwise."""

    def __init__(self, plan: dict, parsed: dict) -> None:
        self.outputs = [json.dumps(plan), json.dumps(parsed), "Risposta finale."]
        self.responses = self

    def create(self, **kwargs):
        return type("Response", (), {"output_text": self.outputs.pop(0)})()


def test_build_app_registers_the_tool_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    enabled = app_module.build_app()["orchestrator"]
    disabled = app_module.build_app({"movie_db": {"enabled": False}})["orchestrator"]

    assert set(enabled.tools) == {"rag_search", MOVIE_DB_TOOL_NAME}
    assert isinstance(enabled.tools[MOVIE_DB_TOOL_NAME], MovieDbTool)
    assert set(disabled.tools) == {"rag_search"}
    assert disabled._allowed_tool_names() == ["rag_search"]


def test_config_routes_db_questions_and_keeps_rag_fallback() -> None:
    orchestrator = app_module.CONFIG["orchestrator"]

    assert MOVIE_DB_TOOL_NAME in orchestrator["allowed_tools"]
    assert MOVIE_DB_TOOL_NAME in orchestrator["instructions"]
    assert orchestrator["fallback_tool"] == "rag_search"


def test_db_query_step_reaches_the_turn_result(monkeypatch, movie_db_config) -> None:
    monkeypatch.setattr(
        app_module,
        "classify_query_domain",
        lambda q, history=None: {"is_cinema": True, "is_italian": True},
    )
    client = FakeClient(
        plan={"standalone_query": "film più votati", "tool_name": MOVIE_DB_TOOL_NAME, "confidence": 0.9},
        parsed={"operation": "most_rated", "limit": 2},
    )
    tool = MovieDbTool(config=movie_db_config, client=client)
    orchestrator = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[tool], client=client)
    app = {"config": app_module.build_runtime_config(), "orchestrator": orchestrator}

    turn = app_module.handle_query(app, "film più votati", history=[])

    assert turn.tool == MOVIE_DB_TOOL_NAME
    assert [s.kind for s in turn.steps] == ["classification", "query_rewrite", "tool_selection", "db_query"]
    assert turn.steps[-1].data["queries"][0]["sql"].startswith("SELECT")
    assert turn.answer == "Risposta finale."


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_runtime_never_imports_the_harness() -> None:
    runtime_files = [ROOT / "app.py", *sorted((ROOT / "movie_db" / "tool").rglob("*.py"))]
    runtime_files += [ROOT / "movie_db" / "config.py", ROOT / "movie_db" / "schema.py"]

    for path in runtime_files:
        offending = {m for m in _imported_modules(path) if m.startswith("movie_db.harness")}
        assert not offending, f"{path.relative_to(ROOT)} imports {offending}"


def test_presenters_do_not_import_the_movie_db_package() -> None:
    for path in sorted((ROOT / "presenters").rglob("*.py")):
        assert not {m for m in _imported_modules(path) if m.startswith("movie_db")}, path


def test_only_ingestion_opens_writable_connections() -> None:
    for path in sorted((ROOT / "movie_db").rglob("*.py")):
        if "ingestion" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "executescript" not in source, path
        if "sqlite3.connect(" in source:
            assert "mode=ro" in source, path
