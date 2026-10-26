"""scripts/start_qdrant.sh: required binary path, real storage default, runs outside the repository (fake binary)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/start_qdrant.sh"


def run(env_extra, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("QDRANT_", "QDRANT__"))} | env_extra
    return subprocess.run(["/bin/sh", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30)


def fake_binary(tmp_path):
    binary = tmp_path / "qdrant"
    binary.write_text('#!/bin/sh\necho "cwd=$(pwd)"; echo "host=$QDRANT__SERVICE__HOST"; echo "storage=$QDRANT__STORAGE__STORAGE_PATH"\n')
    binary.chmod(0o755)
    return binary


def test_it_refuses_without_the_binary_path_or_with_a_wrong_one(tmp_path):
    assert run({}, tmp_path).returncode != 0
    result = run({"QDRANT_BIN": str(tmp_path / "missing")}, tmp_path)
    assert result.returncode == 1 and "not an executable" in result.stderr


def test_it_listens_only_on_localhost_on_the_real_storage_and_outside_the_repository(tmp_path):
    result = run({"QDRANT_BIN": str(fake_binary(tmp_path))}, tmp_path)
    assert result.returncode == 0, result.stderr
    out = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert out["host"] == "127.0.0.1"
    assert out["storage"] == str(ROOT / "dbVettoriale/qdrant_openai/storage")
    assert (ROOT / "dbVettoriale/qdrant_openai/storage").is_dir()
    assert not Path(out["cwd"]).resolve().is_relative_to(ROOT)


def test_a_missing_storage_is_reported_not_created(tmp_path):
    result = run({"QDRANT_BIN": str(fake_binary(tmp_path)), "QDRANT_STORAGE": str(tmp_path / "nope")}, tmp_path)
    assert result.returncode == 1 and "storage folder not found" in result.stderr and not (tmp_path / "nope").exists()
