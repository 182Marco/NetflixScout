"""Interactive schema map of a v3 database (tables, columns, keys, cardinalities, links), read from the REAL SQLite file.

    python -m cinema_db.harness.schema.generate_v3 --db cinema_db/data/cinema.v3.sqlite3 [--out docs/cinema_db/schema_v3.html]

The committed notes (`cinema_db/schema_notes.py`) describe the runtime v2 schema and must not know tables that file does not have,
so the descriptions of the four v3 tables are added here, in memory, only for this run. Nothing is written but the HTML.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from cinema_db import schema_notes as N
from cinema_db import schema_notes_v3 as NV3
from cinema_db.harness.schema import render
from cinema_db.harness.schema.introspect import check_notes, introspect

ROOT = Path(__file__).resolve().parents[3]


def build_info(db: Path) -> dict:
    with NV3.applied(N):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            info = introspect(conn)
        finally:
            conn.close()
        problems = check_notes(info)  # inside the block: the notes are the v3 ones
    info["notes_problems"] = problems
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "cinema_db/data/cinema.v3.sqlite3")
    ap.add_argument("--out", type=Path, default=ROOT / "docs/cinema_db/schema_v3.html")
    args = ap.parse_args(argv)
    info = build_info(args.db)
    problems = info.pop("notes_problems")
    if problems:
        print("notes incomplete:\n" + "\n".join(problems), file=sys.stderr)
        return 2
    args.out.write_text(render.html(info), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
