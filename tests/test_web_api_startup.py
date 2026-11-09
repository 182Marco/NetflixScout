"""`uvicorn web_api.main:app` with Qdrant down or up (real subprocess import, nothing is started or paid)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def import_main(env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VECTORSTORE_", "QDRANT_"))} | env_extra
    return subprocess.run([sys.executable, "-c", "import web_api.main"], capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)


def test_server_down_stops_the_start_with_one_clear_line():
    result = import_main({"VECTORSTORE_QDRANT_URL": "http://127.0.0.1:1"})
    assert result.returncode != 0 and "Traceback" not in result.stderr
    assert result.stderr.strip().startswith("Error: Cannot reach Qdrant at http://127.0.0.1:1")
    assert len(result.stderr.strip().splitlines()) == 1


def _local_qdrant_has_both_collections() -> bool:
    try:
        from qdrant_client import QdrantClient
        return {"wikipedia_films_it_v3"} <= {c.name for c in QdrantClient(url="http://127.0.0.1:6333", timeout=3).get_collections().collections}
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _local_qdrant_has_both_collections(), reason="needs the local Qdrant with the film collection (read only)")
def test_qdrant_up_the_app_module_imports():
    result = import_main({"MOVIE_DB_UNUSED": "1"})
    assert result.returncode == 0, result.stderr[-500:]
