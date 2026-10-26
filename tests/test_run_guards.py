"""Paid or risky scripts must not start by accident: no authorization variable by default, refusal without it."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "docs/qdrant_migration/catalog/calibration/calibrate.py"
E2E = ROOT / "docs/qdrant_migration/phase7/run_e2e.py"
AUTH_VARS = ("CATALOG_CALIBRATION_AUTHORIZED", "PHASE7_AUTHORIZED")


def clean_env(monkeypatch):
    for name in AUTH_VARS:
        monkeypatch.delenv(name, raising=False)


def run(script, *args, env_extra=None):
    import os

    env = {k: v for k, v in os.environ.items() if k not in AUTH_VARS} | (env_extra or {})
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, cwd=ROOT, env=env)


def test_authorizations_are_not_set_anywhere_by_default():
    for name in ("CATALOG_CALIBRATION_AUTHORIZED", "PHASE7_AUTHORIZED"):
        for path in (ROOT / ".env.example", ROOT / "app.py", ROOT / "tests/conftest.py"):
            assert name not in path.read_text(encoding="utf-8"), (name, path.name)


def test_phase7_refuses_without_authorization_and_writes_nothing(tmp_path):
    out = tmp_path / "out"
    result = run(E2E, "--out", str(out))
    assert result.returncode == 2 and "Refused" in result.stderr and not out.exists()


@pytest.mark.parametrize("value", ["", "1", "true", "YES", "no"])
def test_phase7_accepts_only_the_exact_word(tmp_path, value):
    result = run(E2E, "--out", str(tmp_path / "o"), env_extra={"PHASE7_AUTHORIZED": value})
    assert result.returncode == 2 and not (tmp_path / "o").exists()


@pytest.mark.parametrize("value", ["", "1", "true", "YES"])
def test_calibration_paid_step_accepts_only_the_exact_word(tmp_path, value):
    queries = tmp_path / "q.json"
    queries.write_text(json.dumps([{"text": "x"}]))
    result = run(CAL, "embed-queries", "--queries", str(queries), "--out", str(tmp_path / "v.json"),
                 env_extra={"CATALOG_CALIBRATION_AUTHORIZED": value})
    assert result.returncode == 2 and not (tmp_path / "v.json").exists()


def test_free_calibration_steps_never_touch_the_paid_client(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("calibrate_guard", CAL)
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    import tool.rag.FromQueryEmbeddingToRes.embeddings as emb

    monkeypatch.setattr(emb, "embed", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid embed called")))
    reg = tmp_path / "r.json"
    reg.write_text(json.dumps({"queries": [{"id": "s", "type": "side", "top_o": ["a"], "top_e": ["a"]}]}))
    assert cal.main(["plan"]) == 0
    assert cal.main(["compare", "--registry", str(reg), "--report", str(tmp_path / "rep.json")]) == 0
