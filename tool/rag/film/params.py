"""The one retrieval setting the planner may choose per call: how many films (`k_finale`), clamped to the configured limits."""
from __future__ import annotations

from typing import Any


def resolve_retrieval(defaults: dict[str, Any], overrides: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge the planner's `k_finale` into the configured retrieval settings. Returns `(effective, overridden)`: a copy to run with (`defaults` is never
    changed) and the subset that differs from the defaults. Out-of-range values are clamped to `defaults["limits"]["k_finale"]`, unusable ones are ignored."""
    limits = defaults.get("limits") or {}
    effective = {k: v for k, v in defaults.items() if k != "limits"}
    raw = (overrides or {}).get("k_finale")
    if raw is not None and not isinstance(raw, bool):
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError):
            value = None
        if value is not None:
            bounds = limits.get("k_finale") or {}
            if bounds.get("min") is not None:
                value = max(value, bounds["min"])
            if bounds.get("max") is not None:
                value = min(value, bounds["max"])
            effective["k_finale"] = value
    overridden = {k: effective[k] for k in ("k_finale",) if effective.get(k) != defaults.get(k)}
    return effective, overridden
