"""Spellings of the same country in the `country` payload of `wikipedia_series_it_v1`.

The catalogue was filled from many Wikipedia infoboxes, so one country appears under several spellings ("Stati Uniti d'America" 3.758 series, "Stati Uniti" 599,
"USA" 356, "Usa" 45 …). Qdrant matches the value exactly, so a request for American series that the parser writes as "Stati Uniti" saw only ~14 % of them.
The groups below list only spellings that exist in the payload (measured on the collection, FASE 19B) and that name the same country; nothing is inferred.

"Gran Bretagna" (42 series) is deliberately NOT grouped with "Regno Unito": Great Britain is geographically narrower (no Northern Ireland) and the data cannot prove the two are used
as the same country, so a request for "Regno Unito" does not reach it (FASE 19D).
"""
from __future__ import annotations

SPELLINGS: tuple[tuple[str, ...], ...] = (
    ("Stati Uniti", "Stati Uniti d'America", "Stati uniti", "Stati uniti d'America", "USA", "Usa"),
    ("Regno Unito", "Regno unito", "UK"),
    ("Thailandia", "Tailandia"),
    ("Malaysia", "Malesia"),
)
_GROUP_OF = {name.casefold(): group for group in SPELLINGS for name in group}   # case only: punctuation is not stripped, so a dirty value never joins a group


def country_variants(names: list[str]) -> list[str]:
    """The requested countries plus every payload spelling of the same country, each once, requested names first."""
    out: list[str] = []
    for name in names:
        for spelling in (name, *_GROUP_OF.get(name.strip().casefold(), ())):
            if spelling not in out:
                out.append(spelling)
    return out
