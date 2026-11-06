"""Pure extraction of the facts the cinema database needs from ONE Wikidata entity (the JSON of wbgetentities).

No I/O. Deprecated statements are ignored; preferred rank wins over normal (same rule as the film project's enrichment).
Values are kept as the source states them (QIDs, ISO-partial dates, amounts with their unit item): nothing is guessed.
"""
from __future__ import annotations

import re
from typing import Any

QID = re.compile(r"^Q[1-9]\d*$")
IMDB_TITLE = re.compile(r"^tt\d{7,9}$")

ROLE_PROPS = {
    "director": "P57", "writer": "P58", "cast": "P161", "composer": "P86", "cinematographer": "P344", "editor": "P1040",
    "producer": "P162", "production_designer": "P2554", "costume_designer": "P2515", "creator": "P170",
}
COMPANY_PROPS = {"production": "P272", "distribution": "P750", "network": "P449"}
RELATION_PROPS = {"based_on": "P144", "follows": "P155", "followed_by": "P156", "derivative": "P4969"}
FRANCHISE_PROPS = {"series": "P179", "franchise": "P8345"}
ID_PROPS = {"imdb_title": "P345", "tmdb_movie": "P4947", "tmdb_tv": "P4983", "tvdb_series": "P4835", "eidr": "P2704"}
P_GENRE, P_COUNTRY, P_LANGUAGE, P_LANGUAGE_WORK, P_DURATION = "P136", "P495", "P364", "P407", "P2047"
P_PUBLICATION, P_START, P_END, P_BOX_OFFICE, P_BUDGET = "P577", "P580", "P582", "P2142", "P2130"
P_WON, P_NOMINATED = "P166", "P1411"
UNITS_TO_MINUTES = {"Q7727": 1.0, "Q11574": 1 / 60, "Q25235": 60.0}


def statements(entity: dict, prop: str) -> list[dict]:
    live = [c for c in entity.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated" and c.get("mainsnak", {}).get("snaktype") == "value"]
    preferred = [c for c in live if c.get("rank") == "preferred"]
    return preferred or live


def _value(snak: dict) -> Any:
    return snak.get("datavalue", {}).get("value")


def item(snak: dict) -> str | None:
    v = _value(snak)
    q = v.get("id") if isinstance(v, dict) else None
    return q if isinstance(q, str) and QID.match(q) else None


def qualifier_items(statement: dict, prop: str) -> list[str]:
    return [q for s in statement.get("qualifiers", {}).get(prop, []) if s.get("snaktype") == "value" and (q := item(s))]


def qualifier_times(statement: dict, prop: str) -> list[str]:
    return [t for s in statement.get("qualifiers", {}).get(prop, []) if s.get("snaktype") == "value" and (t := iso_date(_value(s)))]


def qualifier_texts(statement: dict, prop: str) -> list[str]:
    out = []
    for s in statement.get("qualifiers", {}).get(prop, []):
        v = _value(s) if s.get("snaktype") == "value" else None
        text = v.get("text") if isinstance(v, dict) else v
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


def items(entity: dict, prop: str) -> list[str]:
    seen: list[str] = []
    for c in statements(entity, prop):
        q = item(c["mainsnak"])
        if q and q not in seen:
            seen.append(q)
    return seen


def iso_date(value: Any) -> str | None:
    """Wikidata time -> ISO partial date by its precision (9 year, 10 month, 11 day); finer or coarser precisions give None."""
    if not isinstance(value, dict) or "time" not in value:
        return None
    m = re.match(r"^[+-](\d{4,})-(\d\d)-(\d\d)T", value["time"])
    if not m or value["time"].startswith("-"):
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    precision = value.get("precision", 0)
    if len(year) != 4 or precision < 9:
        return None
    if precision == 9 or month == "00":
        return year
    if precision == 10 or day == "00":
        return f"{year}-{month}"
    return f"{year}-{month}-{day}"


def year_of(date: str | None) -> int | None:
    return int(date[:4]) if date else None


def quantity(snak: dict) -> tuple[int, str] | None:
    """(amount, unit qid) of a whole, non-negative quantity; fractional or negative amounts are not imported."""
    v = _value(snak)
    if not isinstance(v, dict) or "amount" not in v:
        return None
    unit = str(v.get("unit", "")).rsplit("/", 1)[-1]
    try:
        amount = float(v["amount"])
    except ValueError:
        return None
    if amount < 0 or amount != int(amount) or not QID.match(unit):
        return None
    return int(amount), unit


def runtime_minutes(entity: dict) -> int | None:
    for c in statements(entity, P_DURATION):
        v = _value(c["mainsnak"])
        if isinstance(v, dict) and "amount" in v:
            unit = str(v.get("unit", "")).rsplit("/", 1)[-1]
            try:
                minutes = float(v["amount"]) * UNITS_TO_MINUTES.get(unit, 0)
            except ValueError:
                continue
            if 1 <= minutes <= 3000:
                return round(minutes)
    return None


def summarize(qid: str, entity: dict) -> dict[str, Any]:
    """Compact, JSON-able facts of one entity. Keys are stable: the build and the survey both read them."""
    labels = {lang: v["value"] for lang, v in (entity.get("labels") or {}).items()}
    titles = []
    for c in statements(entity, "P1476"):
        v = _value(c["mainsnak"])
        if isinstance(v, dict) and v.get("text"):
            titles.append({"text": v["text"], "language": v.get("language")})
    ids: dict[str, list[str]] = {}
    for scheme, prop in ID_PROPS.items():
        vals = [v for c in statements(entity, prop) if isinstance(v := _value(c["mainsnak"]), str) and v.strip()]
        if scheme == "imdb_title":
            vals = [v for v in vals if IMDB_TITLE.match(v)]
        if vals:
            ids[scheme] = list(dict.fromkeys(vals))
    roles: dict[str, list[dict]] = {}
    for role, prop in ROLE_PROPS.items():
        rows = []
        for c in statements(entity, prop):
            q = item(c["mainsnak"])
            if not q:
                continue
            row: dict[str, Any] = {"person": q}
            characters = qualifier_texts(c, "P4633")
            if characters:
                row["character"] = characters[0]
            rows.append(row)
        if rows:
            roles[role] = rows
    dates = []
    for c in statements(entity, P_PUBLICATION):
        d = iso_date(_value(c["mainsnak"]))
        if d:
            dates.append({"date": d, "places": qualifier_items(c, "P291")})
    financial = []
    for kind, prop in (("box_office", P_BOX_OFFICE), ("budget", P_BUDGET)):
        for c in statements(entity, prop):
            q = quantity(c["mainsnak"])
            if q:
                financial.append({"kind": kind, "amount": q[0], "unit": q[1], "places": qualifier_items(c, "P3005"), "times": qualifier_times(c, "P585")})
    awards = []
    for outcome, prop in (("won", P_WON), ("nominated", P_NOMINATED)):
        for c in statements(entity, prop):
            award = item(c["mainsnak"])
            if award:
                awards.append({"outcome": outcome, "award": award, "ceremony": qualifier_items(c, "P805"), "nominee": qualifier_items(c, "P2453"),
                               "winner": qualifier_items(c, "P1346"), "for_work": qualifier_items(c, "P1686"), "times": qualifier_times(c, "P585")})
    sitelinks = {k: v.get("title") for k, v in (entity.get("sitelinks") or {}).items()}
    return {
        "qid": qid, "labels": labels, "titles": titles, "itwiki": sitelinks.get("itwiki"), "classes": items(entity, "P31"), "ids": ids,
        "roles": roles,
        "companies": {k: items(entity, p) for k, p in COMPANY_PROPS.items() if items(entity, p)},
        "genres": items(entity, P_GENRE), "countries": items(entity, P_COUNTRY),
        "languages": list(dict.fromkeys(items(entity, P_LANGUAGE) + items(entity, P_LANGUAGE_WORK))),
        "relations": {k: items(entity, p) for k, p in RELATION_PROPS.items() if items(entity, p)},
        "franchises": {k: items(entity, p) for k, p in FRANCHISE_PROPS.items() if items(entity, p)},
        "dates": dates, "start": [d for c in statements(entity, P_START) if (d := iso_date(_value(c["mainsnak"])))],
        "end": [d for c in statements(entity, P_END) if (d := iso_date(_value(c["mainsnak"])))],
        "runtime_min": runtime_minutes(entity), "financial": financial, "awards": awards,
    }
