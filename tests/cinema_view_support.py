"""A `cinema_sql_calls` step with INVENTED data, in the shape `tool/cinema_db/trace.py` produces, for the presenter tests and the contract example."""
from __future__ import annotations

from turn import STEP_CINEMA_SQL_CALLS, TraceStep

SQL = "SELECT work_id, title FROM v_work WHERE work_id = ? LIMIT 1"


def doc_step() -> TraceStep:
    return TraceStep(kind=STEP_CINEMA_SQL_CALLS, title="Local cinema database", data={
        "operation": "filmography", "status": "ok", "reason": None,
        "queries": [{"sql": SQL, "params": [13], "views": ["v_work"], "rows": 1, "ms": 2, "truncated": False}], "queries_count": 4, "views": ["v_credit", "v_name", "v_person", "v_work"],
        "subject": {"kind": "person", "person_id": 14, "name": "Ann Regista", "birth_year": 1950, "wikipedia_it": "Ann_Regista", "wikidata_id": "Q9101"},
        "rows": 2, "total": 5, "truncated": True, "candidates": [], "candidates_omitted": 0, "notes": ["filmography", "limit", "ids_partial", "not_a_known_note"],
        "elapsed_ms": 7, "license": "Contains data from Wikipedia (CC BY-SA 4.0) and Wikidata (CC0 1.0).",
    })


def ambiguous_step() -> TraceStep:
    step = doc_step()
    step.data.update({"operation": "find_work", "status": "ambiguous", "reason": "ids_disagree", "subject": None, "rows": 0, "total": None, "truncated": False, "notes": ["unverified"],
                      "candidates": [{"kind": "film", "title": "Crash", "year": 1996, "directors": ["David Cronenberg"]}, {"kind": "series", "title": "Crash", "year": 2008, "end_year": 2009}],
                      "candidates_omitted": 3})
    return step
