import hashlib
import http.server
import threading

import pytest

from tool.RAGWikipediaFilm.config import load_config
from tool.RAGWikipediaFilm.download import DownloadError, download_dump

DATA = bytes(range(256)) * 4000  # ~1 MB
NAME = "itwiki-20261101-pages-articles.xml.bz2"


def _server(sha1: str, interrupt_first: bool):
    state = {"served": 0, "ranges": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.endswith("sha1sums.txt"):
                body = f"{sha1}  {NAME}\n".encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            header = self.headers.get("Range")
            state["ranges"].append(header)
            start = int(header.split("=")[1].split("-")[0]) if header else 0
            if start >= len(DATA):
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = int(header.split("-")[1]) + 1 if header and header.split("-")[1] else len(DATA)
            body = DATA[start:end]
            self.send_response(206 if header else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if interrupt_first and state["served"] == 0:
                state["served"] = 1
                self.wfile.write(body[:300000])
                self.wfile.flush()
                self.connection.close()  # connection dropped mid-body
                return
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


@pytest.fixture
def config(tmp_path):
    return lambda port: _config(tmp_path, port)


def _config(tmp_path, port):
    cfg = load_config(overrides={"dump.base_url": f"http://127.0.0.1:{port}/itwiki", "dump.retry_backoff_seconds": 0,
                                 "dump.chunk_bytes": 65536})
    object.__setattr__(cfg.dump, "raw_dir", str(tmp_path / "raw"))
    return cfg


def test_resume_after_interruption_and_sha1_check(config):
    server, state = _server(hashlib.sha1(DATA).hexdigest(), interrupt_first=True)
    try:
        path = download_dump(config(server.server_port))
    finally:
        server.shutdown()
    assert path.read_bytes() == DATA
    assert state["ranges"][0] is None and state["ranges"][1].startswith("bytes=")  # second try resumed


def test_sha1_mismatch_is_an_error(config):
    server, _ = _server("0" * 40, interrupt_first=False)
    try:
        with pytest.raises(DownloadError, match="SHA-1 mismatch"):
            download_dump(config(server.server_port))
    finally:
        server.shutdown()


def test_sample_is_a_prefix_and_is_not_the_dump(config):
    server, _ = _server("0" * 40, interrupt_first=False)
    try:
        cfg = config(server.server_port)
        sample = download_dump(cfg, max_bytes=1000)
    finally:
        server.shutdown()
    assert sample.name.endswith(".sample") and sample.read_bytes() == DATA[:1000]
    assert not cfg.dump_path.exists()


def test_a_complete_part_file_is_finalised_after_http_416(config, tmp_path):
    server, _ = _server(hashlib.sha1(DATA).hexdigest(), interrupt_first=False)
    try:
        cfg = config(server.server_port)
        part = cfg.dump_path.with_name(cfg.dump_path.name + ".part")
        part.parent.mkdir(parents=True)
        part.write_bytes(DATA)  # crash happened after the last byte, before the rename
        path = download_dump(cfg)
    finally:
        server.shutdown()
    assert path.read_bytes() == DATA and not part.exists()
