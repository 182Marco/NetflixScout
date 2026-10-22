"""Terminal print blocks for the movie DB queries (same box style as `terminal/blocks.py`)."""
from __future__ import annotations

import textwrap

_SQL_WIDTH = 64


def print_db_queries(title: str, sql_statements: list[str]) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    header = f"{title} — {len(sql_statements)} QUERY ESEGUITE"
    print(f"║  🗄️  {header.upper():<62}║")
    print("╚" + "═" * 68 + "╝")

    if not sql_statements:
        print("\n  Nessuna query eseguita.")
        return

    for index, sql in enumerate(sql_statements, start=1):
        print()
        print(f"  🔹 QUERY #{index}")
        print("  " + "─" * 64)
        lines = textwrap.wrap(sql, width=_SQL_WIDTH) or [sql]
        print(f"  🧾 {lines[0]}")
        for line in lines[1:]:
            print(f"     {line}")
