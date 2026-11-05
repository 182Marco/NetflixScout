import bz2
import io
import json

import pytest

from make_dump import build_xml, write_dump
from tool.RAGWikipediaFilm.config import load_config
from tool.RAGWikipediaFilm.extract_films import classify_page, iter_pages, run_extract


@pytest.fixture
def config(tmp_path):
    cfg = load_config(overrides={"extract.min_plot_chars": 200, "extract.min_plot_words": 30,
                                 "extract.checkpoint_every_pages": 3})
    object.__setattr__(cfg.extract, "processed_dir", str(tmp_path / "processed"))
    object.__setattr__(cfg.dump, "raw_dir", str(tmp_path / "raw"))
    return cfg


def _reasons(config):
    out = {}
    for page in iter_pages(io.BytesIO(build_xml())):
        out[page.title] = classify_page(page, config.extract)[1]
    return out


def test_classification(config):
    assert _reasons(config) == {
        "Film Uno": "ok",
        "Rinvio": "redirect",
        "Film (disambigua)": "not_a_film",  # no film signal: rejected by the prefilter, never parsed
        "Filmografia di Anna Bianchi": "list_or_filmography",
        "Film Senza Trama": "no_plot_section",
        "Una città": "not_a_film",
        "Discussione:Film Uno": "not_article",
        "Film Due": "ok",
        "Senza Infobox": "ok",
    }


def test_candidate_content(config):
    pages = {p.title: p for p in iter_pages(io.BytesIO(build_xml()))}
    candidate, _ = classify_page(pages["Film Uno"], config.extract)
    assert candidate["page_id"] == 1 and candidate["revision_id"] == "100"
    assert candidate["infobox"]["anno uscita"] == "1999" and "Frase narrativa numero 0" in candidate["plot"]
    no_box, _ = classify_page(pages["Senza Infobox"], config.extract)
    assert "no_infobox" in no_box["flags"]


def test_run_extract_streams_from_bz2_without_writing_xml(config, tmp_path):
    dump = tmp_path / "raw" / "d.xml.bz2"
    dump.parent.mkdir()
    write_dump(dump)
    summary = run_extract(config, dump_path=dump)
    assert summary["stats"]["ok"] == 3 and summary["pages_seen"] == 9
    assert [p.name for p in (tmp_path / "raw").iterdir()] == ["d.xml.bz2"]  # nothing decompressed on disk
    lines = (tmp_path / "processed" / "candidates.jsonl").read_text().splitlines()
    assert [json.loads(x)["page_id"] for x in lines] == [1, 8, 9]
    rejected = (tmp_path / "processed" / "rejected.jsonl").read_text().splitlines()
    assert json.loads(rejected[0])["reason"] == "no_plot_section"


def test_resume_gives_the_same_result(config, tmp_path):
    dump = tmp_path / "raw" / "d.xml.bz2"
    dump.parent.mkdir()
    write_dump(dump)
    run_extract(config, dump_path=dump)
    expected = (tmp_path / "processed" / "candidates.jsonl").read_bytes()
    ckpt = tmp_path / "processed" / "extract_checkpoint.json"
    state = json.loads(ckpt.read_text())
    # simulate an interruption after 6 pages: file cut, checkpoint says "not complete"
    cut = len(b"".join(expected.splitlines(keepends=True)[:1]))
    state.update(pages_seen=3, complete=False, candidates_bytes=cut, rejected_bytes=0,
                 stats={"ok": 1, "redirect": 1, "disambiguation": 1})
    ckpt.write_text(json.dumps(state))
    run_extract(config, dump_path=dump)
    assert (tmp_path / "processed" / "candidates.jsonl").read_bytes() == expected


def test_truncated_dump_needs_explicit_permission(tmp_path):
    data = bz2.compress(build_xml())[:-40]
    with pytest.raises(Exception):
        list(iter_pages(bz2.BZ2File(io.BytesIO(data))))
    pages = list(iter_pages(bz2.BZ2File(io.BytesIO(data)), allow_truncated=True))
    assert len(pages) <= 9


def test_a_page_that_crashes_the_parser_is_recorded_and_skipped(config, tmp_path, monkeypatch):
    import tool.RAGWikipediaFilm.extract_films as ef

    original = ef.classify_page

    def flaky(page, cfg):
        if page.page_id == 8:
            raise ValueError("boom")
        return original(page, cfg)

    monkeypatch.setattr(ef, "classify_page", flaky)
    dump = tmp_path / "raw" / "d.xml.bz2"
    dump.parent.mkdir()
    write_dump(dump)
    summary = run_extract(config, dump_path=dump)
    assert summary["stats"]["parse_error"] == 1 and summary["stats"]["ok"] == 2  # pipeline went on
    rejected = [json.loads(x) for x in (tmp_path / "processed" / "rejected.jsonl").read_text().splitlines()]
    assert {"page_id": 8, "reason": "parse_error", "title": "Film Due"} in rejected


def test_prefilter_never_rejects_what_the_full_check_accepts(config):
    from tool.RAGWikipediaFilm.extract_films import _may_be_a_film

    cfg = config.extract
    assert _may_be_a_film("{{Film\n|titolo=X}}", cfg) and _may_be_a_film("{{ film |titolo=X}}", cfg)
    assert _may_be_a_film("Testo.\n[[Categoria:Film del 1999]]", cfg)
    assert not _may_be_a_film("{{Divisione amministrativa|nome=Roma}} un film in un testo", cfg)
    for page in iter_pages(io.BytesIO(build_xml())):  # on the mini dump the prefilter changes nothing
        full_reason = classify_page(page, cfg)[1]
        if full_reason == "ok":
            assert _may_be_a_film(page.text, cfg)


def test_a_disambiguation_page_with_film_signals_is_still_labelled_disambiguation(config):
    from tool.RAGWikipediaFilm.extract_films import Page

    text = "{{Disambigua}}\n{{Film\n|titolo=X}}\n[[Categoria:Film del 1999]]"
    page = Page(11, "X (disambigua)", 0, False, "1", "2026-10-01T00:00:00Z", text)
    assert classify_page(page, config.extract) == (None, "disambiguation")
