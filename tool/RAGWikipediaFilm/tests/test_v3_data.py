from tool.RAGWikipediaFilm.audit import build_v3 as B3
from tool.RAGWikipediaFilm.audit import franchise as FR
from tool.RAGWikipediaFilm.audit.reconcile_v3 import AFTERSHOCK, NOT_DETERMINABLE, reconcile_v3


def test_reconcile_v3_includes_aftershock_and_keeps_the_others_out():
    out = reconcile_v3()
    recs = {r["film_id"]: r for r in out["manifest"]["records"]}
    assert recs[AFTERSHOCK]["decision"] == "include_verified"
    assert AFTERSHOCK not in {e["film_id"] for e in out["plan"]["extra_exclude"]}
    for fid in NOT_DETERMINABLE:
        assert recs[fid]["decision"] == "exclude"


def test_franchise_groups_sequels_and_ignores_big_lists():
    films = {f"Q{i}": {"year": 2000 + i} for i in range(1, 9)}
    links = {f: {"franchises": [], "sequel_links": []} for f in films}
    links["Q1"]["sequel_links"] = ["Q2"]
    links["Q2"]["sequel_links"] = ["Q1", "Q3"]
    links["Q3"]["sequel_links"] = ["Q2"]
    for i in range(4, 9):
        links[f"Q{i}"]["franchises"] = ["QBIG"]
    a = FR.assign(films, links)
    assert {a[f]["franchise_id"] for f in ("Q1", "Q2", "Q3")} == {"C:Q1"}
    assert a["Q5"]["franchise_id"] == "QBIG" and a["Q5"]["franchise_size"] == 5
    films2 = {f"Q{i}": {"year": 2000} for i in range(100, 200)}
    big = {f: {"franchises": ["QLIST"], "sequel_links": []} for f in films2}
    assert FR.assign(films2, big) == {}


def test_work_format_and_normalisation():
    assert B3.work_format("Q1", {"verdict": "film", "subtype": "short", "confidence": "high"}, False) == ("short", "high")
    assert B3.work_format("Q1", {"verdict": "doubtful", "subtype": "anime", "confidence": "medium"}, True) == ("tv_related", "low")
    assert B3.work_format(AFTERSHOCK, None, False) == ("tv_film", "manual")
    assert B3.norm("Léa Seydoux, Di Caprio") == "lea seydoux di caprio"
