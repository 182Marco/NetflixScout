"""Layout of the orchestrator tools: all in `tool/`, wired only by `app.py`."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("rag", "tmdb", "youtube", "wikipedia", "movie_db")
ENTRY = {"rag": "FromQueryEmbeddingToRes/tool_interface.py", "movie_db": "movie_db_tool.py"}
# Legacy terminal loop of the RAG, kept as it was before the move (see AGENTS.md).
LEGACY_PRESENTER_IMPORT = "tool/rag/FromQueryEmbeddingToRes/chat.py"
SKIPPED = {".venv", "__pycache__", ".git", "dbVettoriale", "dataset", "tests"}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_every_tool_package_lives_in_the_tool_folder() -> None:
    assert (ROOT / "tool" / "__init__.py").is_file()
    for name in TOOLS:
        assert (ROOT / "tool" / name / "__init__.py").is_file(), name
        assert (ROOT / "tool" / name / ENTRY.get(name, "tool.py")).is_file(), name
        if name != "movie_db":  # the root movie_db/ is the database side (data, schema, harness)
            assert not (ROOT / name).exists(), f"{name}/ must not come back to the root"
    assert not (ROOT / "movie_db" / "tool").exists(), "the MovieLens tool lives in tool/movie_db/"


def test_only_app_and_the_routing_eval_import_the_tools() -> None:
    importers = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.py")
        if not SKIPPED & set(path.relative_to(ROOT).parts)
        and path.relative_to(ROOT).parts[0] != "tool"
        and "tool" in _imported_roots(path)
    }
    assert importers == {
        "app.py",
        "buildSemanticDb.py",  # shims to tool/rag/EmbeddingProcess
        "movie_metadata.py",
        "movie_db/harness/evaluation/cases.py",
        "movie_db/harness/evaluation/run_eval.py",
        "movie_db/harness/evaluation/run_routing_eval.py",
        "movie_db/harness/evaluation/run_rag_params_eval.py",
        # offline analysis scripts of the Qdrant work, never imported at runtime
        "docs/qdrant_migration/phase5/ab.py",
        "docs/qdrant_migration/catalog/calibration/calibrate.py",  # offline, paid steps gated by an env variable
    }


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def test_tool_packages_do_not_import_the_project_or_each_other() -> None:
    """A tool imports only itself (`tool.<name>...`) or relative modules: no sibling tool, no
    presenter, no channel; `turn` is the neutral core."""
    forbidden = {"app", "orchestrator", "presenters", "web_api", "web_lists", "movie_db", "tmdb", "youtube", "wikipedia", "rag"}
    # The MovieLens tool reads the database side shared with the ingestion: config and schema only.
    shared_with_the_database = {"movie_db", "movie_db.config", "movie_db.schema"}
    for path in (ROOT / "tool").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        own = path.relative_to(ROOT / "tool").parts[0]
        for module in _imported_modules(path):
            parts = module.split(".")
            relative = path.relative_to(ROOT).as_posix()
            if relative == LEGACY_PRESENTER_IMPORT and parts[0] in {"presenters", "app"}:
                continue
            if own == "movie_db" and module in shared_with_the_database:
                continue
            assert parts[0] not in forbidden, (relative, module)
            if parts[0] == "tool":
                assert parts[1] == own, (path.relative_to(ROOT).as_posix(), module)
