"""Reading-only rendering of an executed SQL statement (bind parameters inlined), shared by the cinema presenters. Pure: no printing."""
from __future__ import annotations

SqlParam = str | int | float | None


def _literal(value: SqlParam) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def format_sql(sql: str, params: list[SqlParam]) -> str:
    """Inline the bind parameters for reading only: the result is never executed.

    `?` inside quoted SQL literals is left alone; if the placeholders do not match the
    parameters, the original SQL is returned unchanged.
    """
    if sql.count("?") < len(params):
        return sql
    out: list[str] = []
    values = iter(params)
    used = 0
    quote: str | None = None
    for char in sql:
        if quote:
            out.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "?":
            try:
                out.append(_literal(next(values)))
                used += 1
            except StopIteration:
                return sql
        else:
            out.append(char)
    return "".join(out) if used == len(params) else sql
