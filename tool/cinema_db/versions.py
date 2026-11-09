"""Which approved-view policy belongs to a database file: schema 2 (the runtime file), schema 3 (the reconciled IMDb layer) or schema 4 (schema 3 plus MovieLens).

The schema number is read from `build_info` with one plain read-only query BEFORE the guarded connection opens (never from anything the model controls).
The guarded connection then verifies the chosen policy against the file, so a wrong choice fails at start, not at query time.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .approved_views import POLICY as POLICY_V2
from .policy import Policy

SCHEMA_V3_VIEW = "v_work_status"  # present in every schema-3 policy and in no schema-2 one


def schema_version_of(path: str | Path) -> int:
    """4 or 3 if the file declares schema 4 or 3, else 2 (also for a missing or unreadable file: the guarded open reports that)."""
    try:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            row = conn.execute("SELECT value FROM build_info WHERE key = 'schema_version'").fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return 2
    return int(row[0]) if row and str(row[0]) in ("3", "4") else 2


def policy_for_version(version: int) -> Policy:
    if version >= 4:
        from .approved_views_v4 import POLICY as POLICY_V4

        return POLICY_V4
    if version >= 3:
        from .approved_views_v3 import POLICY as POLICY_V3

        return POLICY_V3
    return POLICY_V2


def schema_of_policy(policy: Policy) -> int:
    """The feature level of the tool: 3 for every policy with the v3 views (schema 4 adds MovieLens: see `has_movielens`)."""
    return 3 if SCHEMA_V3_VIEW in policy.view_names else 2


def has_movielens(policy: Policy) -> bool:
    return "v_ml_movie" in policy.view_names
