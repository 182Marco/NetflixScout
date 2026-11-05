"""Reads the STRUCTURE of a cinema database from the SQLite file itself (PRAGMAs and sqlite_master).

Nothing here describes the schema by hand: tables, columns, types, keys, indexes, checks, views and the base columns each
view reads come from the file. Descriptions come from `cinema_db.schema_notes` and are checked for completeness.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from cinema_db import schema_notes as N

VIEW_PREFIX = "v_"
# Definitional lookups: a foreign key to one of these never makes a table a junction.
VOCAB_TABLES = frozenset({"relation_type", "role_type", "id_scheme", "work_kind"})


class NotesIncomplete(Exception):
    """A table, view or column has no description, or a description names something that does not exist."""


def _checks(sql: str) -> list[str]:
    """Text of every CHECK (...) in a CREATE TABLE statement (balanced parentheses, quotes respected)."""
    out, i, upper = [], 0, sql.upper()
    while True:
        i = upper.find("CHECK", i)
        if i < 0:
            return out
        j = sql.find("(", i)
        if j < 0:
            return out
        depth, k, quote = 0, j, None
        while k < len(sql):
            ch = sql[k]
            if quote:
                quote = None if ch == quote else quote
            elif ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(" ".join(sql[j + 1 : k].split()))
        i = k


def _virtual_entry(name: str, sql: str, shadow: list[str]) -> dict[str, Any]:
    """An external-content FTS5 table reads its content table directly when a query has no MATCH: those columns are part of it."""
    import re

    content = re.search(r"content\s*=\s*'([^']+)'", sql)
    rowid = re.search(r"content_rowid\s*=\s*'([^']+)'", sql)
    body = sql.split("(", 1)[1].rsplit(")", 1)[0]
    columns = [c.strip().split()[0] for c in re.split(r",(?![^()]*\))", body) if c.strip() and "=" not in c.split()[0] and "=" not in c]
    return {
        "name": name, "module": sql.split("USING", 1)[1].split("(", 1)[0].strip(), "shadow_tables": shadow,
        "content_table": content.group(1) if content else None,
        "content_columns": sorted(set(([rowid.group(1)] if rowid else []) + (columns if content else []))),
    }


def _fk_auto_doc(ref_table: str, ref_col: str) -> str:
    return f"Reference to {ref_table}.{ref_col}."


def introspect(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return {structure..., counts, sources}. `structure_digest` hashes only the structure (not counts or sources)."""
    cur = conn.cursor()
    master = {n: (t, s) for n, t, s in cur.execute("SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    virtual = {n: s_ for n, (t, s_) in master.items() if t == "table" and (s_ or "").upper().startswith("CREATE VIRTUAL TABLE")}
    shadow = {n: sorted(m for m, (t, _) in master.items() if t == "table" and m.startswith(n + "_")) for n in virtual}
    shadow_names = {m for ms in shadow.values() for m in ms}
    table_names = sorted(n for n, (t, _) in master.items() if t == "table" and n not in shadow_names)
    view_names = [n for n in master if master[n][0] == "view"]
    tables: list[dict[str, Any]] = []
    for name in table_names:
        sql = master[name][1]
        cols_raw = cur.execute(f'PRAGMA table_xinfo("{name}")').fetchall()
        fks_raw = cur.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
        by_id: dict[int, list[tuple]] = {}
        for fk in fks_raw:
            by_id.setdefault(fk[0], []).append(fk)
        fks = []
        for rows in by_id.values():
            rows.sort(key=lambda r: r[1])
            fks.append({"columns": [r[3] for r in rows], "ref_table": rows[0][2], "ref_columns": [r[4] for r in rows]})
        fk_of: dict[str, tuple[str, str]] = {}
        for fk in fks:
            for c, rc in zip(fk["columns"], fk["ref_columns"]):
                fk_of[c] = (fk["ref_table"], rc)
        pk = [c[1] for c in sorted((c for c in cols_raw if c[5]), key=lambda c: c[5])]
        indexes, uniques = [], []
        for idx in cur.execute(f'PRAGMA index_list("{name}")').fetchall():
            iname, unique, origin, partial = idx[1], bool(idx[2]), idx[3], bool(idx[4])
            cols = []
            for x in cur.execute(f'PRAGMA index_xinfo("{iname}")').fetchall():
                if x[5]:  # key column (not an included/rowid column)
                    cols.append(x[2] if x[2] is not None else "<expression>")
            isql = (master.get(iname) or (None, None))[1]
            entry = {"name": iname, "unique": unique, "columns": cols, "partial": partial, "origin": origin, "sql": " ".join(isql.split()) if isql else None}
            indexes.append(entry)
            if unique and not partial and "<expression>" not in cols:
                uniques.append(cols)
        indexes.sort(key=lambda i: i["name"])
        if pk and pk not in uniques:
            uniques.insert(0, pk)
        columns = []
        for c in cols_raw:
            if c[6]:  # hidden
                continue
            col = c[1]
            doc = N.COLUMNS.get(f"{name}.{col}")
            if doc is None:
                doc = N.COMMON.get(col) if col in N.COMMON else None
            if doc is None and col in fk_of:
                doc = _fk_auto_doc(*fk_of[col])
            columns.append({
                "name": col, "type": c[2], "not_null": bool(c[3]) or bool(c[5]), "default": c[4], "pk": c[5] or 0,
                "fk": {"table": fk_of[col][0], "column": fk_of[col][1]} if col in fk_of else None,
                "unique": any(u == [col] for u in uniques), "doc": doc,
            })
        # A junction links two or more entities: its primary key holds foreign keys to at least two non-vocabulary groups.
        pk_links = [fk for fk in fks if set(fk["columns"]) <= set(pk) and fk["ref_table"] not in VOCAB_TABLES]
        junction = len(pk) >= 2 and len(pk_links) >= 2
        tables.append({
            "name": name, "group": N.TABLE_GROUP.get(name), "doc": N.TABLES.get(name), "virtual": name in virtual,
            "strict": bool(sql and " STRICT" in sql.upper().split(")")[-1]),
            "columns": columns, "primary_key": pk, "foreign_keys": fks, "unique": uniques, "indexes": indexes,
            "checks": _checks(sql or ""), "junction": junction, "sql": " ".join((sql or "").split()),
        })
    t_by = {t["name"]: t for t in tables}
    rels = []
    for t in tables:
        for fk in t["foreign_keys"]:
            cols = fk["columns"]
            one = sorted(cols) == sorted(t["primary_key"]) or any(sorted(u) == sorted(cols) for u in t["unique"])
            optional = not all(next(c for c in t["columns"] if c["name"] == x)["not_null"] for x in cols)
            kind = "subtype" if one and fk["ref_table"] == "entity" else ("junction" if t["junction"] else "reference")
            rels.append({
                "child": t["name"], "child_columns": cols, "parent": fk["ref_table"], "parent_columns": fk["ref_columns"],
                "cardinality": "one_to_one" if one else "one_to_many", "optional": optional, "kind": kind,
            })
    rels.sort(key=lambda r: (r["child"], r["child_columns"], r["parent"]))
    m2m = []
    for t in tables:
        if t["junction"]:
            parents = []
            for fk in sorted(t["foreign_keys"], key=lambda f: t["primary_key"].index(f["columns"][0]) if f["columns"][0] in t["primary_key"] else 99):
                # only the keys that are part of the primary key define the many-to-many; vocab lookups (relation_type) do not
                if fk["ref_table"] in VOCAB_TABLES or not set(fk["columns"]) <= set(t["primary_key"]):
                    continue
                parents.append(fk["ref_table"])
            if len(parents) >= 2:
                m2m.append({"via": t["name"], "a": parents[0], "b": parents[1]})
    for t in tables:  # associative tables with their own key (credit, award_result) that link a work and a person
        linked = {fk["ref_table"] for fk in t["foreign_keys"]}
        if not t["junction"] and {"work", "person"} <= linked:
            m2m.append({"via": t["name"], "a": "work", "b": "person"})
    m2m.sort(key=lambda m: m["via"])
    views = []
    for vname in sorted(view_names):
        vcols = cur.execute(f'PRAGMA table_info("{vname}")').fetchall()
        reads: set[tuple[str, str]] = set()

        def rec(action, a1, a2, db, src, reads=reads):
            if action == sqlite3.SQLITE_READ and src is not None and (a1 or "") not in view_names:
                reads.add((a1, a2))
            return sqlite3.SQLITE_OK

        conn.set_authorizer(rec)
        try:
            cur.execute(f'SELECT * FROM "{vname}" LIMIT 0').fetchall()
        finally:
            conn.set_authorizer(None)
        notes = N.VIEW_COLUMNS.get(vname, {})
        views.append({
            "name": vname, "group": "view", "doc": N.VIEWS.get(vname), "sql": " ".join((master[vname][1] or "").split()),
            "columns": [{"name": c[1], "type": notes.get(c[1], ("", None))[0], "doc": notes.get(c[1], ("", None))[1]} for c in vcols],
            "reads": sorted({r[0] for r in reads if r[0]}), "base_columns": sorted(f"{r[0]}.{r[1]}" for r in reads if r[0] and r[1]),
        })
    structure = {
        "schema_version": int(cur.execute("SELECT value FROM build_info WHERE key='schema_version'").fetchone()[0]),
        "groups": N.GROUPS, "group_order": list(N.GROUPS), "tables": tables,
        "virtual_tables": [_virtual_entry(n, virtual[n], shadow[n]) for n in sorted(virtual)],
        "engine": {"functions": list(N.ENGINE_FUNCTIONS), "pragmas": list(N.ENGINE_PRAGMAS)}, "relationships": rels, "many_to_many": m2m, "views": views,
    }
    digest = hashlib.sha256(json.dumps(structure, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    counts = {t["name"]: cur.execute(f'SELECT count(*) FROM "{t["name"]}"').fetchone()[0] for t in tables}
    sources = [dict(zip(("name", "kind", "url", "license", "usage_scope", "attribution_required", "snapshot_label", "retrieved_at"), r))
               for r in cur.execute("SELECT name, kind, url, license, usage_scope, attribution_required, snapshot_label, retrieved_at FROM source ORDER BY source_id")]
    return {"structure": structure, "structure_digest": digest, "counts": counts, "sources": sources}


def check_notes(info: dict[str, Any]) -> list[str]:
    """Problems between the real schema and the descriptions. Empty list = complete and exact."""
    problems: list[str] = []
    s = info["structure"]
    tnames = {t["name"] for t in s["tables"]}
    for t in s["tables"]:
        if not t["doc"]:
            problems.append(f"table {t['name']}: no description")
        if t["group"] not in N.GROUPS:
            problems.append(f"table {t['name']}: no group")
        for c in t["columns"]:
            if not c["doc"]:
                problems.append(f"column {t['name']}.{c['name']}: no description")
    for v in s["views"]:
        if not v["doc"]:
            problems.append(f"view {v['name']}: no description")
        for c in v["columns"]:
            if not c["doc"] or not c["type"]:
                problems.append(f"view column {v['name']}.{c['name']}: no type/description")
        if not v["name"].startswith(VIEW_PREFIX):
            problems.append(f"view {v['name']}: public views must start with {VIEW_PREFIX}")
    cols = {(t["name"], c["name"]) for t in s["tables"] for c in t["columns"]}
    for key in N.COLUMNS:
        tab, col = key.split(".")
        if (tab, col) not in cols:
            problems.append(f"description for a column that does not exist: {key}")
    for name in N.TABLES:
        if name not in tnames:
            problems.append(f"description for a table that does not exist: {name}")
    for name in N.TABLE_GROUP:
        if name not in tnames:
            problems.append(f"group for a table that does not exist: {name}")
    vnames = {v["name"] for v in s["views"]}
    for name, cols_ in N.VIEW_COLUMNS.items():
        if name not in vnames:
            problems.append(f"description for a view that does not exist: {name}")
        else:
            real = [c["name"] for c in next(v for v in s["views"] if v["name"] == name)["columns"]]
            if list(cols_) != real:
                problems.append(f"view {name}: described columns {list(cols_)} differ from the real ones {real}")
    for name in N.VIEWS:
        if name not in vnames:
            problems.append(f"description for a view that does not exist: {name}")
    return problems
