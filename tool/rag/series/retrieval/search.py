"""The dense search: filters decided by the request and evaluated by Qdrant, exclusions as a penalty, optional LLM reorder. Pure functions around `embed`/`parse`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from qdrant_client import models

from .index import Item, SeriesIndex, _eq
from .signals import SeriesSignals, fallback
from .text import base_title_norm, norm, unit, verified_rare_terms

Embed = Callable[[list[str]], np.ndarray]


@dataclass
class Settings:
    pool: int = 50
    penalty_lambda: float = 0.5
    rerank_pool: int = 40


@dataclass
class Output:
    items: list[Item]
    pool: list[Item]
    notes: dict
    series_ids: list[str] | None = None
    wide: list[tuple[Item, float]] = field(default_factory=list)       # K-wide: the candidates after exclusions and penalty, with their score, before the reorder
    reranked: list[Item] = field(default_factory=list)                  # the head sent to the reorder, in the order the model decided


def _resolve_series(index: SeriesIndex, sg: SeriesSignals) -> tuple[list[str] | None, dict]:
    names = [n for n in (sg.series_title, sg.series_title_original) if n]
    if not names or sg.level not in ("season", "episode"):
        return None, {}
    found = {}
    for n in names:
        for it in index.find_titles(n, levels=("series",)):
            found[it.record_id] = it
    if not found:
        return [], {"series_not_in_index": names[0]}
    ids = list(found)
    note = {"series_resolved": [{"record_id": i.record_id, "title": i.title, "year": i.year} for i in found.values()]}
    return ids, note


Reorder = Callable[[str, SeriesSignals, list[Item]], list[int]]


def search(index: SeriesIndex, embed: Embed, sg: SeriesSignals, *, k: int, settings: Settings = Settings(), reorder: Reorder | None = None,
           request: str = "") -> Output:
    notes: dict = {}
    if sg.rare_terms and request:
        kept_terms, dropped_terms = verified_rare_terms(sg.rare_terms, request)
        if dropped_terms:         # not words of the user's request (e.g. a translation): never a hard filter; the caller's signals stay as the parser wrote them
            sg = sg.model_copy(update={"rare_terms": kept_terms})
            notes["dropped_rare_terms"] = dropped_terms
    named = [t for t in (sg.series_title, sg.series_title_original) if t]
    if named and sg.level in ("series", "tv_movie"):
        # the request names the work itself: an exact title lookup (decision 8b: this is also how a manga+anime page is reached)
        hits = {}
        for t in named:
            for it in index.find_titles(t, levels=(sg.level,)):
                hits[it.record_id] = it
        if hits:
            items = sorted(hits.values(), key=lambda i: (not i.default_search_eligible, i.year or 9999))
            for it in items:
                it.score = 1.0
            notes["title_match"] = True
            if len(items) > 1:
                notes["ambiguous_title"] = [{"title": i.title, "year": i.year} for i in items]
            if any(not i.default_search_eligible for i in items):
                notes["mixed_media_pages"] = [i.title for i in items if not i.default_search_eligible]
            return Output(items[:k], items, notes, None)
        notes["series_not_in_index"] = named[0]       # no wrong guess: a named work the catalogue does not have returns nothing
        return Output([], [], notes, [])
    series_ids, n = _resolve_series(index, sg)
    notes.update(n)
    if series_ids == []:                       # a named series that the catalogue does not have: no wrong guess
        return Output([], [], notes, [])
    if sg.list_children and series_ids and sg.level in ("season", "episode"):     # navigation, no vectors: the children in their order
        kids = [it for sid in series_ids for it in (index.seasons_of(sid) if sg.level == "season" else index.episodes_of(sid, sg.season_number))]
        for it in kids:
            it.score = 1.0
        notes["listing"] = True
        return Output(kids[:max(k, 60)], kids, notes, series_ids)
    texts = [sg.positive_it, *sg.avoid_descriptions_it]
    vecs = embed(texts)
    P = unit(vecs[0])
    negatives = [unit(v) for v in vecs[1:]]
    if sg.like_titles:                          # a cited series that exists steers the search with its own vector
        pos = [P]
        for t in sg.like_titles:
            hit = index.find_titles(t, levels=("series",), eligible_only=True)
            if hit:
                got = index.lookup(models.Filter(must=[_eq("record_id", hit[0].record_id)]), limit=1, vectors=True)
                if got and got[0].vector is not None:
                    pos.append(got[0].vector)
                    notes.setdefault("references_resolved", []).append(hit[0].title)
        P = unit(np.mean(pos, axis=0))
    raw = index.query(P, limit=settings.pool, flt=index.positive_filter(sg, series_ids=series_ids))
    for it in raw:
        it.score = float(it.vector @ P)
    cited = {norm(t) for t in [*sg.avoid_titles, *sg.like_titles] if norm(t)}
    kept = [it for it in raw if not ({norm(it.title), base_title_norm(it.title), norm(it.series_title), base_title_norm(it.series_title)} & cited)]
    if negatives and kept:
        M = np.stack([it.vector for it in kept])
        sc = M @ P - settings.penalty_lambda * np.max(M @ np.stack(negatives).T, axis=1)
        order = np.argsort(-sc)
        kept = [kept[i] for i in order]
        for i, it in zip(order, kept):
            it.score = float(sc[i])
    if sg.contradictory:
        notes["contradiction"] = sg.contradiction_note or True
    if not kept and raw == []:
        notes["no_match_for_the_filters"] = True
    wide = [(it, float(it.score)) for it in kept]
    reranked: list[Item] = []
    if reorder is not None and len(kept) > 1:
        head = kept[:settings.rerank_pool]
        try:
            order = reorder(request or sg.positive_it, sg, head)
            seen, ranked = set(), []
            for i in order:
                if 0 <= i < len(head) and i not in seen:
                    seen.add(i); ranked.append(head[i])
            kept = ranked + [head[i] for i in range(len(head)) if i not in seen] + kept[len(head):]
            reranked = kept[:len(head)]
            notes["reordered"] = True
        except Exception:  # noqa: BLE001  (an improvement, not a requirement: the penalty order stays)
            notes["reorder_failed"] = True
    return Output(kept[:k], kept, notes, series_ids, wide=wide, reranked=reranked)



def run(question: str, *, index: SeriesIndex, embed: Embed, parse, k: int = 5, settings: Settings = Settings(),
        reorder: Reorder | None = None) -> Output:
    """The whole path: parse (failure → the plain request is searched, noted), search, optional LLM reorder (recommended: `make_reorder()`;
    paired A/B on 35 questions, same signals and judge: valid 0.475 -> 0.726, better on 20, worse on 1), return."""
    notes = {}
    try:
        sg = parse(question)
    except Exception as exc:  # noqa: BLE001
        sg, notes["parser_failed"] = fallback(question), type(exc).__name__
    out = search(index, embed, sg, k=k, settings=settings, reorder=reorder, request=question)
    out.notes.update(notes)
    return out
