"""Request builders for phase 4: constant fragments plus validated Wikidata ids, nothing else (no free text ever enters a query)."""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from cinema_db.harness.enrich.client import API_URL, SPARQL_URL

QID = re.compile(r"^Q[1-9]\d{0,11}$")
LABEL_LANGUAGES = "it|en|mul"
PERSON_BATCH = 200
ENTITY_BATCH = 50


def checked(ids: list[str]) -> list[str]:
    bad = [i for i in ids if not QID.match(i)]
    if bad:
        raise ValueError(f"not Wikidata item ids: {bad[:3]}")
    return ids


def chunks(ids: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def person_query(ids: list[str]) -> str:
    """Labels (it, en, mul) and life dates WITH their precision and rank for up to PERSON_BATCH people, one result set."""
    values = " ".join(f"wd:{q}" for q in checked(ids))
    return (
        "SELECT ?p ?kind ?value ?aux ?rank WHERE { VALUES ?p { " + values + " } "
        '{ ?p rdfs:label ?value . FILTER(LANG(?value) IN ("it","en","mul")) BIND(LANG(?value) AS ?aux) BIND("label" AS ?kind) } '
        'UNION { ?p p:P569 ?s . ?s wikibase:rank ?rank ; psv:P569 ?v . ?v wikibase:timeValue ?value ; wikibase:timePrecision ?aux . BIND("birth" AS ?kind) } '
        'UNION { ?p p:P570 ?s . ?s wikibase:rank ?rank ; psv:P570 ?v . ?v wikibase:timeValue ?value ; wikibase:timePrecision ?aux . BIND("death" AS ?kind) } }'
    )


def person_request(ids: list[str]) -> tuple[str, dict[str, Any]]:
    return SPARQL_URL, {"endpoint": "sparql", "format": "json", "query": person_query(ids)}


def entities_request(ids: list[str], props: str) -> tuple[str, dict[str, Any]]:
    if props not in ("labels", "labels|claims"):
        raise ValueError("props not allowed")
    return API_URL, {"action": "wbgetentities", "format": "json", "ids": "|".join(checked(ids)), "languages": LABEL_LANGUAGES, "props": props}


# category -> (kind of request, props or None)
KINDS: dict[str, tuple[str, str | None]] = {
    "persons": ("person", None),
    "awards": ("entities", "labels|claims"),
    "award_parents": ("entities", "labels|claims"),
    "dual_use": ("entities", "labels|claims"),
    "currencies": ("entities", "labels|claims"),
    "countries": ("entities", "labels|claims"),
    "languages": ("entities", "labels|claims"),
    "companies": ("entities", "labels|claims"),
    "franchises": ("entities", "labels"),
    "relation_targets": ("entities", "labels"),
    "places": ("entities", "labels|claims"),
}


def batches(category: str, ids: list[str]) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(endpoint, params, meta) for every batch of a category, in a deterministic order."""
    kind, props = KINDS[category]
    size = PERSON_BATCH if kind == "person" else ENTITY_BATCH
    for n, part in enumerate(chunks(sorted(set(ids)), size), 1):
        endpoint, params = person_request(part) if kind == "person" else entities_request(part, props or "labels")
        yield endpoint, params, {"category": category, "batch": n, "count": len(part)}
