"""Storage copy procedure (real files in tmp) and the phase 7 runner with a fake app (no network, no cost)."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bk = load("docs/qdrant_migration/catalog/backup_storage.py", "backup_storage")
e2e = load("docs/qdrant_migration/phase7/run_e2e.py", "run_e2e")


def make_storage(root: Path) -> Path:
    s = root / "storage"
    (s / "collection/netflix_scout/0").mkdir(parents=True)
    (s / "collection/netflix_scout/0/segment.bin").write_bytes(b"\x00\x01" * 5000)
    (s / "raft_state.json").write_text('{"x": 1}')
    return s


def test_backup_copies_verifies_and_never_overwrites(tmp_path, capsys):
    src = make_storage(tmp_path)
    before = bk.manifest_of(src)
    out = bk.backup(src, tmp_path / "copy")
    assert out["files"] == 2 and bk.manifest_of(src) == before  # source untouched
    assert bk.verify(src, tmp_path / "copy")["identical"]
    with pytest.raises(SystemExit, match="already exists"):
        bk.backup(src, tmp_path / "copy")
    (tmp_path / "copy/raft_state.json").write_text("damaged")
    assert not bk.verify(src, tmp_path / "copy")["identical"]


def test_backup_refuses_nested_or_missing_paths_and_a_live_server(tmp_path, monkeypatch):
    src = make_storage(tmp_path)
    with pytest.raises(SystemExit, match="separate"):
        bk.backup(src, src / "inside")
    with pytest.raises(SystemExit, match="not a folder"):
        bk.backup(tmp_path / "nope", tmp_path / "d")
    monkeypatch.setattr(bk, "server_is_up", lambda url: True)
    with pytest.raises(SystemExit, match="stop it"):
        bk.backup(src, tmp_path / "d2", "http://127.0.0.1:6333")
    assert not (tmp_path / "d2").exists()


def test_phase7_runner_with_a_fake_app_writes_one_file_per_question_and_chains_the_followup(tmp_path, monkeypatch):
    calls = []

    class Turn:
        def __init__(self, text, history):
            self.answer, self.tools, self.steps, self.history = "ok", ["rag_search"], [], history + [{"role": "user", "content": text}]

    def handle(app, text, history, client):
        calls.append((text, len(history)))
        return Turn(text, history)

    fake_app = types.SimpleNamespace(
        build_ready_app=lambda: {"config": {"rag": {"vectorstore": {"engine": "qdrant"}}, "catalog": {"enabled": False}}},
        handle_query=handle)
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda: object()))
    monkeypatch.setattr(e2e, "PAUSE_SECONDS", 0)
    monkeypatch.setenv("PHASE7_AUTHORIZED", "yes")
    questions = json.loads((ROOT / "docs/qdrant_migration/phase7/questions.json").read_text())
    assert e2e.main(["--out", str(tmp_path / "o")]) == 0
    assert len(list((tmp_path / "o").glob("[a-z][0-9][0-9].json"))) == len(questions) == 20
    follow = next(c for c in calls if c[0].startswith("Ne puoi"))
    assert follow[1] > 0  # received the history of the question it follows


def test_phase7_runner_refuses_chroma_and_an_active_catalog(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda: object()))
    monkeypatch.setenv("PHASE7_AUTHORIZED", "yes")
    for engine, catalog in (("chroma", False), ("qdrant", True)):
        fake = types.SimpleNamespace(build_ready_app=lambda e=engine, c=catalog: {
            "config": {"rag": {"vectorstore": {"engine": e}}, "catalog": {"enabled": c}}},
            handle_query=lambda *a: pytest.fail("must not run"))
        monkeypatch.setitem(sys.modules, "app", fake)
        assert e2e.main(["--out", str(tmp_path / engine)]) == 2


def test_phase7_questions_are_twenty_unique_and_the_followup_points_at_a_real_one():
    qs = json.loads((ROOT / "docs/qdrant_migration/phase7/questions.json").read_text())
    ids = [q["id"] for q in qs]
    assert len(qs) == 20 and len(set(ids)) == 20
    assert all(q["after"] in ids for q in qs if "after" in q)


def test_a_source_that_changes_during_the_copy_is_not_declared_valid(tmp_path, monkeypatch):
    src = make_storage(tmp_path)
    real = bk.shutil.copytree

    def copy_then_the_server_writes(a, b, *args, **kw):
        out = real(a, b, *args, **kw)
        (Path(a) / "raft_state.json").write_text('{"x": 2}')  # a live server keeps writing
        return out

    monkeypatch.setattr(bk.shutil, "copytree", copy_then_the_server_writes)
    with pytest.raises(SystemExit, match="changed during the copy"):
        bk.backup(src, tmp_path / "copy")
    assert not (tmp_path / "copy" / bk.MANIFEST).exists()  # no manifest: nothing vouches for this folder


def test_a_copy_that_differs_from_the_source_gets_no_manifest(tmp_path, monkeypatch):
    src = make_storage(tmp_path)
    real = bk.shutil.copytree

    def corrupting(a, b, *args, **kw):
        out = real(a, b, *args, **kw)
        (Path(b) / "raft_state.json").write_text("damaged")
        return out

    monkeypatch.setattr(bk.shutil, "copytree", corrupting)
    with pytest.raises(SystemExit, match="NOT a valid copy"):
        bk.backup(src, tmp_path / "copy")
    assert not (tmp_path / "copy" / bk.MANIFEST).exists()


def test_verify_detects_a_file_changed_after_the_backup_even_if_the_source_changed_too(tmp_path):
    src = make_storage(tmp_path)
    bk.backup(src, tmp_path / "copy")
    (src / "raft_state.json").write_text("new")
    (tmp_path / "copy" / "raft_state.json").write_text("new")  # both drift together: the manifest still tells
    result = bk.verify(src, tmp_path / "copy")
    assert not result["identical"] and result["changed_since_backup"] == ["raft_state.json"]


def test_a_symlink_in_the_copy_is_refused(tmp_path, monkeypatch):
    src = make_storage(tmp_path)
    real = bk.shutil.copytree

    def linking(a, b, *args, **kw):
        out = real(a, b, *args, **kw)
        (Path(b) / "link").symlink_to(Path(a) / "raft_state.json")
        return out

    monkeypatch.setattr(bk.shutil, "copytree", linking)
    with pytest.raises(SystemExit):
        bk.backup(src, tmp_path / "copy")


def step(kind, **data):
    return {"kind": kind, "data": data}


def test_phase7_auto_classes_never_count_errors_or_fallbacks_as_success():
    q = {"id": "a", "kind": "rag"}
    ok = {"answer": "x", "tools": ["rag_search"], "steps": [step("tool_outcome", tool="rag_search", status="ok")]}
    assert e2e.classify(ok, q) == ("completed", [])
    assert e2e.classify({"error": "Boom: x"}, q)[0] == "error"
    assert e2e.classify({"answer": "  ", "tools": ["t"], "steps": []}, q)[0] == "missed"
    assert e2e.classify({"answer": "x", "tools": [], "steps": []}, q)[0] == "missed"
    fb = {"answer": "x", "tools": ["t"], "steps": [step("planning", fallbacks=["answer_failed"])]}
    assert e2e.classify(fb, q) == ("partial", ["fallback:answer_failed"])
    empty = {"answer": "x", "tools": ["t"], "steps": [step("tool_outcome", tool="t", status="empty", reason=None)]}
    assert e2e.classify(empty, q)[0] == "partial"
    off = {"id": "x", "kind": "off_topic"}
    assert e2e.classify({"answer": "no", "tools": [], "steps": []}, off)[0] == "completed"
    assert e2e.classify({"answer": "no", "tools": ["t"], "steps": []}, off)[0] == "partial"


def test_phase7_summary_counts_errors_and_returns_failure(tmp_path, monkeypatch):
    class Turn:
        answer, tools, steps, history = "ok", ["rag_search"], [], []

    def handle(app, text, history, client):
        if text == "Qual è il genere con il voto medio più alto?":
            raise RuntimeError("db down")
        return Turn()

    fake = types.SimpleNamespace(
        build_ready_app=lambda: {"config": {"rag": {"vectorstore": {"engine": "qdrant"}}, "catalog": {"enabled": False}}},
        handle_query=handle)
    monkeypatch.setitem(sys.modules, "app", fake)
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda: object()))
    monkeypatch.setattr(e2e, "PAUSE_SECONDS", 0)
    monkeypatch.setenv("PHASE7_AUTHORIZED", "yes")
    assert e2e.main(["--out", str(tmp_path / "o")]) == 1
    summary = json.loads((tmp_path / "o/summary.json").read_text())
    assert summary["counts"]["error"] == 1 and sum(summary["counts"].values()) == 20
    assert summary["counts"]["completed"] + summary["counts"]["partial"] + summary["counts"]["missed"] == 19
