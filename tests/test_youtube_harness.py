"""The live smoke script is never run by the tests, but its queries and its isolation are checked."""
from __future__ import annotations

import ast
from pathlib import Path

from tool.youtube.harness.live_smoke import _variants

ROOT = Path(__file__).resolve().parent.parent


def test_the_smoke_variants_include_the_query_the_tool_builds() -> None:
    queries = dict(_variants())

    assert queries["Critters 3, query built by the tool"].startswith('"Critters 3" "Leonardo DiCaprio"|"DiCaprio" interview|')
    assert '"Leonardo DiCaprio"' in queries["Critters 3, query built by the tool"]
    assert len(queries) == 7


def test_runtime_never_imports_the_youtube_harness() -> None:
    runtime_files = [ROOT / "app.py", *[p for p in sorted((ROOT / "tool" / "youtube").rglob("*.py")) if "harness" not in p.parts]]
    for path in runtime_files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "harness" not in node.module, path
