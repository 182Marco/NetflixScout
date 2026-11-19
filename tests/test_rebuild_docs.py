"""docs/REBUILD.md must not rot: every module, file and environment variable it names has to exist. Offline, no commands are run."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/REBUILD.md").read_text(encoding="utf-8")
GENERATED = ("/data/", "dbVettoriale", "bin/", ".venv", "<", "$", "*")  # things the rebuild creates, placeholders and globs


def modules() -> list[str]:
    return sorted({m for m in re.findall(r"python -m ([\w.]+)", DOC) if m != "pytest"})


@pytest.mark.parametrize("module", modules())
def test_every_python_module_in_the_runbook_exists(module):
    assert importlib.util.find_spec(module) is not None, f"docs/REBUILD.md names `python -m {module}`, which does not exist"


def test_every_file_the_runbook_names_exists():
    tokens = set(re.findall(r"(?<![\w/.-])((?:scripts|docs|pipelines|cinema_db|movie_db|tests)/[\w./-]+|requirements[\w-]*\.txt|\.env\.example)", DOC))
    missing = []
    for t in sorted(tokens):
        t = t.rstrip(".,;:)")
        if any(g in f"/{t}" for g in GENERATED) or t.endswith("/"):
            continue
        if not (ROOT / t).exists():
            missing.append(t)
    assert not missing, f"docs/REBUILD.md names files that do not exist: {missing}"


def test_every_environment_variable_in_the_runbook_is_in_env_example():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    names = set(re.findall(r"(?<![/\w])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,})(?![\w]|\.\w)", DOC))  # not a file name such as AUDIT_NOYEAR_246.md
    missing = sorted(n for n in names if n not in example)
    assert not missing, f"documented in docs/REBUILD.md but absent from .env.example: {missing}"


def test_the_paid_steps_are_guarded_and_the_runbook_says_so():
    assert "FILMS_EMBED_AUTHORIZED=yes" in DOC and "SERIES_EMBED_AUTHORIZED=yes" in DOC
    from pipelines.wikipedia_films.indexing import v3
    assert v3.AUTH_ENV == "FILMS_EMBED_AUTHORIZED"


def test_the_stage_checkpoints_exist():
    for stage in range(6):
        assert f"## Stage {stage}" in DOC
    assert DOC.count("**Checkpoint:**") >= 4


def test_the_pinned_runtime_database_name_matches_the_code():
    from cinema_db.harness.candidate import EXPECTED
    assert EXPECTED["path"] in DOC
