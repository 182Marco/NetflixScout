"""The search itself: references, exclusions, penalty, optional LLM reorder. Pure functions over a `FilmIndex` and two callables
(`embed`, `reorder`), so every step is testable without the network."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ...shared.text import norm, unit
from .index import Film, FilmIndex
from .models import Signals

Embed = Callable[[list[str]], np.ndarray]
# (request, signals, cited titles, candidates) -> candidate indices, best first
Reorder = Callable[[str, Signals, list[str], list[Film]], list[int]]


@dataclass
class Settings:
    pool: int = 50
    penalty_lambda: float = 0.5
    max_genre_share: float = 0.08
    max_avoid_genres: int = 3
    rerank_pool: int = 40


@dataclass
class Context:
    signals: Signals
    P: np.ndarray
    negatives: list[np.ndarray]
    cited: list[dict]
    franchise_ids: set[str]
    franchise_names: list[str]
    avoid_genre_terms: list[str]
    dropped_genre_terms: list[dict] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)


@dataclass
class Output:
    films: list[Film]
    pool: list[Film]                    # the wide candidate list in the order of the final scoring, before the reorder
    reordered: list[Film]               # the candidates the LLM reordered (empty without reorder)
    context: Context
    engine: str


def build_context(index: FilmIndex, embed: Embed, s: Signals, settings: Settings) -> Context:
    texts = [s.positive_it, *s.avoid_descriptions_it]
    vecs = embed(texts)
    positives, negatives = [vecs[0]], list(vecs[1:])
    cited, refs, franchise_ids, pending = [], [], set(), []
    for role, titles in (("like", s.like_titles), ("avoid", s.avoid_titles)):
        for r in titles:
            f = index.resolve(r.title_it, r.title_original, r.year)
            cited.append({"keys": {norm(r.title_it), norm(r.title_original)} - {""}, "year": r.year, "point_id": f.point_id if f else None,
                          "title": r.title_original or r.title_it})
            entry = {"title": r.title_original or r.title_it, "year": r.year, "role": role,
                     "status": "resolved" if f else "described", "source": "index" if f else "description",
                     "matched_title": f.title if f else None}
            refs.append(entry)
            if f is not None:
                (positives if role == "like" else negatives).append(unit(f.vector))
                franchise_ids |= set(f.franchise_ids)
            else:
                pending.append((role, r.summary_it))
    if pending:
        for (role, _), v in zip(pending, embed([t for _, t in pending])):
            (positives if role == "like" else negatives).append(unit(v))
    for name in s.avoid_franchise_names:
        f = index.resolve(name, name, None)
        if f:
            franchise_ids |= set(f.franchise_ids)
    P = unit(np.mean([unit(v) for v in positives], axis=0))
    keep = {norm(g) for g in s.keep_genres_it}
    terms, dropped = [], []
    for t in s.avoid_genres_it:
        tn = norm(t)
        if not tn or any(tn in k or k in tn for k in keep):
            dropped.append({"term": t, "reason": "also_wanted"})
        elif len(terms) >= settings.max_avoid_genres:
            dropped.append({"term": t, "reason": "too_many"})
        elif index.genre_share(t) > settings.max_genre_share:
            dropped.append({"term": t, "reason": "too_wide"})
        else:
            terms.append(t)
    return Context(s, P, negatives, cited, franchise_ids, [n for n in s.avoid_franchise_names if norm(n)], terms, dropped, refs)


def is_cited(f: Film, ctx: Context) -> bool:
    keys = {norm(f.title), norm(f.original_title)} - {""}
    for c in ctx.cited:
        if c["point_id"] == f.point_id or (keys & c["keys"] and (not c["year"] or not f.year or abs(f.year - c["year"]) <= 1)):
            return True
    return False


def franchise_hit(f: Film, ctx: Context) -> bool:
    if set(f.franchise_ids) & ctx.franchise_ids:
        return True
    titles = [t for t in (norm(f.title), norm(f.original_title)) if t]
    for n in ctx.franchise_names:
        words = norm(n).split()
        pat = r"\b" + r"\s+".join(w + ("s?" if i == len(words) - 1 else "") for i, w in enumerate(words)) + r"\b"
        if any(re.search(pat, t) for t in titles):
            return True
    return False


def genre_or_format_hit(f: Film, ctx: Context) -> bool:
    gs = [norm(g) for g in f.genres]
    if any(norm(t) in g for t in ctx.avoid_genre_terms for g in gs):
        return True
    bad = set(ctx.signals.avoid_formats)
    return bool(bad and f.work_format and (f.work_format in bad or ("series" in bad and f.work_format == "tv_related")))


def penalised(pool: list[Film], ctx: Context, lam: float) -> list[Film]:
    if not ctx.negatives or not pool:
        return pool
    M = np.stack([unit(f.vector) for f in pool])
    sc = M @ ctx.P - lam * np.max(M @ np.stack(ctx.negatives).T, axis=1)
    out = []
    for i in np.argsort(-sc):
        pool[i].score = float(sc[i])
        out.append(pool[i])
    return out


def search(index: FilmIndex, embed: Embed, signals: Signals, request: str, *, k: int, settings: Settings,
           reorder: Reorder | None = None) -> Output:
    ctx = build_context(index, embed, signals, settings)
    raw = index.search(ctx.P, limit=settings.pool, flt=index.positive_filter(signals))
    for f in raw:       # the retrieval similarity, kept for the trace
        f.score = float(f.vector @ ctx.P)
    kept = [f for f in raw if not is_cited(f, ctx) and not franchise_hit(f, ctx) and not genre_or_format_hit(f, ctx)]
    pool = penalised(kept, ctx, settings.penalty_lambda)
    if reorder is None or len(pool) <= 1:
        return Output(pool[:k], pool, [], ctx, "penalty")
    head = pool[:settings.rerank_pool]
    try:
        order = reorder(request, signals, [c["title"] for c in ctx.cited], head)
    except Exception:  # noqa: BLE001  (the LLM is an improvement, not a requirement: keep the penalty order)
        return Output(pool[:k], pool, [], ctx, "penalty_after_error")
    seen, ranked = set(), []
    for i in order:
        if 0 <= i < len(head) and i not in seen:
            seen.add(i)
            ranked.append(head[i])
    ranked += [head[i] for i in range(len(head)) if i not in seen]
    return Output(ranked[:k], pool, ranked, ctx, "llm_request")
