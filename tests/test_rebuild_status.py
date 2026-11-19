"""scripts/rebuild_status.py: the read-only progress report of docs/REBUILD.md. Offline; the Qdrant server is faked."""
from __future__ import annotations

import gzip
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rebuild_status", ROOT / "scripts/rebuild_status.py")
rs = importlib.util.module_from_spec(spec)
sys.modules["rebuild_status"] = rs   # a dataclass needs its module registered while it is being defined
spec.loader.exec_module(rs)


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    monkeypatch.setattr(rs, "qdrant_up", lambda url: False)
    monkeypatch.setattr(rs, "qdrant_points", lambda url, name: None)


def by_key(stages):
    return {s.key: s for s in stages}


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_clean_clone_has_nothing_done_and_says_what_to_do_first(tmp_path, capsys):
    stages = by_key(rs.build_report(tmp_path))
    assert [stages[k].status for k in "1234"] == ["todo"] * 4
    assert stages["5"].status != "done"
    assert "bin/qdrant" in stages["0"].next or stages["0"].next        # the first missing prerequisite has a command
    assert rs.main(["--root", str(tmp_path), "--strict"]) == 1
    assert "Next (stage" in capsys.readouterr().out


def test_json_output_is_valid_and_complete(tmp_path, capsys):
    assert rs.main(["--root", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["key"] for s in data] == ["0", "1", "2", "3", "4", "5"]
    assert all({"status", "next", "checks"} <= set(s) for s in data)


def test_it_never_reads_the_env_file(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-secret-value\n")
    check = next(c for c in rs.stage0(tmp_path, "http://x").checks if c.name == ".env exists")
    assert check.ok and "secret" not in check.detail and "sk-" not in check.detail


def test_movielens_stage_checks_the_exact_counts(tmp_path, monkeypatch):
    monkeypatch.setitem(rs.MOVIELENS, "movies", 2)
    monkeypatch.setitem(rs.MOVIELENS, "ratings", 7)
    monkeypatch.setitem(rs.MOVIELENS, "tags", 1)
    for f in ("movies.csv", "ratings.csv", "tags.csv", "links.csv"):
        touch(tmp_path / "movie_db/data/raw/ml-32m" / f)
    db = tmp_path / "movie_db/data/movielens32m.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE movies(id INT); CREATE TABLE tags(id INT); CREATE TABLE movie_stats(n_ratings INT);"
                       "INSERT INTO movies VALUES (1),(2); INSERT INTO tags VALUES (1); INSERT INTO movie_stats VALUES (3),(4);")
    conn.commit(); conn.close()
    assert rs.stage3(tmp_path).status == "done"

    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO movies VALUES (3)")
    conn.commit(); conn.close()
    assert rs.stage3(tmp_path).status == "partial"          # one number is wrong: not done


def test_collection_checks_compare_points_with_the_catalogue(tmp_path, monkeypatch):
    d = tmp_path / "pipelines/wikipedia_films/data"
    touch(d / "clean_v3/films.v3.jsonl", "{}\n{}\n{}\n")
    touch(d / "embeddings/itwiki-20261101-large1536-v3/new_vectors.npz")
    monkeypatch.setattr(rs, "qdrant_points", lambda url, name: 3)
    s = rs.stage1(tmp_path, "http://x", "20261101")
    assert next(c for c in s.checks if c.name.startswith("collection")).ok
    monkeypatch.setattr(rs, "qdrant_points", lambda url, name: 2)
    s = rs.stage1(tmp_path, "http://x", "20261101")
    bad = next(c for c in s.checks if c.name.startswith("collection"))
    assert not bad.ok and "catalogue: 3" in bad.detail


def test_series_units_are_counted_in_the_gzip_file(tmp_path):
    units = tmp_path / "u.jsonl.gz"
    with gzip.open(units, "wt") as f:
        f.write("{}\n{}\n")
    assert rs.count_lines(units) == 2


def test_the_pinned_digest_is_read_from_candidate_py_without_importing_it():
    assert len(rs.expected_digest(ROOT) or "") == 64


def test_the_dump_date_follows_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ITWIKI_DUMP_DATE", "20270101")
    touch(tmp_path / "pipelines/wikipedia_films/data/raw/itwiki-20270101-pages-articles.xml.bz2")
    first = rs.build_report(tmp_path)[1].checks[0]
    assert first.ok and "20270101" in first.detail
