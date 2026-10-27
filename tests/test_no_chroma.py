"""Chroma is gone: no tracked source or config may import it or select it."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("import chromadb", "from chromadb", "VECTORSTORE_ENGINE", "PersistentClient")
CHECKED = {".py", ".txt", ".example", ".toml", ".cfg"}


def _tracked_and_new() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [ROOT / p for p in out if (ROOT / p).is_file()]


def test_no_source_or_config_mentions_chroma_engine():
    here = Path(__file__).resolve()
    hits = []
    for path in _tracked_and_new():
        if path == here or (path.suffix not in CHECKED and path.name != ".gitignore"):
            continue
        if "docs" in path.relative_to(ROOT).parts[:1]:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits += [f"{path.relative_to(ROOT)}: {w}" for w in FORBIDDEN if w in text]
        if path.name == "requirements.txt" and "chromadb" in text.lower():
            hits.append(f"{path.relative_to(ROOT)}: chromadb")
    assert not hits, hits
