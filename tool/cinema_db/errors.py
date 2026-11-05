"""Typed errors. The message names the rule that failed; it never repeats the SQL or SQLite's own text."""
from __future__ import annotations


class CinemaSqlError(Exception):
    """Base class: `code` is a stable identifier safe to show to the planner."""

    code = "error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or (code or self.code))
        if code:
            self.code = code


class SqlRejected(CinemaSqlError):
    """The statement was refused before execution (validator)."""

    code = "rejected"


class SqlTimeout(CinemaSqlError):
    code = "timeout"


class SqlPlanRejected(CinemaSqlError):
    """The query plan scans a protected table without a bound."""

    code = "plan_rejected"


class SqlExecutionFailed(CinemaSqlError):
    """SQLite refused to run the statement (authorizer or runtime error); the engine's text is not exposed."""

    code = "execution_failed"


class PolicyMismatch(CinemaSqlError):
    """The policy does not describe the database that was opened."""

    code = "policy_mismatch"


class DatabaseMissing(CinemaSqlError):
    code = "db_missing"
