"""Terminal print blocks for the movie DB queries (same box style as `terminal/box.py`)."""
from __future__ import annotations

import textwrap

from ..box import print_box
from ..texts import texts

_SQL_WIDTH = 64


def print_db_queries(title: str, sql_statements: list[str], language: str = "it") -> None:
    text = texts(language)
    print_box("🗄️", f"{title} — {len(sql_statements)} {text['db_executed']}")

    if not sql_statements:
        print(f"\n  {text['db_none']}")
        return

    for index, sql in enumerate(sql_statements, start=1):
        print()
        print(f"  🔹 {text['db_query']} #{index}")
        print("  " + "─" * 64)
        lines = textwrap.wrap(sql, width=_SQL_WIDTH) or [sql]
        print(f"  🧾 {lines[0]}")
        for line in lines[1:]:
            print(f"     {line}")
