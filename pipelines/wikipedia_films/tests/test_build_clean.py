"""Phase 6: the clean-dataset builder on a tiny synthetic dataset (no real data, no network)."""
from __future__ import annotations

import json

import pytest

from pipelines.wikipedia_films.audit import build_clean as B


def film(fid, page, title, synopsis="Una trama lunga abbastanza."):
    return {"film_id": fid, "wikipedia_page_id": page, "title": title, "synopsis": synopsis, "year": 1990}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    src = tmp_path / "films.jsonl"
    rows = [film("Q1", 1, "Film uno"), film("Q2", 2, "Serie due"), film("Q3", 3, "Film tre", "Trama vera. Produzione varia."),
            film("Q3821447", 4, "Nero-Fumo", "Produzione e musiche. Il corto si apre con la sagoma di una donna. Trama. Nel gennaio del 1943, la stampa cinematografica lodò. Altro.")]
    src.write_text("".join(B._dumps(r) + "\n" for r in rows))
    ex = tmp_path / "exclusions.json"
    ex.write_text(json.dumps({"records": [{"film_id": "Q2", "verdict": "series", "subtype": "miniseries", "reasons": ["r"]}]}))
    fix = tmp_path / "fix.jsonl"
    fix.write_text(json.dumps({"page_id": "3", "synopsis": "Trama vera.''<ref>nota</ref>"}) + "\n")
    cls = tmp_path / "cls.jsonl"
    cls.write_text("".join(json.dumps({"film_id": f, "verdict": v, "subtype": "x", "reasons": []}) + "\n"
                           for f, v in (("Q1", "doubtful"), ("Q3", "film"), ("Q2", "series"), ("Q3821447", "film"))))
    for name, value in dict(SOURCE=src, EXCLUSIONS=ex, SECTION_FIX=fix, CLASSIFICATION=cls, OVERRIDES=tmp_path / "ov.json",
                            OUT=tmp_path / "clean").items():
        monkeypatch.setattr(B, name, value)
    return tmp_path


def test_build_applies_exclusions_fixes_and_flags(env):
    m = B.build()
    assert (m["records_clean"], m["records_excluded"], m["plots_corrected"], m["unverified"]) == (3, 1, 2, 1)
    rows = {json.loads(l)["film_id"]: json.loads(l) for l in (env / "clean/films.clean.jsonl").open()}
    assert rows["Q3"]["synopsis"] == "Trama vera." and rows["Q3"]["synopsis_original_sha256"]
    assert rows["Q3821447"]["synopsis"] == "Il corto si apre con la sagoma di una donna. Trama."
    assert rows["Q1"]["catalog_status"] == "unverified" and rows["Q3"]["catalog_status"] == "verified"
    assert "Q2" not in rows


def test_build_is_deterministic_and_verifiable(env):
    B.build()
    first = (env / "clean/films.clean.jsonl").read_bytes()
    B.build()
    assert (env / "clean/films.clean.jsonl").read_bytes() == first
    assert B.verify() == []


def test_verify_detects_a_tampered_file(env):
    B.build()
    path = env / "clean/films.clean.jsonl"
    path.write_text(path.read_text().replace("Film uno", "Film UNO"))
    assert B.verify()


def test_reverse_check_finds_a_lost_or_changed_record(env):
    B.build()
    lines = (env / "clean/films.clean.jsonl").read_text().splitlines(keepends=True)
    (env / "clean/films.clean.jsonl").write_text("".join(lines[1:]))
    assert any("missing" in p for p in B.reverse_check(env / "clean/films.clean.jsonl", env / "clean/excluded.jsonl"))


def test_mark_verified_removes_the_unverified_flag(env):
    (env / "ov.json").write_text(json.dumps({"mark_verified": ["Q1"]}))
    B.build()
    rows = {json.loads(l)["film_id"]: json.loads(l) for l in (env / "clean/films.clean.jsonl").open()}
    assert rows["Q1"]["catalog_status"] == "verified"
    assert json.loads((env / "clean/unverified.json").read_text())["count"] == 0


def test_reports_list_unverified_corrections_and_exclusions(env):
    B.build()
    assert json.loads((env / "clean/corrections.json").read_text())["count"] == 2
    assert json.loads((env / "clean/excluded_list.json").read_text())["records"][0]["film_id"] == "Q2"
    assert json.loads((env / "clean/unverified.json").read_text())["records"][0]["film_id"] == "Q1"
    assert "report_sha256" in json.loads((env / "clean/clean_manifest.json").read_text())


def test_overrides_reinstate_and_exclude(env):
    (env / "ov.json").write_text(json.dumps({"reinstate": ["Q2"], "extra_exclude": [{"film_id": "Q1", "reason": "approved"}]}))
    m = B.build()
    ids = {json.loads(l)["film_id"] for l in (env / "clean/films.clean.jsonl").open()}
    assert ids == {"Q2", "Q3", "Q3821447"} and m["records_excluded"] == 1


def test_manual_plot_fails_loudly_when_markers_are_missing():
    with pytest.raises(ValueError):
        B.manual_plot({"film_id": "Q3821447", "synopsis": "nulla"})


def test_tidy_removes_references_and_stray_italics():
    assert B.tidy("A.<ref name=\"x\">nota</ref> ''B''<ref>aperta senza fine\nC") == "A. B\nC"
    assert B.tidy("La trama finisce.\n\nAlla fine si sente una barzelletta:") == "La trama finisce."
