"""Where the HTTP code may live: only in `web_api/`, which calls the core through a few entry points."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIPPED = {".venv", "__pycache__", "dbVettoriale", "dataset", "tests", ".git", "node_modules"}
HTTP_PACKAGES = {"fastapi", "starlette", "uvicorn", "sse_starlette"}
# Packages web_api may import from the project: the entry points of the bot, nothing deeper.
ALLOWED_PROJECT_IMPORTS = {"app", "turn", "presenters", "web_lists", "web_api"}
PROJECT_PACKAGES = {"app", "orchestrator", "turn", "presenters", "web_lists", "tool", "movie_db", "answer_stream"}


def _modules(path: Path) -> set[str]:
    """Top-level packages imported by a file (relative imports are internal and skipped)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _project_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if not SKIPPED & set(p.relative_to(ROOT).parts)]


def _inside_web_api(path: Path) -> bool:
    return path.relative_to(ROOT).parts[0] == "web_api"


def _runtime_web_api_files() -> list[Path]:
    """The server code; `web_api/harness/` holds manual scripts (they print and call the LLM)."""
    return [p for p in _project_files() if _inside_web_api(p) and "harness" not in p.relative_to(ROOT).parts]


def test_http_libraries_are_imported_only_inside_web_api() -> None:
    offenders = [str(p.relative_to(ROOT)) for p in _project_files() if not _inside_web_api(p) and _modules(p) & HTTP_PACKAGES]
    assert offenders == []


def test_nothing_outside_web_api_imports_it() -> None:
    offenders = [str(p.relative_to(ROOT)) for p in _project_files() if not _inside_web_api(p) and "web_api" in _modules(p)]
    assert offenders == []


def test_web_api_uses_only_the_entry_points_of_the_bot() -> None:
    files = _runtime_web_api_files()
    assert files
    offenders = {
        str(p.relative_to(ROOT)): sorted((_modules(p) & PROJECT_PACKAGES) - ALLOWED_PROJECT_IMPORTS) for p in files
    }
    assert {path: bad for path, bad in offenders.items() if bad} == {}


def test_the_terminal_and_the_core_never_import_the_web_only_packages() -> None:
    core = [ROOT / "app.py", ROOT / "orchestrator.py", ROOT / "turn.py", ROOT / "answer_stream.py"]
    core += [p for p in (ROOT / "presenters").rglob("*.py")]
    offenders = [str(p.relative_to(ROOT)) for p in core if _modules(p) & {"web_lists", "web_api"}]
    assert offenders == []


def test_no_print_in_web_api() -> None:
    for path in _runtime_web_api_files():
        calls = [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Call)]
        assert not [c for c in calls if getattr(c.func, "id", None) == "print"], path
