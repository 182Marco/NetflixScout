"""FASE 21: the schema-4 candidate is named in ONE place and every check refuses any other file (no silent fallback)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cinema_db.harness import candidate as C

ROOT = Path(__file__).resolve().parents[1]


def _file(path: Path, **info) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT INTO build_info VALUES (?,?)", list(info.items()))
    conn.commit(); conn.close()
    return path


def test_the_expectation_is_complete_and_names_candidate6() -> None:
    assert C.EXPECTED["path"].endswith("cinema.v4.candidate6.sqlite3") and C.EXPECTED["schema_version"] == "4"
    assert len(C.EXPECTED["content_sha256"]) == 64 and C.EXPECTED["content_sha256"].startswith("27d2d09e")
    assert C.EXPECTED_PATH == ROOT / C.EXPECTED["path"]


def test_a_file_with_the_expected_name_schema_and_digest_is_accepted(tmp_path) -> None:
    ok = _file(tmp_path / Path(C.EXPECTED["path"]).name, schema_version="4", content_sha256=C.EXPECTED["content_sha256"])
    assert C.identify(ok)["content_sha256"] == C.EXPECTED["content_sha256"]


@pytest.mark.parametrize("info, message", [
    ({"schema_version": "3", "content_sha256": C.EXPECTED["content_sha256"]}, "schema_version"),
    ({"schema_version": "4", "content_sha256": "0" * 64}, "content_sha256"),
    ({"schema_version": "4"}, "content_sha256"),
])
def test_any_other_schema_or_digest_is_refused(tmp_path, info, message) -> None:
    with pytest.raises(C.CandidateMismatch, match=message):
        C.identify(_file(tmp_path / Path(C.EXPECTED["path"]).name, **info))


def test_the_name_is_part_of_the_identity_because_the_digest_does_not_cover_indexes(tmp_path) -> None:
    other = _file(tmp_path / "cinema.v4.candidate4.sqlite3", schema_version="4", content_sha256=C.EXPECTED["content_sha256"])
    with pytest.raises(C.CandidateMismatch, match="file name"):
        C.identify(other)
    assert C.identify(other, strict_name=False)["schema_version"] == "4"


def test_missing_and_foreign_files_are_refused(tmp_path) -> None:
    with pytest.raises(C.CandidateMismatch, match="does not exist"):
        C.identify(tmp_path / "nothing.sqlite3")
    junk = tmp_path / Path(C.EXPECTED["path"]).name
    junk.write_bytes(b"not a database at all" * 100)
    with pytest.raises(C.CandidateMismatch, match="build_info"):
        C.identify(junk)


@pytest.mark.skipif(not C.EXPECTED_PATH.is_file(), reason="needs the schema-4 candidate")
def test_the_real_candidate_is_the_expected_one() -> None:
    assert C.identify()["schema_version"] == "4"


def test_every_default_path_of_the_harness_is_the_expected_candidate() -> None:
    from movie_db.harness.evaluation import run_preference_routing_eval as pref
    from movie_db.harness.evaluation import run_rag_semantic_smoke as smoke
    assert smoke.CINEMA_DB == C.EXPECTED_PATH and pref.CINEMA_DB == C.EXPECTED["path"]
    for module in ("run_routing_eval", "run_rag_infra_check"):
        text = (ROOT / "movie_db/harness/evaluation" / f"{module}.py").read_text()
        assert "candidate3" not in text and "candidate4" not in text and "candidate.EXPECTED" in text.replace("fromlist=[\"EXPECTED\"]).EXPECTED", "candidate.EXPECTED").replace("fromlist=[\"EXPECTED_PATH\"]).EXPECTED_PATH", "candidate.EXPECTED")
    script = (ROOT / "scripts/start_integrated.sh").read_text()
    assert C.EXPECTED["path"] in script


def test_no_schema_4_check_of_the_harness_names_a_superseded_candidate() -> None:
    for path in sorted((ROOT / "cinema_db/harness").rglob("*.py")) + sorted((ROOT / "movie_db/harness").rglob("*.py")):
        text = path.read_text()
        for stale in ("v4.candidate3.sqlite3", "v4.candidate4.sqlite3"):
            assert stale not in text.replace("cinema.v4.candidate4.verify", ""), (path.name, stale)
