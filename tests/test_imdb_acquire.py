"""A1 acquisition module: manifest, hash, read-only file, idempotence, refusals. Offline: a local HTTP server stands in for IMDb."""
from __future__ import annotations

import functools
import gzip
import http.server
import stat
import threading

import pytest

from cinema_db.harness.acquire import imdb


@pytest.fixture()
def server(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    (root / "title.basics.tsv.gz").write_bytes(gzip.compress(b"tconst\ttitleType\ntt0000001\tshort\n"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/", root
    httpd.shutdown()


def test_fetch_records_manifest_and_makes_file_read_only(server, tmp_path):
    base, root = server
    out = tmp_path / "snap"
    entry = imdb.fetch("title.basics", out, base_url=base, allowed_host=None)
    path = out / "title.basics.tsv.gz"
    assert entry["bytes"] == path.stat().st_size and entry["sha256"] == imdb.sha256_file(path)
    assert entry["url"].endswith("/title.basics.tsv.gz") and entry["retrieved_at"].endswith("Z")
    assert not (path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    assert imdb.verify(out) == {"title.basics": "ok"}


def test_second_fetch_does_not_download_again(server, tmp_path):
    base, root = server
    out = tmp_path / "snap"
    first = imdb.fetch("title.basics", out, base_url=base, allowed_host=None)
    (root / "title.basics.tsv.gz").unlink()  # a second download would now fail with 404
    assert imdb.fetch("title.basics", out, base_url=base, allowed_host=None) == first


def test_refusals(tmp_path):
    with pytest.raises(imdb.AcquisitionError):
        imdb.fetch("title.akas", tmp_path)  # not approved
    with pytest.raises(imdb.AcquisitionError):
        imdb.fetch("title.basics", tmp_path, base_url="http://evil.example/", allowed_host="datasets.imdbws.com")
    (tmp_path / "title.basics.tsv.gz").write_bytes(b"x")
    with pytest.raises(imdb.AcquisitionError):  # present but not in the manifest: never overwritten
        imdb.fetch("title.basics", tmp_path, base_url="http://127.0.0.1:1/", allowed_host=None)


def test_verify_detects_a_changed_file(server, tmp_path):
    base, _ = server
    out = tmp_path / "snap"
    imdb.fetch("title.basics", out, base_url=base, allowed_host=None)
    path = out / "title.basics.tsv.gz"
    path.chmod(0o644)
    path.write_bytes(path.read_bytes()[:-1] + b"Z")
    assert imdb.verify(out) == {"title.basics": "MISMATCH"}
