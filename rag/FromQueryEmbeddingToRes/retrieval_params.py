from __future__ import annotations

from typing import Any

# Retrieval settings the planner may set for one call; everything else stays in the configuration.
TUNABLE = ("k_finale",)


def resolve_retrieval(
    defaults: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge the planner's choices into the configured retrieval settings.

    Returns `(effective, overridden)`: the settings to run with (a copy: `defaults` is never
    changed) and the subset that differs from the defaults. Values outside
    `defaults["limits"]` are clamped, unusable ones fall back to the default, and the
    pools stay coherent: `k_finale <= k_largo <= fetch_k`.
    """
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
    if effective.get("k_largo") is not None and effective.get("k_finale") is not None:
        effective["k_largo"] = max(effective["k_largo"], effective["k_finale"])
    if effective.get("fetch_k") is not None and effective.get("k_largo") is not None:
        effective["fetch_k"] = max(effective["fetch_k"], effective["k_largo"])
    overridden = {k: effective[k] for k in TUNABLE if effective.get(k) != defaults.get(k)}
    return effective, overridden
