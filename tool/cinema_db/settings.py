"""Constants of the SQL guard. Pure data."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryLimits:
    max_rows: int = 50
    timeout_ms: int = 2000
    max_sql_chars: int = 2000
    max_params: int = 16
    max_param_chars: int = 200
    max_literals: int = 32
    max_literal_chars: int = 200
    max_nodes: int = 600
    max_joins: int = 4
    max_subquery_depth: int = 3
    max_set_branches: int = 3
    max_offset: int = 10_000
    max_cell_chars: int = 500
    max_result_chars: int = 60_000
    # SQLite limits set on the connection (statement length is derived from max_sql_chars).
    sqlite_expr_depth: int = 40
    sqlite_function_args: int = 8
    sqlite_like_pattern: int = 100
    sqlite_value_length: int = 100_000
    sqlite_columns: int = 64


# Names as SQLite's authorizer reports them (lower case). `ifnull` is rewritten to `coalesce` by the parser.
# Not allowed on purpose: random, randomblob, zeroblob, printf/format, load_extension, readfile/writefile, json_*,
# fts/match helpers, sqlite_*, table-valued functions.
DEFAULT_FUNCTIONS: frozenset[str] = frozenset(
    {
        # aggregates
        "count", "sum", "avg", "min", "max", "total", "group_concat",
        # scalars
        "abs", "coalesce", "ifnull", "nullif", "iif", "length", "lower", "upper", "substr", "substring",
        "trim", "ltrim", "rtrim", "replace", "instr", "round", "typeof",
        # operators SQLite reports as functions
        "like", "glob",
    }
)
# Syntax that renders like a call but is not reported by the authorizer as a function.
SYNTAX_CALLS: frozenset[str] = frozenset({"cast"})
