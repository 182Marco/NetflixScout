"""Phase 4 fetch machinery, fully offline: fake transport, temporary stores, no sleeping, no network."""
from __future__ import annotations

import json
import socket

import pytest

from cinema_db.harness.build.snapshot import Snapshot
from cinema_db.harness.enrich import builders
from cinema_db.harness.enrich.client import API_URL, SPARQL_URL, CircuitOpen, Client, Response
from cinema_db.harness.enrich.store import PhaseStore, request_key


class Fake:
    def __init__(self, *responses: Response) -> None:
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append((method, url, data, headers))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def ok(obj) -> Response:
    return Response(200, json.dumps(obj).encode())


def client(tmp_path, transport, sleeps=None):
    sl = sleeps if sleeps is not None else []
    return Client(PhaseStore(tmp_path / "s"), transport=transport, sleep=sl.append, clock=lambda: 0.0, log=lambda *_: None), sl


def test_a_response_is_stored_byte_for_byte_and_read_by_the_existing_snapshot_reader(tmp_path):
    c, _ = client(tmp_path, Fake(ok({"entities": {"Q1": {"labels": {"it": {"language": "it", "value": "Uno"}}}}})))
    params = {"action": "wbgetentities", "format": "json", "ids": "Q1", "languages": "it", "props": "labels"}
    assert c.fetch(API_URL, params, {"category": "t", "batch": 1}) == request_key(API_URL, params)
    snap = Snapshot(tmp_path / "s")
    assert snap.labels() == {"Q1": {"it": "Uno"}} and snap.requests[0].status == 200


def test_a_stored_request_is_never_sent_again(tmp_path):
    t = Fake(ok({"entities": {}}))
    c, _ = client(tmp_path, t)
    p = {"action": "wbgetentities", "format": "json", "ids": "Q1", "languages": "it", "props": "labels"}
    c.fetch(API_URL, p, {})
    c2 = Client(PhaseStore(tmp_path / "s"), transport=t, sleep=lambda s: None, log=lambda *_: None)
    c2.fetch(API_URL, p, {})
    assert len(t.calls) == 1 and c2.stats["reused"] == 1


def test_requests_are_paced_and_carry_a_descriptive_user_agent_without_an_email(tmp_path):
    t = Fake(ok({"entities": {}}))
    c, sleeps = client(tmp_path, t)
    c._last = 0.0
    c.fetch(API_URL, {"action": "wbgetentities", "ids": "Q1"}, {})
    ua = t.calls[0][3]["User-Agent"]
    assert "NetflixScout" in ua and "github.com" in ua and "@" not in ua
    assert sleeps and sleeps[0] == pytest.approx(1.2)
    assert "maxlag=5" in t.calls[0][1]


def test_429_honours_retry_after_then_succeeds(tmp_path):
    c, sleeps = client(tmp_path, Fake(Response(429, b"", 7.0), ok({"results": {}})))
    assert c.fetch(SPARQL_URL, {"endpoint": "sparql", "query": "SELECT 1"}, {}) is not None
    assert 7.0 in sleeps and c.stats["retried"] == 1


def test_maxlag_comes_with_http_200_and_is_retried(tmp_path):
    c, sleeps = client(tmp_path, Fake(ok({"error": {"code": "maxlag"}}), ok({"entities": {}})))
    assert c.fetch(API_URL, {"action": "wbgetentities", "ids": "Q2"}, {}) is not None
    assert c.stats["retried"] == 1 and c.store.root.joinpath("errors.jsonl").exists() is False


def test_a_permanent_failure_is_recorded_as_an_error_never_as_data(tmp_path):
    c, _ = client(tmp_path, Fake(Response(400, b"x")))
    assert c.fetch(API_URL, {"action": "wbgetentities", "ids": "Q3"}, {"category": "x", "batch": 1}) is None
    assert not c.store.index.exists() and json.loads(c.store.errors.read_text())["status"] == 400


def test_the_circuit_opens_after_consecutive_failures(tmp_path):
    c, _ = client(tmp_path, Fake(Response(400, b"")))
    with pytest.raises(CircuitOpen):
        for i in range(10):
            c.fetch(API_URL, {"action": "wbgetentities", "ids": f"Q{i + 1}"}, {})
    assert c.stats["failed"] == 4


def test_an_endpoint_outside_the_allowlist_is_refused(tmp_path):
    c, _ = client(tmp_path, Fake(ok({})))
    with pytest.raises(ValueError):
        c.fetch("https://example.org/api", {}, {})


def test_a_non_json_body_is_not_stored(tmp_path):
    c, _ = client(tmp_path, Fake(Response(200, b"<html>")))
    assert c.fetch(API_URL, {"action": "wbgetentities", "ids": "Q4"}, {}) is None
    assert not c.store.index.exists()


def test_only_valid_item_ids_can_enter_a_query():
    with pytest.raises(ValueError):
        builders.person_query(["Q1", 'Q2 } DROP'])
    with pytest.raises(ValueError):
        builders.entities_request(["P31"], "labels")
    q = builders.person_query(["Q1", "Q2"])
    assert "wd:Q1 wd:Q2" in q and "P569" in q and "P570" in q


def test_batches_are_deterministic_deduplicated_and_sized():
    ids = [f"Q{n}" for n in range(1, 451)] + ["Q1"]
    a = list(builders.batches("persons", ids))
    assert [m["count"] for _, _, m in a] == [200, 200, 50]
    assert [m["count"] for _, _, m in builders.batches("awards", ids)] == [50] * 9
    assert list(builders.batches("awards", ids)) == list(builders.batches("awards", list(reversed(ids))))


def test_the_enrichment_code_has_no_other_network_path():
    import pathlib

    root = pathlib.Path(builders.__file__).parent
    offenders = [p.name for p in root.glob("*.py") if p.name != "client.py" and ("urllib.request" in p.read_text() or "import socket" in p.read_text())]
    assert offenders == []


def test_the_suite_itself_never_opens_a_socket(monkeypatch, tmp_path):
    def refuse(*a, **k):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", refuse)
    c, _ = client(tmp_path, Fake(ok({"entities": {}})))
    c.fetch(API_URL, {"action": "wbgetentities", "ids": "Q5"}, {})
