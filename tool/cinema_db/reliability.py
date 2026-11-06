"""What the local answer can be trusted for, field by field, and where one online step would add information (pure functions, no I/O).

Four states, never a score. They come from facts of the result, not from a judgement:
- `verified`: the field is recorded with a provenance and nothing in the result says it is incomplete or ambiguous (an entity found by id or by an exact,
  unique name; a relation stored as such; a credit role the source states by name);
- `partial`: recorded, but the catalogue is known to hold only some of it (credits of recent years, awards recorded for some works, seasons that exist in the
  catalogue); what is shown is true as recorded, the complete list may be longer;
- `uncertain`: recorded, but what it means is not settled by the data (the `writer` role can list the author of the source material; "part of a series" can be a
  list; `is based on` does not tell a remake from an adaptation; episode rows can repeat or lack numbers);
- `absent`: the database holds nothing for it (no billing order is recorded for any cast, no result was found). `absent` never says the thing does not exist.

`gaps` names, for the fields that are not `verified`, the one online tool that could fill them and WHEN that is worth a step. The orchestrator offers the planner
a further step only for a gap the request asks about (`wants`), so nothing is checked "just in case".
"""
from __future__ import annotations

import re
from typing import Any

VERIFIED, PARTIAL, UNCERTAIN, ABSENT = "verified", "partial", "uncertain", "absent"

# Words that say a request is about the field a gap concerns (it/en/de/fr/es). The tool does not answer from them: they only decide whether to OFFER the planner
# a further step; the planner still judges, on the request, whether it adds anything.
LEAD_WORDS = re.compile(r"protagonist|principal|main cast|lead|leading|star(s|ring)?\b|top[- ]billed|hauptdarsteller|hauptrolle|acteurs? principa|actores principales|interpret", re.I)
REMAKE_WORDS = re.compile(r"remake|reboot|sequel|prequel|seguito|rifacimento|adattament|adaptation|ispirat|fortsetzung|vorgeschichte", re.I)
EPISODE_WORDS = re.compile(r"episod|puntat|episoden|folgen|épisode|capítulo", re.I)


def _field(state: str, why: str) -> dict[str, str]:
    return {"state": state, "why": why}


def _gap(name: str, tool: str, fills: str, wants: re.Pattern[str] | None = None) -> dict[str, Any]:
    return {"field": name, "tool": tool, "fills": fills, "wants": wants}


def assess(operation: str, *, status: str, reason: str | None, data: dict[str, Any], total: int | None, shown: int, truncated: bool,
           subject: dict[str, Any] | None) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    """(fields, gaps) of one result. `fields` goes to the model and the trace; `gaps` is for `offer`."""
    fields: dict[str, dict[str, str]] = {}
    gaps: list[dict[str, Any]] = []
    if status == "ambiguous":
        return {"identity": _field(UNCERTAIN, "several entities with this name")}, gaps
    if status == "unverified":
        return {"identity": _field(UNCERTAIN, "only similar names found")}, gaps
    if status == "not_found":
        return {"identity": _field(ABSENT, "no entity with this name in the catalogue")}, gaps
    if status == "empty":
        fields["result"] = _field(ABSENT, reason or "nothing recorded")
        return fields, gaps
    if subject:
        fields["identity"] = _field(VERIFIED, "one entity, found by identifier or by an exact unique name")
    if operation == "cast":
        fields["members"] = _field(PARTIAL, "credits are Wikidata statements; the catalogue may hold only some of the cast")
        fields["billing_order"] = _field(ABSENT, "the order of the credits is not recorded for any cast")
        gaps.append(_gap("billing_order", "tmdb_search", "which actors lead (credits with their order)", LEAD_WORDS))
        people = data.get("cast") or []
        if people:
            named = sum(1 for p in people if p.get("character"))
            fields["characters"] = _field(VERIFIED if named == len(people) else PARTIAL, f"{named} of {len(people)} listed credits name the character")
    elif operation == "crew":
        roles = {c.get("role") for c in data.get("crew") or []}
        fields["credits"] = _field(PARTIAL, "credits are Wikidata statements; the catalogue may hold only some")
        if "writer" in roles:
            fields["writer"] = _field(UNCERTAIN, "the writer role can also list the authors of the source material or the creators of a character")
    elif operation == "awards":
        if subject and subject.get("kind") == "person":
            fields["results"] = _field(PARTIAL, "a result is attached to a person only when the source names the nominee; nominations are recorded for some works only")
            gaps.append(_gap("results", "wikipedia_search", "the person's complete list of nominations and wins (one page, not the whole work again)"))
        else:
            fields["results"] = _field(PARTIAL, "awards are Wikidata statements recorded for some works; nominations are often missing")
    elif operation == "series":
        seasons = data.get("seasons")
        if seasons is not None:
            fields["seasons"] = _field(PARTIAL, "only seasons that exist in the catalogue are listed")
            exact = all(s["episodes"] == s["numbered_episodes"] for s in seasons) if seasons else False
            fields["episode_counts"] = _field(PARTIAL if exact else UNCERTAIN,
                                              "every episode row has a number" if exact else "some episode rows have no number or may repeat an episode: counts can be off")
            fields["numbering"] = _field(VERIFIED if exact else PARTIAL, "episode numbers come from the season tables; a missing number is never inferred")
            gaps.append(_gap("episode_counts", "tvmaze_search", "the real number of episodes per season", EPISODE_WORDS))
        else:
            episodes = data.get("episodes") or []
            numbered = all(e.get("episode_number") is not None for e in episodes)
            fields["episodes"] = _field(PARTIAL, "episodes exist only where the catalogue has them")
            fields["numbering"] = _field(VERIFIED if numbered else PARTIAL, "all listed episodes carry a number" if numbered else "some episodes have no number in the source")
            gaps.append(_gap("episodes", "tvmaze_search", "the complete list with numbering and air dates", EPISODE_WORDS))
    elif operation == "relations":
        fields["links"] = _field(VERIFIED, "the relations are stored as recorded")
        natures = {r.get("nature") for r in data.get("relations") or []}
        if natures and natures <= {"adaptation_of_non_screen_work", "adapted_into_screen_work"}:
            fields["relation_type"] = _field(VERIFIED, "the source is not a film or a series (a novel, a comic, a play, a game): the work is an adaptation of it")
        else:
            fields["relation_type"] = _field(UNCERTAIN, "a film or series based on another film or series can be a remake, a reboot or a derived work (not told apart); 'follows' is not 'sequel'")
            gaps.append(_gap("relation_type", "wikipedia_search", "whether a related work is a remake, adaptation, sequel or prequel", REMAKE_WORDS))
    elif operation == "franchise":
        fields["membership"] = _field(UNCERTAIN, "'part of the series' can be a saga but also a list or collection, and a film of a saga may be missing")
    elif operation in {"filmography", "collaborations", "companies"}:
        fields["list"] = _field(PARTIAL, "credits are Wikidata statements; the catalogue is incomplete, especially after 2019")
        if truncated:
            fields["list"] = _field(PARTIAL, "the list was cut at the limit shown")
    elif operation == "work_card":
        fields["writers"] = _field(UNCERTAIN, "the writer role can also list the authors of the source material")
        fields["composers"] = _field(PARTIAL, "credits are Wikidata statements")
        fields["money"] = _field(PARTIAL if data.get("money") else ABSENT, "recorded in the currency given, never converted" if data.get("money") else "no budget or box office recorded")
    elif operation == "sql":
        fields["rows"] = _field(PARTIAL if truncated else VERIFIED, "the rows returned by the query" + (" cut at the limit" if truncated else ""))
    return fields, gaps


def offer(gaps: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """The gaps worth a further step: the request asks about the field (`wants` matches), or the gap has no pattern because it is always in play
    (a person's awards are always incomplete: whether to complete them is for the planner to say from the request)."""
    return [g for g in gaps if g["wants"] is None or g["wants"].search(query or "")]


def follow_up_summary(operation: str, offered: list[dict[str, Any]]) -> str:
    lines = "; ".join(f"{g['field']} -> {g['tool']} for {g['fills']}" for g in offered)
    return (f"cinema_sql {operation}: ok, with fields that are not fully verified ({lines}). Take ONE further step only if the user's request needs that information and "
            "the local result does not already answer it; otherwise the local result is enough and the answer can be written. Do not ask the external tool for what the local "
            "result already contains, and reuse the ids and names it returned.")
