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


bk = load("scripts/backup_qdrant_storage.py", "backup_storage")


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

