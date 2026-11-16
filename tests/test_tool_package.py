"""Layout of the orchestrator tools: all in `tool/`, wired only by `app.py`."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("rag", "tmdb", "youtube", "wikipedia", "omdb", "tvmaze", "wikidata", "cinema_db")
# `rag` holds the two RAG tools, one sub-package each (`film` = rag_search, `series` = series_rag_search).
ENTRY = {"rag": "film/tool.py"}
RAG_TOOLS = ("film", "series")
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
    for sub in RAG_TOOLS:  # two distinct tools, each with its own entry point, retriever and contract
        for part in ("__init__.py", "tool.py", "models.py" if sub == "film" else "config.py"):
            assert (ROOT / "tool" / "rag" / sub / part).is_file(), (sub, part)
        assert (ROOT / "tool" / "rag" / sub / "retrieval" / "__init__.py").is_file(), sub
        if name not in ("movie_db", "cinema_db"):  # the root movie_db/ and cinema_db/ are the database side (data, schema, harness)
            assert not (ROOT / name).exists(), f"{name}/ must not come back to the root"
    assert not (ROOT / "cinema_db" / "tool").exists(), "the cinema tool lives in tool/cinema_db/"


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
        "movie_db/harness/evaluation/run_routing_eval.py",
        "movie_db/harness/evaluation/run_rag_infra_check.py",  # offline check of the two RAGs on Qdrant with stored vectors (no model call)
        "movie_db/harness/evaluation/run_rag_semantic_smoke.py",  # free-text quality harness of the two RAGs (paid only with --live and an env authorisation)
        # offline analysis scripts of the Qdrant work, never imported at runtime
        "cinema_db/harness/tool_eval/run_benchmark.py",  # offline benchmark of the cinema_sql tool on the real database
        "cinema_db/harness/build/verify.py",  # offline verification of the built cinema database: opens it through tool/cinema_db's guard  # offline phase-0 baseline of the cinema DB plan (fake transports)
        # the series pipeline evaluates and indexes with the retriever the agent runs (one copy, in tool/rag/series), never a duplicate
        "pipelines/wikipedia_series/index.py",
        "pipelines/wikipedia_series/eval_known_item.py",
        "pipelines/wikipedia_series/eval/run_battery.py",
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
    for path in (ROOT / "tool").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        own = path.relative_to(ROOT / "tool").parts[0]
        for module in _imported_modules(path):
            parts = module.split(".")
            relative = path.relative_to(ROOT).as_posix()
            assert parts[0] not in forbidden, (relative, module)
            if parts[0] == "tool":
                assert parts[1] == own, (path.relative_to(ROOT).as_posix(), module)
            if own == "rag" and parts[:2] == ["tool", "rag"] and len(parts) > 2:  # the two RAG tools never import each other; only `shared` is common
                mine = path.relative_to(ROOT / "tool" / "rag").parts[0]
                assert parts[2] in {mine, "shared"} or mine == "shared", (relative, module)


def test_tool_holds_only_the_tools_the_agent_can_use_and_pipelines_live_outside() -> None:
    """One folder per tool in `tool/`; datasets, cleaning, embedding and index builds are `pipelines/`, and the two pipelines never import each other."""
    folders = {p.name for p in (ROOT / "tool").iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert folders == set(TOOLS)
    assert {p.name for p in (ROOT / "pipelines").iterdir() if p.is_dir() and p.name != "__pycache__"} == {"wikipedia_films", "wikipedia_series"}
    for mine, other in (("wikipedia_films", "wikipedia_series"), ("wikipedia_series", "wikipedia_films")):
        for path in (ROOT / "pipelines" / mine).rglob("*.py"):
            if "data" in path.relative_to(ROOT).parts:
                continue
            assert f"pipelines.{other}" not in path.read_text(), path


def test_the_two_rag_tools_share_only_the_shared_package_and_use_no_removed_code() -> None:
    """film and series import nothing from each other (relative imports stay inside the own sub-package or reach `shared`), and the old RAG is gone."""
    for sub in RAG_TOOLS:
        for path in (ROOT / "tool" / "rag" / sub).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level >= 3 and sub in path.parts:
                    # from ...X inside tool/rag/<sub>/retrieval/<m>.py is tool.rag.X
                    assert (node.module or "").split(".")[0] == "shared", (path, node.module)
    text = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "tool").rglob("*.py") if "__pycache__" not in p.parts)
    for removed in ("FromQueryEmbeddingToRes", "EmbeddingProcess", "series_index", "rerank_cohere", "COHERE_API_KEY", "rerank-v3"):
        assert removed not in text, removed
    assert not (ROOT / "tool" / "rag" / "FromQueryEmbeddingToRes").exists() and not (ROOT / "tool" / "series_index").exists()
