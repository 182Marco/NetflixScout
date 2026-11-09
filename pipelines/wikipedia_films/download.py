"""Streaming download of the dated Italian Wikipedia dump, with resume and verification."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import DumpConfig, PipelineConfig

log = logging.getLogger("ragwiki.download")
USER_AGENT = "RAGWikipediaPipeline/1.0 (dump download; see pipelines/wikipedia_films/README.md)"


class DownloadError(RuntimeError):
    pass


def _open(url: str, *, start: int, end: int | None, timeout: float):
    headers = {"User-Agent": USER_AGENT}
    if start or end is not None:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def fetch_expected_sha1(cfg: DumpConfig) -> str | None:
    """SHA-1 published by Wikimedia for the dump file (None if the sums file lists nothing)."""
    try:
        with _open(cfg.sha1sums_url, start=0, end=None, timeout=cfg.timeout_seconds) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as error:
        log.warning("cannot read %s: %s", cfg.sha1sums_url, error)
        return None
    for line in text.splitlines():
        digest, _, name = line.strip().partition("  ")
        if name == cfg.filename:
            return digest
    return None


def file_digests(path: Path, chunk: int = 1 << 20) -> dict[str, str]:
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            sha1.update(block)
            sha256.update(block)
    return {"sha1": sha1.hexdigest(), "sha256": sha256.hexdigest()}


def download_dump(config: PipelineConfig, *, max_bytes: int | None = None, verify: bool = True) -> Path:
    """Download (or resume) the dump. With `max_bytes` only a prefix is fetched, into a `.sample`
    file that is never verified and never mistaken for the full dump."""
    cfg = config.dump
    target = config.dump_path
    target.parent.mkdir(parents=True, exist_ok=True)
    sample = max_bytes is not None
    final = target.with_name(target.name + ".sample") if sample else target
    part = final.with_name(final.name + ".part")
    if final.exists() and not sample:
        log.info("already downloaded: %s", final)
        return final

    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(1, cfg.max_retries + 1):
        have = part.stat().st_size if part.exists() else 0
        end = None if not sample else max_bytes - 1
        if sample and have >= max_bytes:
            break
        try:
            with _open(cfg.url, start=have, end=end, timeout=cfg.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if have and status != 206:
                    log.warning("server ignored Range (status %s): restarting from zero", status)
                    have = 0
                total = int(response.headers.get("Content-Length", 0)) + have
                mode = "ab" if have else "wb"
                log.info("download attempt %d: %s bytes_have=%d total=%s", attempt, cfg.url, have, total or "?")
                expected_len = int(response.headers.get("Content-Length", 0))
                received = 0
                with part.open(mode) as out:
                    while block := response.read(cfg.chunk_bytes):
                        out.write(block)
                        received += len(block)
                if expected_len and received < expected_len:  # urllib ends silently on a dropped connection
                    raise ConnectionError(f"incomplete body: {received} of {expected_len} bytes")
            last_error = None
            break
        except urllib.error.HTTPError as error:
            if error.code == 416 and have and not sample:  # Range beyond the end: .part is already whole
                log.info("server says the .part is already complete (HTTP 416)")
                last_error = None
                break
            last_error = error
            wait = cfg.retry_backoff_seconds * 2 ** (attempt - 1)
            log.warning("download failed (%s); retrying in %.0fs", error, wait)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last_error = error
            wait = cfg.retry_backoff_seconds * 2 ** (attempt - 1)
            log.warning("download interrupted (%s); resuming in %.0fs", error, wait)
            time.sleep(wait)
    if last_error is not None:
        raise DownloadError(f"download failed after {cfg.max_retries} attempts: {last_error}") from None

    size = part.stat().st_size
    elapsed = time.monotonic() - started
    info: dict[str, object] = {
        "url": cfg.url,
        "dump_date": cfg.date,
        "bytes": size,
        "seconds": round(elapsed, 1),
        "sample": sample,
    }
    if not sample and verify:
        expected = fetch_expected_sha1(cfg)
        digests = file_digests(part)
        info.update(digests, expected_sha1=expected)
        if expected is not None and digests["sha1"] != expected:
            raise DownloadError(
                f"SHA-1 mismatch: expected {expected}, got {digests['sha1']}; "
                f"delete {part} and download again"
            )
        if expected is None:
            log.warning("no published SHA-1 found: integrity NOT verified against Wikimedia")
    part.replace(final)
    final.with_name(final.name + ".info.json").write_text(
        json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    log.info("download done: %s (%d bytes in %.1fs)", final, size, elapsed)
    return final
