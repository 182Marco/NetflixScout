from __future__ import annotations

import gzip
import json

from pipelines.wikipedia_series import embedding_units as eu


class Words:  # one token per whitespace-separated word: enough to test the cut without the real tokenizer
    def encode(self, text):
        return text.split(" ")

    def decode(self, tokens):
        return " ".join(tokens)


def test_compose_per_type_and_skips_unusable():
    series = {"entity_type": "series", "subtype": "miniseries", "title": "X", "year": 2019, "text_kind": "plot", "plot_text": "Trama", "lead_text": ""}
    assert eu.compose(series) == ("X (2019) — miniserie TV.\nTrama", "plot")
    assert eu.compose({**series, "text_kind": "lead", "lead_text": "Intro"}) == ("X (2019) — miniserie TV.\nIntro", "lead")
    assert eu.compose({**series, "text_kind": "none"}) is None
    movie = {**series, "entity_type": "tv_movie", "subtype": "tv_movie"}
    assert eu.compose(movie)[0].startswith("X (2019) — film TV.")
    logical = {"entity_type": "season", "logical": True, "text_kind": "series_section", "lead_text": "t", "title": "S", "series_title": "X"}
    assert eu.compose(logical) is None   # logical seasons have no vector of their own
    ep = {"entity_type": "episode", "text_kind": "plot", "series_title": "X", "season_number": 2, "episode_number": 3, "title": "Pilota", "plot_text": "Trama ep"}
    assert eu.compose(ep) == ("X – stagione 2 – episodio 3 – Pilota.\nTrama ep", "plot")


def test_build_counts_truncates_and_stays_pending(tmp_path, monkeypatch):
    s5 = tmp_path / "s5"
    s5.mkdir()
    rec = {"record_id": "wp-1", "entity_type": "series", "subtype": "tv_series", "title": "X", "year": None, "text_kind": "plot",
           "plot_text": " ".join(["w"] * 50), "lead_text": ""}
    (s5 / "series.jsonl").write_text(json.dumps(rec) + "\n")
    for name in ("seasons", "episodes", "tv_movies"):
        (s5 / f"{name}.jsonl").write_text("")
    monkeypatch.setattr(eu, "TARGET_TOKENS", 10)
    manifest = eu.build(s5, tmp_path / "s6", encoder=Words())
    assert manifest["status"] == "pending" and manifest["units"] == 1 and manifest["by_type"]["series"]["truncated"] == 1
    row = json.loads(gzip.open(tmp_path / "s6" / "units.jsonl.gz", "rt").readline())
    assert row["truncated"] is True and row["tokens"] == 10
