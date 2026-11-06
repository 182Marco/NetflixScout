"""The graphical map of the schema (docs/cinema_db/schema.html) against the REAL SQLite schema, read here with plain PRAGMAs and independently of `introspect.py`.

Checked: every table and column (name, type), every primary key, every foreign key, no invented relation, the Mermaid diagram, and the graph the page draws (its model, its
layout and its edge geometry, run in Node from the page's own script: the pure functions that build nodes and edges). The browser rendering was looked at in Chrome
(headless screenshots); an opt-in test drives Chrome itself (set CINEMA_MAP_BROWSER_TEST=1) because headless Chrome is slow on some machines.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pytest

from cinema_db.harness.schema import map_view, render
from cinema_db.schema import create_database

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs/cinema_db/schema.html"
MERMAID = ROOT / "docs/cinema_db/schema.mmd"
REAL_DB = ROOT / "cinema_db/data/cinema.sqlite3"


def pragma_schema(path: Path) -> dict:
    """tables -> columns [(name, type, pk position)], foreign keys {(child, from, parent, to)}; read with PRAGMA only. FTS5 shadow tables are not tables of the model."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        master = {n: (t, s or "") for n, t, s in conn.execute("SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        virtual = [n for n, (t, s) in master.items() if t == "table" and s.upper().startswith("CREATE VIRTUAL TABLE")]
        shadow = {n for n, (t, _) in master.items() if t == "table" and any(n.startswith(v + "_") for v in virtual)}
        tables = sorted(n for n, (t, _) in master.items() if t == "table" and n not in shadow)
        columns, fk_columns, fks = {}, set(), set()
        for name in tables:
            columns[name] = [(r[1], r[2], r[5]) for r in conn.execute(f'PRAGMA table_xinfo("{name}")') if not r[6]]
            by_id: dict[int, list[tuple]] = {}
            for r in conn.execute(f'PRAGMA foreign_key_list("{name}")'):
                fk_columns.add((name, r[3], r[2], r[4]))
                by_id.setdefault(r[0], []).append(r)
            for rows in by_id.values():  # one foreign key can span several columns: (work_id, entity_type) -> entity
                rows.sort(key=lambda r: r[1])
                fks.add((name, tuple(r[3] for r in rows), rows[0][2], tuple(r[4] for r in rows)))
        return {"tables": tables, "columns": columns, "fks": fks, "fk_columns": fk_columns, "views": sorted(n for n, (t, _) in master.items() if t == "view")}
    finally:
        conn.close()


def embedded(text: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="schema-data">(.*?)</script>', text, re.S).group(1).replace("<\\/", "</"))


@pytest.fixture(scope="module")
def committed():
    return embedded(HTML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema_only(tmp_path_factory):
    return pragma_schema(create_database(tmp_path_factory.mktemp("map") / "c.sqlite3"))


def test_every_table_column_type_and_primary_key_of_the_database_is_on_the_map(committed, schema_only):
    s = committed["structure"]
    assert [t["name"] for t in s["tables"]] == schema_only["tables"] and len(s["tables"]) >= 30
    for t in s["tables"]:
        want = schema_only["columns"][t["name"]]
        assert [(c["name"], c["type"] or "") for c in t["columns"]] == [(n, ty or "") for n, ty, _ in want], t["name"]
        assert t["primary_key"] == [n for n, _, pk in sorted(want, key=lambda c: c[2]) if pk], t["name"]
        assert [c["name"] for c in t["columns"] if c["pk"]] == [n for n, _, pk in want if pk]
    assert [v["name"] for v in s["views"]] == schema_only["views"]


def test_every_foreign_key_is_a_relation_and_no_relation_is_invented(committed, schema_only):
    s = committed["structure"]
    relations = {(r["child"], tuple(r["child_columns"]), r["parent"], tuple(r["parent_columns"])) for r in s["relationships"]}
    assert relations == schema_only["fks"] and len(schema_only["fks"]) >= 60
    assert len(s["relationships"]) == len(schema_only["fks"])  # one relation per foreign key, none twice
    assert {(r["child"], c, r["parent"], p) for r in s["relationships"] for c, p in zip(r["child_columns"], r["parent_columns"])} == schema_only["fk_columns"]  # column by column too
    declared = {(t["name"], c, f["table"], f["column"]) for t in s["tables"] for c in [c for c in t["columns"] if c["fk"]] for f in [c["fk"]] for c in [c["name"]]}
    assert declared == schema_only["fk_columns"]
    for r in s["relationships"]:  # cardinality only from constraints: a child column that is the whole primary key or unique is one-to-one
        child = next(t for t in s["tables"] if t["name"] == r["child"])
        one = sorted(r["child_columns"]) == sorted(child["primary_key"]) or any(sorted(u) == sorted(r["child_columns"]) for u in child["unique"])
        assert (r["cardinality"] == "one_to_one") == one, r


def test_junction_tables_are_the_ones_whose_primary_key_joins_two_entities(committed):
    s = committed["structure"]
    junctions = {t["name"] for t in s["tables"] if t["junction"]}
    assert {"work_genre", "work_country", "work_language", "work_company", "work_franchise", "work_relation", "genre_label_map"} <= junctions
    assert not junctions & {"work", "person", "credit", "award_result", "entity"}  # credit and award_result are associative tables with their own key, listed as many-to-many too
    assert {(m["a"], m["b"], m["via"]) for m in s["many_to_many"]} >= {("work", "person", "credit"), ("work", "person", "award_result")}
    for m in s["many_to_many"]:
        via = next(t for t in s["tables"] if t["name"] == m["via"])
        assert {m["a"], m["b"]} <= {f["ref_table"] for f in via["foreign_keys"]}  # a many-to-many only exists where the bridge really points at both sides


def test_the_mermaid_relations_are_exactly_the_foreign_keys(schema_only):
    text = MERMAID.read_text(encoding="utf-8")
    declared = {m.group(1) for m in re.finditer(r"^    (\w+) \{$", text, re.M)}
    assert declared == set(schema_only["tables"])
    parsed = {(m.group(2), m.group(3), m.group(1)) for m in re.finditer(r'^    (\w+) (?:\|o|\|\|)--(?:o\||o\{) (\w+) : "(.*)"$', text, re.M)}
    assert len(parsed) == len(re.findall(r'--(?:o\||o\{) ', text))  # no relation drawn twice
    want = {(child, col, parent) for child, cols, parent, _ in schema_only["fks"] for col in [", ".join(cols)]}
    assert parsed == want


def test_the_committed_html_is_the_one_the_generator_writes_and_has_the_map_controls():
    text = HTML.read_text(encoding="utf-8")
    assert text == render.html(_info()), "run python -m cinema_db.harness.schema.generate"
    for needle in ('id="mapsvg"', 'id="zin"', 'id="zout"', 'id="zfit"', 'id="zrelayout"', 'id="zsource"', 'id="mode-map"', 'id="mode-cards"', 'type="search"', 'id="detail"', "wheel", "pointerdown"):
        assert needle in text, needle
    assert not re.findall(r'(?:src|href)=["\']https?://', text) and "<script src" not in text


def _info():
    from cinema_db.harness.schema.introspect import introspect

    with tempfile.TemporaryDirectory() as tmp:
        conn = sqlite3.connect(create_database(Path(tmp) / "c.sqlite3"))
        try:
            return introspect(conn)
        finally:
            conn.close()


# ---- the graph the page draws, run in Node from the page's own functions -------------------------------------------------------------
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")


def run_in_node(structure: dict, counts: dict, *, show_views: bool = False) -> dict:
    js = map_view.JS
    pure = js[js.index("function mapModel"): js.index("function mapDefs")]  # mapModel, layoutMap, rectPoint, edgePath: no DOM
    program = f"""
const S={json.dumps(structure)},D={{counts:{json.dumps(counts)}}};
const state={{groups:new Set(Object.keys(S.groups)),showViews:{str(show_views).lower()},sel:null,q:''}};
const mp={{nodes:new Map()}};
{pure}
const model=mapModel();layoutMap(model.nodes,model.edges);
mp.nodes=new Map(model.nodes.map(n=>[n.name,n]));
const pair=new Map();model.edges.forEach(e=>{{const k=[e.child,e.parent].sort().join('>');(pair.get(k)||pair.set(k,[]).get(k)).push(e)}});
for(const l of pair.values())l.forEach((e,i)=>{{e.idx=i;e.total=l.length}});
const geom=model.edges.map(e=>edgePath(e,e.idx,e.total));
console.log(JSON.stringify({{nodes:model.nodes.map(n=>({{name:n.name,kind:n.kind,group:n.group,x:n.x,y:n.y,w:n.w,h:n.h}})),edges:model.edges.map(e=>({{child:e.child,parent:e.parent,cols:e.cols,pcols:e.pcols,card:e.card,optional:e.optional,kind:e.kind,prov:!!e.prov}})),geom}}));
"""
    proc = subprocess.run([NODE, "-e", program], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@needs_node
def test_the_graph_has_one_node_per_table_and_one_edge_per_foreign_key(committed, schema_only):
    out = run_in_node(committed["structure"], committed["counts"])
    assert sorted(n["name"] for n in out["nodes"]) == schema_only["tables"]
    drawn = {(e["child"], e["cols"], e["parent"], e["pcols"]) for e in out["edges"]}
    assert drawn == {(c, ", ".join(cols), p, ", ".join(pcols)) for c, cols, p, pcols in schema_only["fks"]}  # no edge without a foreign key, no foreign key without an edge
    assert len(out["edges"]) == len(schema_only["fks"])
    for e in out["edges"]:
        assert e["prov"] == (e["parent"] == "source")
        assert e["kind"] in {"reference", "junction", "subtype"} and e["card"] in {"one_to_many", "one_to_one"}
    kinds = {n["name"]: n["kind"] for n in out["nodes"]}
    assert kinds["credit"] == "table" and kinds["work_genre"] == "junction" and kinds["entity_name_fts"] == "fts"


@needs_node
def test_public_views_become_nodes_that_only_read_the_tables_they_really_read(committed, schema_only):
    out = run_in_node(committed["structure"], committed["counts"], show_views=True)
    assert len([n for n in out["nodes"] if n["kind"] == "view"]) == len(schema_only["views"])
    reads = {(e["child"], e["parent"]) for e in out["edges"] if e["kind"] == "reads"}
    want = {(v["name"], t) for v in committed["structure"]["views"] for t in v["reads"] if t in schema_only["tables"]}
    assert reads == want and reads


@needs_node
def test_the_layout_is_deterministic_finite_and_leaves_no_two_tables_overlapping(committed):
    a = run_in_node(committed["structure"], committed["counts"])
    b = run_in_node(committed["structure"], committed["counts"])
    assert a == b  # the same schema always gives the same map
    nodes = a["nodes"]
    assert all(all(isinstance(n[k], (int, float)) and abs(n[k]) < 5000 for k in ("x", "y")) for n in nodes)
    overlaps = [(p["name"], q["name"]) for i, p in enumerate(nodes) for q in nodes[i + 1:]
                if abs(p["x"] - q["x"]) < (p["w"] + q["w"]) / 2 and abs(p["y"] - q["y"]) < (p["h"] + q["h"]) / 2]
    assert not overlaps, overlaps
    assert len({n["name"] for n in nodes}) == len(nodes) >= 30


@needs_node
def test_every_edge_has_a_finite_path_even_between_the_same_two_tables_and_on_itself(committed):
    out = run_in_node(committed["structure"], committed["counts"])
    assert len(out["geom"]) == len(out["edges"])
    for e, g in zip(out["edges"], out["geom"]):
        numbers = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", g["d"])]
        assert numbers and all(abs(x) < 6000 for x in numbers), (e, g)
    pairs = {}
    for e, g in zip(out["edges"], out["geom"]):
        pairs.setdefault(tuple(sorted((e["child"], e["parent"]))), set()).add(g["d"])
    multi = {k: v for k, v in pairs.items() if sum(1 for e in out["edges"] if tuple(sorted((e["child"], e["parent"]))) == k) > 1 and k[0] != k[1]}
    assert multi and all(len(v) == sum(1 for e in out["edges"] if tuple(sorted((e["child"], e["parent"]))) == k) for k, v in multi.items())  # work_relation -> work twice: two curves
    assert any(e["child"] == e["parent"] for e in out["edges"])  # work.parent_work_id -> work: a loop, drawn


@needs_node
def test_a_schema_with_fewer_or_more_tables_changes_the_graph_with_it(committed):
    structure = json.loads(json.dumps(committed["structure"]))
    structure["tables"] = [t for t in structure["tables"] if t["name"] != "credit"]
    structure["relationships"] = [r for r in structure["relationships"] if "credit" not in (r["child"], r["parent"])]
    out = run_in_node(structure, committed["counts"])
    assert "credit" not in {n["name"] for n in out["nodes"]} and not [e for e in out["edges"] if "credit" in (e["child"], e["parent"])]


@pytest.mark.skipif(os.environ.get("CINEMA_MAP_BROWSER_TEST") != "1", reason="opt-in: drives headless Chrome (slow); set CINEMA_MAP_BROWSER_TEST=1")
def test_the_page_renders_in_a_real_browser_with_one_svg_node_per_table_and_edge_per_foreign_key(schema_only, tmp_path):
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).is_file():
        pytest.skip("Chrome is not installed")
    dom = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'profile'}", "--virtual-time-budget=5000", "--dump-dom", f"file://{HTML}#t=credit"],
                         capture_output=True, text=True, timeout=300).stdout
    assert len(re.findall(r'<g class="node ', dom)) == len(schema_only["tables"])
    assert len(re.findall(r'<path class="edge', dom)) == len(schema_only["fks"])
    assert re.findall(r'class="node [^"]*\bsel\b[^"]*" id="n-([a-z_]+)"', dom) == ["credit"]
