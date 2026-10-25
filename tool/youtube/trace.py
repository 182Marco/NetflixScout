"""Trace of a YouTube run: calls made, searches, categories not searched and videos kept.

Kept outside `metadata` (which goes into the LLM prompt): the presenters show the video
titles, channels and URLs exactly as returned by the API, with the YouTube attribution,
never left to the model. The search `q` is listed for debugging, like the SQL of `db_query`;
the key never appears (calls are display URLs). `dropped` lists the titles the relevance
filter removed, with the reason, to spot false negatives in tests and evaluations; the
presenters do not print it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from turn import STEP_YOUTUBE_CALLS

from .models import KindOutcome

YOUTUBE_CALLS_TITLE = "YouTube"


def build_youtube_trace(
    calls: list[str],
    outcomes: list[KindOutcome],
    queries: dict[str, str],
    *,
    hints: list[str] | None = None,
    quota_paused_until: float | None = None,
    dropped: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    searches = [
        {
            "kind": outcome.kind.value,
            "q": queries.get(outcome.kind.value),
            "result": outcome.result,
            "error": outcome.error,
            "returned": outcome.returned,
            "kept": len(outcome.hits),
            "filtered_out": dict(outcome.filtered_out),
        }
        for outcome in outcomes
        if outcome.status == "searched"
    ]
    data: dict[str, Any] = {
        "calls": list(calls),
        "searches": searches,
        "not_searched": [
            {"kind": outcome.kind.value, "reason": outcome.reason}
            for outcome in outcomes
            if outcome.status == "not_searched"
        ],
        "videos": [
            {
                "kind": outcome.kind.value,
                "title": hit.title,
                "channel": hit.channel,
                "url": hit.url,
                "published_at": hit.published_at,
                "description_excerpt": hit.description_excerpt,
                "notes": list(hit.notes),
                "verification": hit.verification,
            }
            for outcome in outcomes
            for hit in outcome.hits
        ],
        "dropped": [dict(row) for row in dropped or []],
    }
    if hints:
        data["hints"] = list(hints)
    if quota_paused_until is not None:
        data["quota_paused_until"] = datetime.fromtimestamp(quota_paused_until, timezone.utc).isoformat()
    return [{"kind": STEP_YOUTUBE_CALLS, "title": YOUTUBE_CALLS_TITLE, "data": data}]
