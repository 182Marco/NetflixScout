"""`series_rag_search`: dense search over the TV-series collection. No HTTP to a third party (Qdrant on this machine, OpenAI SDK for the
parser, the embedding and the optional reorder), so there are no `calls` in the trace. Read only: the collection is never written."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import ValidationError

from turn import (
    OUTCOME_EMPTY,
    OUTCOME_ERROR,
    OUTCOME_OK,
    RESULT_FOLLOW_UP,
    TOOL_PARAM_TURN_ID,
    TOOL_PARAM_TURN_LANGUAGE,
    tool_outcome,
)

from . import retrieval as R
from .config import SeriesRagConfig
from .models import SeriesRagToolInput, describe_validation_errors
from .trace import build_series_rag_trace

SERIES_RAG_TOOL_NAME = "series_rag_search"
LISTING_MAX = 60

_DESCRIPTION = (
    "Semantic search over about 100,000 TV records from the Italian Wikipedia: series (including miniseries, anime and animated series), seasons, single "
    "EPISODES with their plots, and TV movies. Use it to recommend or find TV series by plot, theme, atmosphere or setting, 'series like X', to find an "
    "episode from a scene or event (with or without naming the series), the plot of a season, or a TV movie. "
    "Write the user's whole request in `query`. Not for structured facts or LISTS of episodes (seasons count, episode lists and numbering, air dates, next episode, cast, network: tvmaze_search), streaming, "
    "trailers, ratings, trending or new releases (tmdb_search), films (rag_search)."
)


def planner_schema() -> dict[str, Any]:
    schema = SeriesRagToolInput.model_json_schema()
    schema.pop("description", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


class _Usage:
    """Tokens of the calls made inside one run, by stage."""

    def __init__(self) -> None:
        self.tokens: dict[str, dict[str, int]] = {}
        self.ms: dict[str, int] = {}

    def record(self, stage: str, usage: Any) -> None:
        d = self.tokens.setdefault(stage, {"input": 0, "output": 0, "total": 0, "calls": 0})
        d["calls"] += 1
        if usage is None:
            return
        d["input"] += int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None) or 0)
        d["output"] += int(getattr(usage, "output_tokens", None) or 0)
        d["total"] += int(getattr(usage, "total_tokens", None) or 0)

    def timed(self, stage: str, fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.ms[stage] = self.ms.get(stage, 0) + round((time.perf_counter() - t0) * 1000)
        return wrapper


Factories = Callable[[SeriesRagConfig, _Usage], tuple[Callable, Callable, Callable | None]]


def _openai_factories(config: SeriesRagConfig, usage: _Usage):
    from openai import OpenAI
    client = OpenAI(max_retries=2, timeout=60)
    embed = R.make_embed(config.embedding_model, config.embedding_dimensions, client=client, on_usage=usage.record)
    parse = R.make_parse(config.parser_model, None, client=client, on_usage=usage.record)
    reorder = R.make_reorder(config.rerank_model, "none", config.rerank_plot_chars, client=client, on_usage=usage.record) if config.rerank_enabled else None
    return embed, parse, reorder


def _view(item: R.Item, n: int, *, plot_chars: int, listing: bool, with_imdb_id: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {"n": n, "imdb_id": item.imdb_id if with_imdb_id else None, "level": item.entity_type, "title": item.title, "year": item.year, "subtype": item.subtype}
    if item.entity_type in ("episode", "season"):
        d.update(series=item.series_title, season=item.season_number)
        if item.entity_type == "episode":
            d["episode"] = item.episode_number
    if not listing:
        d["countries"] = item.country[:3]
        d["genres"] = item.genres[:4]
        d["plot"] = item.text[:plot_chars]
    if not item.default_search_eligible:
        d["mixed_manga_and_anime_page"] = True
    return {k: v for k, v in d.items() if v not in (None, [], "")}


def _follow_up(reason: str, summary: str) -> dict[str, Any]:
    return {"available": True, "reasons": [reason], "summary": summary}


@dataclass(kw_only=True)
class SeriesRagTool:
    config: SeriesRagConfig
    name: str = SERIES_RAG_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=planner_schema)
    index: R.SeriesIndex | None = None
    factories: Factories = _openai_factories
    expose_imdb_id: bool = False  # integrated configuration: the planner may pass a series' imdb_id to cinema_sql (set by `build_app`)

    def _index(self) -> R.SeriesIndex:
        if self.index is None:
            self.index = R.SeriesIndex(url=self.config.url, collection=self.config.collection)
        return self.index

    def count(self) -> int:
        return self._index().count()

    def run(self, *, query: str, params: dict[str, Any] | None = None, conversation_history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        arguments = dict(params or {})
        arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)
        arguments.pop(TOOL_PARAM_TURN_ID, None)
        # The user's standalone query drives the search; the planner's `arguments.query` is only a hint for the parser (as in the film index).
        hint = str(arguments.get("query") or "").strip()
        arguments["query"] = query or hint
        try:
            request = SeriesRagToolInput.model_validate(arguments)
        except ValidationError as exc:
            return self._failure(query, "invalid_request", errors=describe_validation_errors(exc))
        text = request.query if not hint or hint == request.query else f"{request.query}\n\nPlanner rewrite: {hint}"
        usage = _Usage()
        notes: dict[str, Any] = {}
        t0 = time.perf_counter()
        try:
            embed, parse, reorder = self.factories(self.config, usage)
            embed, parse = usage.timed("embedding", embed), usage.timed("parser", parse)
            reorder = usage.timed("reorder", reorder) if reorder else None
            try:
                signals = parse(text)
            except Exception as exc:  # noqa: BLE001  (the plain request is searched with no exclusions, and the answer is told)
                signals, notes["parser_failed"] = R.fallback(request.query), type(exc).__name__
            k = request.k_final or signals.requested_count or self.config.k_final
            k = max(1, min(int(k), 10))
            settings = R.Settings(pool=self.config.pool, penalty_lambda=self.config.penalty_lambda, rerank_pool=self.config.rerank_pool)
            t_search = time.perf_counter()
            out = R.search(self._index(), embed, signals, k=k, settings=settings, reorder=reorder, request=request.query)
        except Exception as exc:  # noqa: BLE001  (Qdrant down, collection missing, OpenAI unreachable: an error the answer can state)
            return self._failure(request.query, "series_rag_unavailable", detail=type(exc).__name__)
        total_ms = round((time.perf_counter() - t0) * 1000)
        timings = {"total": total_ms, "search_and_reorder": round((time.perf_counter() - t_search) * 1000), **usage.ms}
        notes.update(out.notes)
        listing = bool(notes.get("listing"))
        items = [_view(it, i, plot_chars=self.config.plot_chars_to_answer, listing=listing, with_imdb_id=self.expose_imdb_id) for i, it in enumerate(out.items, start=1)]
        trace_items = [{"n": i, "level": it.entity_type, "title": it.title, "label": it.label(), "year": it.year, "url": it.url,
                        "score": round(it.score, 4), "mixed_manga_and_anime_page": (not it.default_search_eligible) or None}
                       for i, it in enumerate(out.items, start=1)]
        engine = "listing" if listing else "title" if notes.get("title_match") else "llm_reorder" if notes.get("reordered") else "dense"
        if items:
            status, outcome, reason = "ok", tool_outcome(OUTCOME_OK), None
        else:
            reason = "series_not_in_index" if "series_not_in_index" in notes else "no_match"
            status, outcome = "empty", tool_outcome(OUTCOME_EMPTY, reason)
        public_notes = {key: value for key, value in notes.items() if key != "listing"}
        result: dict[str, Any] = {
            "query": request.query,
            "chunks": [],
            "outcome": outcome,
            "metadata": {"series_rag": {"status": status, "level": signals.level, "listing": listing, "count": len(items), "items": items,
                                          "notes": {k_: v_ for k_, v_ in public_notes.items() if k_ != "dropped_rare_terms"}}},
            "trace": build_series_rag_trace(level=signals.level, query=request.query, items=trace_items, notes=public_notes, status=status,
                                              reason=reason, engine=engine,
                                              signals={k_: v for k_, v in signals.model_dump().items() if v not in (None, [], False, "")},
                                              timings=timings),
            "usage": {"tokens": usage.tokens, "timings_ms": timings},
        }
        if not items:
            result[RESULT_FOLLOW_UP] = _follow_up(reason, (
                "series_rag_search found nothing in its catalogue of Italian Wikipedia TV pages"
                + (f" for the series «{notes.get('series_not_in_index')}»" if reason == "series_not_in_index" else "")
                + ". One step with tmdb_search (kind tv) or tvmaze_search (a named series) can still answer; do not search this tool again."))
        return result

    @staticmethod
    def _failure(query: str, error: str, **details: Any) -> dict[str, Any]:
        return {
            "query": query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_ERROR, error),
            "metadata": {"series_rag": {"status": "error", "error": error, **details}},
            "trace": [],
            RESULT_FOLLOW_UP: _follow_up(error, "series_rag_search could not run. One step with tmdb_search (kind tv) or tvmaze_search can still answer."),
        }
