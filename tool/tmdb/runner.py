"""Run the requested operations in order, sharing one turn budget.

Failures become data (`status`, `error`) instead of exceptions, so an exhausted budget or
a 429 never breaks the turn. After the budget runs out later requests still run: they
may be fully served by the memo or the cache, which cost nothing.
"""
from __future__ import annotations

from .context import TmdbContext
from .dispatch import OPERATION_HANDLERS
from .errors import TmdbAuthError, TmdbError, TmdbUnverifiedMatch
from .models.requests import TmdbRequest
from .models.results import RequestOutcome


def run_requests(ctx: TmdbContext, requests: list[TmdbRequest]) -> list[RequestOutcome]:
    outcomes: list[RequestOutcome] = []
    unauthorized = False
    for index, request in enumerate(requests, start=1):
        if unauthorized:
            # Same credentials would be rejected again: do not spend calls on it.
            outcome = RequestOutcome(operation=request.operation.value, status="error", error=TmdbAuthError.code)
        else:
            try:
                outcome = OPERATION_HANDLERS[request.operation](ctx, request)
            except TmdbError as exc:
                unauthorized = isinstance(exc, TmdbAuthError)
                outcome = RequestOutcome(operation=request.operation.value, status="error", error=exc.code)
                if isinstance(exc, TmdbUnverifiedMatch):
                    # Unverified alternatives only: no entity is attributed to the request.
                    outcome.notes.append(exc.reason)
                    outcome.candidates = list(exc.candidates)
            else:
                if outcome.skipped_for_budget:
                    outcome.status = "partial"
        outcome.index = index
        outcomes.append(outcome)
    return outcomes


def overall_status(outcomes: list[RequestOutcome]) -> str:
    if all(outcome.status == "ok" for outcome in outcomes):
        return "ok"
    if all(outcome.status == "error" for outcome in outcomes):
        return "error"
    return "partial"
