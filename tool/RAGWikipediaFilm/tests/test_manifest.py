import json

import pytest

from tool.RAGWikipediaFilm import manifest as mf
from tool.RAGWikipediaFilm.config import load_config


def _put_body(snap, key, body):
    import gzip
    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    (snap / "bodies").mkdir(exist_ok=True)
    (snap / "bodies" / f"{digest}.json.gz").write_bytes(gzip.compress(body))
    (snap / "requests.jsonl").write_text(json.dumps({"key": key, "sha256": digest, "bytes": len(body)}) + "\n")


@pytest.fixture
def config(tmp_path):
    cfg = load_config()
    object.__setattr__(cfg.extract, "processed_dir", str(tmp_path / "processed"))
    object.__setattr__(cfg.output, "manifest_dir", str(tmp_path / "manifests"))
    object.__setattr__(cfg.dump, "raw_dir", str(tmp_path / "raw"))
    object.__setattr__(cfg.wikidata, "snapshot_root", str(tmp_path / "snap"))
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "films.jsonl").write_text('{"wikipedia_page_id":1,"title":"A"}\n')
    snap = tmp_path / "snap" / cfg.wikidata.snapshot_id
    snap.mkdir(parents=True)
    _put_body(snap, "k1", b'{"a":1}')
    return cfg


def test_verify_detects_alterations(config, tmp_path):
    mf.write_manifest(config)
    assert mf.verify_manifest(config) == []
    (tmp_path / "processed" / "films.jsonl").write_text('{"wikipedia_page_id":1,"title":"B"}\n')
    assert any("films.jsonl differs" in p for p in mf.verify_manifest(config))


def test_manifest_content_is_deterministic_apart_from_volatile_keys(config):
    a, b = mf.build_manifest(config), mf.build_manifest(config)
    strip = lambda m: {k: v for k, v in m.items() if k not in mf.VOLATILE_KEYS}
    assert strip(a) == strip(b)
    assert a["outputs"]["films.jsonl"]["records"] == 1 and a["wikidata_snapshot"]["requests"] == 1


def test_snapshot_change_is_detected(config, tmp_path):
    mf.write_manifest(config)
    _put_body(tmp_path / "snap" / config.wikidata.snapshot_id, "k1", b'{"a":2}')
    assert "Wikidata snapshot content differs" in mf.verify_manifest(config)


def test_compare_reports_per_field_differences(tmp_path):
    left, right = tmp_path / "l.jsonl", tmp_path / "r.jsonl"
    left.write_text('{"wikipedia_page_id":1,"year":1990}\n{"wikipedia_page_id":2,"year":2000}\n')
    right.write_text('{"wikipedia_page_id":1,"year":1991}\n{"wikipedia_page_id":3,"year":2000}\n')
    report = mf.compare_films(left, right)
    assert report["only_in_left"] == [2] and report["only_in_right"] == [3]
    assert report["changed_fields"] == {"year": 1} and not report["identical"]


def test_verify_detects_a_corrupted_or_missing_snapshot_body(tmp_path):
    import gzip

    cfg = load_config()
    object.__setattr__(cfg.extract, "processed_dir", str(tmp_path / "processed"))
    object.__setattr__(cfg.output, "manifest_dir", str(tmp_path / "manifests"))
    object.__setattr__(cfg.dump, "raw_dir", str(tmp_path / "raw"))
    object.__setattr__(cfg.wikidata, "snapshot_root", str(tmp_path / "snap"))
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "films.jsonl").write_text("{}\n")
    snap = tmp_path / "snap" / cfg.wikidata.snapshot_id
    (snap / "bodies").mkdir(parents=True)
    body = b'{"entities":{}}'
    digest = __import__("hashlib").sha256(body).hexdigest()
    (snap / "bodies" / f"{digest}.json.gz").write_bytes(gzip.compress(body))
    (snap / "requests.jsonl").write_text(json.dumps({"key": "k", "sha256": digest, "bytes": len(body)}) + "\n")
    mf.write_manifest(cfg)
    assert mf.verify_manifest(cfg) == []
    (snap / "bodies" / f"{digest}.json.gz").write_bytes(gzip.compress(b'{"entities":{"Q1":{}}}'))
    assert any("corrupted" in p for p in mf.verify_manifest(cfg))
    (snap / "bodies" / f"{digest}.json.gz").unlink()
    assert any("missing" in p for p in mf.verify_manifest(cfg))


def test_verify_detects_a_changed_bytes_field_in_the_snapshot_index(config, tmp_path):
    mf.write_manifest(config)
    assert mf.verify_manifest(config) == []
    index = tmp_path / "snap" / config.wikidata.snapshot_id / "requests.jsonl"
    entry = json.loads(index.read_text())
    entry["bytes"] += 1  # key and SHA-256 untouched: only the size recorded in the index changes
    index.write_text(json.dumps(entry) + "\n")
    problems = mf.verify_manifest(config)
    assert "Wikidata snapshot content differs" in problems
    assert any("corrupted" in p for p in problems)
