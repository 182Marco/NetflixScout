"""The generated documentation matches the real SQLite schema exactly, and fails loudly when it cannot."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from cinema_schema_support import build_real

from cinema_db import schema_notes as N
from cinema_db.harness.schema import generate as G
from cinema_db.harness.schema import render
from cinema_db.harness.schema.introspect import check_notes, introspect
from cinema_db.schema import create_database
from tool.cinema_db import approved_views

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def info(tmp_path_factory):
    path = create_database(tmp_path_factory.mktemp("doc") / "c.sqlite3")
    c = sqlite3.connect(path)
    try:
        return introspect(c)
    finally:
        c.close()


def test_every_table_view_and_column_has_a_description_and_nothing_extra(info):
    assert check_notes(info) == []


def test_a_missing_or_stale_description_is_reported(info, monkeypatch):
    monkeypatch.delitem(N.COLUMNS, "work.runtime_min")
    assert any("work.runtime_min" in p for p in check_notes(introspect_again(info)))
    monkeypatch.setitem(N.COLUMNS, "work.no_such_column", "x")
    assert any("does not exist" in p for p in check_notes(introspect_again(info)))
    monkeypatch.delitem(N.TABLES, "credit")
    assert any("table credit" in p for p in check_notes(introspect_again(info)))


def introspect_again(info):
    # descriptions are read at introspection time: rebuild a temp database and introspect it again
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        c = sqlite3.connect(create_database(Path(d) / "x.sqlite3"))
        try:
            return introspect(c)
        finally:
            c.close()


def test_the_committed_files_are_exactly_what_the_generator_produces():
    outputs = G.generate(None)
    for path, text in outputs.items():
        assert Path(path).read_text(encoding="utf-8") == text, f"{path} is stale: run python -m cinema_db.harness.schema.generate"
    assert G.main(["--check"]) == 0


def test_the_html_embeds_exactly_the_real_structure(info):
    text = (ROOT / "docs/cinema_db/schema.html").read_text(encoding="utf-8")
    embedded = json.loads(re.search(r'<script type="application/json" id="schema-data">(.*?)</script>', text, re.S).group(1).replace("<\\/", "</"))
    assert embedded["structure"] == info["structure"]
    assert embedded["structure_digest"] == info["structure_digest"]
    assert f'content="{info["structure_digest"][:16]}"' in text


def test_the_html_is_self_contained(info):
    text = render.html(info)
    assert not re.findall(r'(?:src|href)=["\']https?://', text) and "cdn" not in text.lower() and "@import" not in text
    assert "<script src" not in text and "<link " not in text


def test_the_html_script_is_valid_javascript(info):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    text = render.html(info)
    script = re.findall(r"<script>(.*?)</script>", text, re.S)[0]
    proc = subprocess.run([node, "--check", "-"], input=script, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def parse_mermaid(text):
    tables, rels, cur = {}, [], None
    for line in text.splitlines():
        if line.startswith("%%") or line.strip() == "erDiagram":
            continue
        m = re.match(r"^    (\w+) \{$", line)
        if m:
            cur = m.group(1)
            tables[cur] = []
            continue
        if line.strip() == "}":
            cur = None
            continue
        m = re.match(r'^        (\w+) (\w+)((?: (?:PK|FK|UK)(?:, (?:PK|FK|UK))*)?)(?: "(.*)")?$', line)
        if m and cur:
            tables[cur].append((m.group(2), m.group(1), m.group(3).strip()))
            continue
        m = re.match(r'^    (\w+) (\|o|\|\|)--(o\||o\{) (\w+) : "(.*)"$', line)
        if m:
            rels.append(m.groups())
            continue
        raise AssertionError(f"unparsed mermaid line: {line!r}")
    return tables, rels


def test_the_mermaid_diagram_matches_the_real_schema_exactly(info):
    tables, rels = parse_mermaid((ROOT / "docs/cinema_db/schema.mmd").read_text(encoding="utf-8"))
    s = info["structure"]
    assert set(tables) == {t["name"] for t in s["tables"]}
    for t in s["tables"]:
        want = []
        for c in t["columns"]:
            keys = [k for k, on in (("PK", c["pk"]), ("FK", c["fk"]), ("UK", c["unique"] and not c["pk"])) if on]
            want.append((c["name"], c["type"] or "ANY", ", ".join(keys)))
        assert tables[t["name"]] == want, t["name"]
    want_rels = [(r["parent"], "|o" if r["optional"] else "||", "o|" if r["cardinality"] == "one_to_one" else "o{", r["child"], ", ".join(r["child_columns"])) for r in s["relationships"]]
    assert rels == want_rels


def test_a_schema_change_changes_the_digest_and_makes_the_committed_docs_stale(tmp_path):
    base = create_database(tmp_path / "a.sqlite3")
    changed = tmp_path / "b.sqlite3"
    shutil.copy(base, changed)
    c = sqlite3.connect(changed)
    c.execute("ALTER TABLE person ADD COLUMN nickname TEXT")
    c.commit()
    c.close()
    with sqlite3.connect(base) as a, sqlite3.connect(changed) as b:
        assert introspect(a)["structure_digest"] != introspect(b)["structure_digest"]
    # the committed policy carries the digest of the schema it was generated from
    with sqlite3.connect(base) as a:
        assert introspect(a)["structure_digest"] == approved_views.STRUCTURE_DIGEST


def test_row_counts_and_sources_come_from_the_database_but_not_from_the_structure(tmp_path):
    seeded = build_real(tmp_path / "s.sqlite3")
    empty = create_database(tmp_path / "e.sqlite3")
    with sqlite3.connect(seeded) as a, sqlite3.connect(empty) as b:
        ia, ib = introspect(a), introspect(b)
    assert ia["structure_digest"] == ib["structure_digest"]  # data never changes the structure digest
    assert ia["counts"]["work"] == 6 and ib["counts"]["work"] == 0
    assert [s["name"] for s in ia["sources"]] == ["test-wikidata", "test-wikipedia"]
    assert "snapshot_sha256" not in json.dumps(ia["sources"])  # hashes are not published in the page


def test_views_and_columns_are_described_with_a_type(info):
    for v in info["structure"]["views"]:
        assert v["doc"] and v["columns"] and all(c["type"] in {"integer", "text", "real"} for c in v["columns"]), v["name"]
        assert v["reads"], f"{v['name']} reads no base table"
