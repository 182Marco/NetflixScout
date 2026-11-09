"""Syntactic validation of the SQL written by the model. Pure: no connection, no I/O.

`validate()` parses the text into an AST (sqlglot, sqlite dialect), checks it, qualifies every column against the
policy's views, bounds LIMIT, and returns the text GENERATED from the checked AST. That regenerated text, never the
model's text, is what runs; it is parsed and checked again before it is returned.
"""
from __future__ import annotations

import logging
import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify

from .errors import SqlRejected
from .policy import Policy
from .settings import SYNTAX_CALLS

DIALECT = "sqlite"
Param = str | int | float | None
_INT64 = 2**63

# sqlglot logs a warning when it falls back to a generic Command (EXPLAIN, VACUUM, REPLACE): we reject those anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)


def _classes(*names: str) -> tuple[type, ...]:
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


_ROOTS = _classes("Select", "SetOperation", "Union", "Intersect", "Except")
_SET_OPS = _classes("SetOperation", "Union", "Intersect", "Except")
_FORBIDDEN = _classes(
    "Insert", "Update", "Delete", "Create", "Drop", "Alter", "AlterTable", "Attach", "Detach", "Pragma", "Command",
    "Transaction", "Commit", "Rollback", "Set", "Use", "Into", "Returning", "Merge", "Copy", "Values", "Unnest",
    "Window", "Lateral", "Pivot", "Hint", "Lock", "Analyze", "Describe", "Kill", "Grant", "TruncateTable",
    "Declare", "LoadData", "Export", "Vacuum", "Reindex", "Comment", "Parameter", "SessionParameter", "Star_",
)
_CALL_NAME = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str  # generated from the checked AST: this is what is executed
    params: tuple[Param, ...]
    views: tuple[str, ...]  # views read, as declared in the policy
    limit: int


def reject(code: str, message: str) -> SqlRejected:
    return SqlRejected(message, code=code)


def validate(sql: object, params: object, policy: Policy) -> ValidatedQuery:
    limits = policy.limits
    if not isinstance(sql, str) or not sql.strip():
        raise reject("empty", "The statement is empty.")
    if len(sql) > limits.max_sql_chars:
        raise reject("too_long", f"The statement exceeds {limits.max_sql_chars} characters.")
    if "\x00" in sql:
        raise reject("control_chars", "The statement contains a NUL character.")
    values = _check_params(params, limits)

    text, view_tuple, limit = _checked(sql, len(values), policy)
    return ValidatedQuery(sql=text, params=values, views=view_tuple, limit=limit)


# The checked form of a statement depends only on its text, the NUMBER of parameters and the policy (values are checked apart, every time), so the result of the
# full check (parse, structure, qualify, rewrite, second check) is remembered by that key: the tool writes the same few statement shapes again and again, and
# parsing them is most of the cost of a call. A rejection raises and is never remembered; a hit returns exactly what the same check would have returned.
_CHECKED: "OrderedDict[tuple[str, int, int], tuple[Policy, str, tuple[str, ...], int]]" = OrderedDict()
_CHECKED_MAX = 256
_CHECKED_LOCK = threading.Lock()


def _checked(sql: str, n_params: int, policy: Policy) -> tuple[str, tuple[str, ...], int]:
    key = (sql, n_params, id(policy))
    with _CHECKED_LOCK:
        hit = _CHECKED.get(key)
        if hit is not None and hit[0] is policy:
            _CHECKED.move_to_end(key)
            return hit[1], hit[2], hit[3]
    text, views, limit = _check_statement(sql, n_params, policy)
    with _CHECKED_LOCK:
        _CHECKED[key] = (policy, text, views, limit)
        while len(_CHECKED) > _CHECKED_MAX:
            _CHECKED.popitem(last=False)
    return text, views, limit


def _check_statement(sql: str, n_params: int, policy: Policy) -> tuple[str, tuple[str, ...], int]:
    limits = policy.limits
    root = _parse_single(sql)
    views = _structure(root, policy, expected_params=n_params)
    schema = policy.schema_for_qualify()
    try:
        qualified = qualify(
            root.copy(), schema=schema, dialect=DIALECT, validate_qualify_columns=True, expand_stars=True
        )
    except SqlglotError:
        raise reject("column_not_allowed", "A column or table is not part of the approved views.") from None
    except Exception:  # sqlglot internals: never let a parser bug turn into an execution
        raise reject("unsupported", "The statement could not be analysed.") from None
    limit = _bound_limit(qualified, limits.max_rows, limits.max_offset)
    text = qualified.sql(dialect=DIALECT, comments=False)
    if len(text) > limits.max_sql_chars * 4:
        raise reject("too_long", "The rewritten statement is too long.")

    # The rewritten text must pass the same structural checks and read the same views.
    again = _structure(_parse_single(text), policy, expected_params=n_params)
    if again != views:
        raise reject("unstable_rewrite", "The rewritten statement differs from the checked one.")
    return text, tuple(sorted(views)), limit


# --- parsing -------------------------------------------------------------------------------------------------


def _parse_single(sql: str) -> exp.Expression:
    try:
        statements = sqlglot.parse(sql, read=DIALECT)
    except SqlglotError:
        raise reject("syntax", "The statement is not valid SQL.") from None
    except Exception:
        raise reject("syntax", "The statement could not be parsed.") from None
    found = [s for s in statements if s is not None]
    if len(found) > 1:
        raise reject("multiple_statements", "Only one statement is allowed.")
    if not found:
        raise reject("empty", "The statement is empty.")
    return found[0]


# --- parameters ----------------------------------------------------------------------------------------------


def _check_params(params: object, limits) -> tuple[Param, ...]:
    if params is None:
        return ()
    if not isinstance(params, (list, tuple)):
        raise reject("params", "params must be a list.")
    if len(params) > limits.max_params:
        raise reject("params", f"At most {limits.max_params} parameters are allowed.")
    out: list[Param] = []
    for value in params:
        if isinstance(value, bool) or not (value is None or isinstance(value, (str, int, float))):
            raise reject("params", "Parameters must be strings, numbers or null.")
        if isinstance(value, str) and (len(value) > limits.max_param_chars or "\x00" in value):
            raise reject("params", "A text parameter is too long or contains a NUL character.")
        if isinstance(value, int) and not -_INT64 <= value < _INT64:
            raise reject("params", "An integer parameter is out of range.")
        if isinstance(value, float) and not math.isfinite(value):
            raise reject("params", "A number parameter is not finite.")
        out.append(value)
    return tuple(out)


# --- structure -----------------------------------------------------------------------------------------------


def _structure(root: exp.Expression, policy: Policy, *, expected_params: int) -> set[str]:
    """Checks that do not need the schema. Returns the set of policy views the statement reads."""
    limits = policy.limits
    if not isinstance(root, _ROOTS):
        raise reject("statement_type", "Only SELECT statements are allowed.")
    nodes = 0
    placeholders = 0
    literals = 0
    joins = 0
    branches = 1
    for node in root.walk():
        nodes += 1
        if isinstance(node, _FORBIDDEN):
            raise reject("forbidden_construct", f"{type(node).__name__} is not allowed.")
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise reject("recursive", "Recursive queries are not allowed.")
        if isinstance(node, exp.Placeholder):
            if node.this is not None:
                raise reject("named_parameter", "Only positional ? parameters are allowed.")
            placeholders += 1
        if isinstance(node, exp.Literal):
            literals += 1
            if len(str(node.this)) > limits.max_literal_chars:
                raise reject("literal_too_long", "A literal is too long.")
        if isinstance(node, exp.Join):
            joins += 1
            _check_join(node)
        if isinstance(node, _SET_OPS):
            branches += 1
    if nodes > limits.max_nodes:
        raise reject("too_complex", "The statement is too complex.")
    if placeholders != expected_params:
        raise reject("params", "The number of ? placeholders does not match the parameters.")
    if literals > limits.max_literals:
        raise reject("too_many_literals", "Too many literals; use parameters.")
    if joins > limits.max_joins:
        raise reject("too_many_joins", f"At most {limits.max_joins} joins are allowed.")
    if branches - 1 >= limits.max_set_branches:
        raise reject("too_many_branches", f"At most {limits.max_set_branches} UNION branches are allowed.")
    if _subquery_depth(root) > limits.max_subquery_depth:
        raise reject("too_deep", f"Subqueries nest at most {limits.max_subquery_depth} levels.")
    views = _check_tables(root, policy)
    _check_functions(root, policy)
    return views


def _check_join(join: exp.Join) -> None:
    kind = str(join.args.get("kind") or "").upper()
    if kind == "CROSS" or join.args.get("method") or join.args.get("natural"):
        raise reject("join_kind", "CROSS and NATURAL joins are not allowed.")
    on, using = join.args.get("on"), join.args.get("using")
    if on is None and not using:
        raise reject("join_without_condition", "Every join needs an ON or USING condition.")
    if on is not None:
        # The parser writes `ON TRUE` for a join without condition: a constant (or one-sided) condition is a
        # cartesian product. Once columns are qualified, the condition must relate two different tables.
        columns = list(on.find_all(exp.Column))
        if not columns:
            raise reject("join_without_condition", "A join condition must compare columns.")
        tables = {c.table for c in columns}
        if all(tables) and len(tables) < 2:
            raise reject("join_without_condition", "A join condition must relate two different tables.")


def _subquery_depth(node: exp.Expression, depth: int = 0) -> int:
    best = depth
    for child in node.iter_expressions():
        step = depth + 1 if isinstance(child, (exp.Subquery, exp.Select)) and child.parent is not None else depth
        best = max(best, _subquery_depth(child, step))
    return best


def _check_tables(root: exp.Expression, policy: Policy) -> set[str]:
    reserved = policy.view_names | policy.base_table_names
    ctes: set[str] = set()
    for cte in root.find_all(exp.CTE):
        name = cte.alias_or_name.casefold()
        if name in reserved or name.startswith("sqlite_"):
            raise reject("cte_shadows_table", "A CTE cannot reuse the name of a table or view.")
        ctes.add(name)
    views: set[str] = set()
    for table in root.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog"):
            raise reject("qualified_name", "Schema-qualified names are not allowed.")
        if not isinstance(table.this, exp.Identifier):
            raise reject("table_function", "Table-valued functions are not allowed.")
        name = table.name.casefold()
        if name in ctes:
            continue
        spec = policy.view(name)
        if spec is None:
            raise reject("table_not_allowed", "Only the approved views can be read.")
        views.add(spec.name)
    return views


def _function_name(node: exp.Func) -> str | None:
    if isinstance(node, exp.Anonymous):
        return str(node.name).casefold()
    match = _CALL_NAME.match(node.sql(dialect=DIALECT, comments=False))
    return match.group(1).casefold() if match else None  # CASE, operators, etc. do not call a function


def _check_functions(root: exp.Expression, policy: Policy) -> None:
    for node in root.find_all(exp.Func):
        name = _function_name(node)
        if name is None or name in SYNTAX_CALLS:
            continue
        if name not in policy.functions:
            raise reject("function_not_allowed", "A function is not on the approved list.")


# --- LIMIT ---------------------------------------------------------------------------------------------------


def _bound_limit(root: exp.Expression, max_rows: int, max_offset: int) -> int:
    """Rows the caller may receive. When the cap (not the caller's own LIMIT) bounds the result, the SQL asks for one
    extra row so that the executor can tell the result was cut."""
    limit = root.args.get("limit")
    if limit is None:
        root.set("limit", exp.Limit(expression=exp.Literal.number(max_rows + 1)))
        value = max_rows
    else:
        amount = limit.args.get("expression")
        if not (isinstance(amount, exp.Literal) and not amount.is_string and str(amount.this).isdigit()):
            raise reject("limit_not_literal", "LIMIT must be a whole number written in the statement.")
        value = int(amount.this)
        if value >= max_rows:
            limit.set("expression", exp.Literal.number(max_rows + 1))
            value = max_rows
    offset = root.args.get("offset")
    if offset is not None:
        amount = offset.args.get("expression")
        if not (isinstance(amount, exp.Literal) and not amount.is_string and str(amount.this).isdigit()) or int(amount.this) > max_offset:
            raise reject("offset_not_allowed", "OFFSET must be a whole number within the allowed range.")
    return value
