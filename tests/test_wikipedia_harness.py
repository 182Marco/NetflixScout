"""The live smoke script is never run by the tests, but its requests and its isolation are checked."""
from __future__ import annotations

import ast
from pathlib import Path

from wikipedia.harness.live_smoke import _requests, main

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_smoke_requests_are_the_ones_the_tool_builds() -> None:
    requests = {label: (language, params) for label, language, params in _requests()}

    assert len(requests) == 3
    language, lookup = requests["lookup of a person"]
    assert language == "en" and lookup["generator"] == "search" and lookup["gsrsearch"] == '"Park Chan-wook"'
    assert requests["whole article"][0] == "en" and requests["whole article"][1]["titles"] == "Park Chan-wook"
    assert requests["lookup of a homonym title"][1]["gsrsearch"] == '"Parasite" film'


def test_the_script_needs_live() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_runtime_never_imports_the_wikipedia_harness() -> None:
    runtime_files = [ROOT / "app.py", *[p for p in sorted((ROOT / "wikipedia").rglob("*.py")) if "harness" not in p.parts]]
    for path in runtime_files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "harness" not in node.module, path
