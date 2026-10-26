"""Offline checks of the Chroma restore script: it must never write over existing data."""
from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "qdrant_migration" / "restore_chroma.py"


def _load():
    spec = importlib.util.spec_from_file_location("restore_chroma", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_destination_inside_dbvettoriale_is_refused():
    module = _load()
    for name in ("dbVettoriale", "dbVettoriale/openai", "dbVettoriale/new_copy"):
        with pytest.raises(SystemExit, match="refused"):
            module.check_destination(ROOT / name)


def test_existing_destination_is_refused(tmp_path):
    module = _load()
    with pytest.raises(SystemExit, match="already exists"):
        module.check_destination(tmp_path)


def test_new_destination_is_accepted(tmp_path):
    _load().check_destination(tmp_path / "fresh")


def test_symlink_into_dbvettoriale_is_refused(tmp_path):
    module = _load()
    link = tmp_path / "link"
    link.symlink_to(ROOT / "dbVettoriale")
    with pytest.raises(SystemExit, match="refused"):
        module.check_destination(link / "x")


def test_restore_copies_and_verifies_a_backup(tmp_path, monkeypatch):
    module = _load()
    backup = tmp_path / "backup"
    (backup / "openai" / "sub").mkdir(parents=True)
    (backup / "openai" / "a.bin").write_bytes(b"alpha")
    (backup / "openai" / "sub" / "b.bin").write_bytes(b"beta")
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(backup / 'openai').as_posix()}"
        for p in sorted((backup / "openai").rglob("*")) if p.is_file()
    ]
    for name in ("openai.copy.sha256", "openai.src.sha256"):
        (backup / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    dest = tmp_path / "restored"
    monkeypatch.setattr("sys.argv", ["restore", "--backup", str(backup), "--dest", str(dest)])
    assert module.main() == 0
    assert (dest / "sub" / "b.bin").read_bytes() == b"beta"


def test_tampered_backup_is_rejected(tmp_path, monkeypatch):
    module = _load()
    backup = tmp_path / "backup"
    (backup / "openai").mkdir(parents=True)
    (backup / "openai" / "a.bin").write_bytes(b"alpha")
    line = f"{hashlib.sha256(b'other').hexdigest()}  ./a.bin\n"
    for name in ("openai.copy.sha256", "openai.src.sha256"):
        (backup / name).write_text(line, encoding="utf-8")
    dest = tmp_path / "restored"
    monkeypatch.setattr("sys.argv", ["restore", "--backup", str(backup), "--dest", str(dest)])
    with pytest.raises(SystemExit, match="manifest"):
        module.main()
    assert not dest.exists()
