"""Build manifest, verification and comparison of two builds (checksums, no data in git)."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from .config import DEFAULT_CONFIG, PipelineConfig, config_sha256

MANIFEST_NAME = "build_manifest.json"
VOLATILE_KEYS = {"built_at", "git_commit", "git_dirty"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def snapshot_digest(snapshot_dir: Path) -> dict:
    """Content identity of the snapshot: SHA-256 over the sorted (request key, body sha256, bytes) triples."""
    index = snapshot_dir / "requests.jsonl"
    if not index.exists():
        return {"present": False}
    pairs = sorted(
        (e["key"], e["sha256"], e["bytes"])
        for e in (json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip())
    )
    joined = "\n".join(f"{k} {h} {b}" for k, h, b in pairs)  # key, body hash AND size
    return {
        "present": True,
        "requests": len(pairs),
        "uncompressed_bytes": sum(b for _, _, b in pairs),
        "content_sha256": hashlib.sha256(joined.encode()).hexdigest(),
    }


def snapshot_body_problems(snapshot_dir: Path) -> list[str]:
    """Every indexed response must exist on disk and match its recorded SHA-256 (deep check)."""
    import gzip

    index = snapshot_dir / "requests.jsonl"
    if not index.exists():
        return []
    problems: list[str] = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        body = snapshot_dir / "bodies" / f"{entry['sha256']}.json.gz"
        try:
            data = gzip.decompress(body.read_bytes())
        except (OSError, EOFError):
            problems.append(f"snapshot body missing or unreadable: {entry['sha256'][:12]}")
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["bytes"]:
            problems.append(f"snapshot body corrupted: {entry['sha256'][:12]}")
    return problems


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def build_manifest(config: PipelineConfig, config_path: Path | None = None) -> dict:
    processed = config.processed_dir
    outputs: dict[str, dict] = {}
    for name in (config.output.films_file, config.output.candidates_file):
        path = processed / name
        if path.exists():
            outputs[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size, "records": count_lines(path)}
    dump: dict = {"date": config.dump.date, "filename": config.dump.filename, "url": config.dump.url}
    info = config.dump_path.with_name(config.dump_path.name + ".info.json")
    if info.exists():
        recorded = json.loads(info.read_text(encoding="utf-8"))
        dump.update({k: recorded[k] for k in ("bytes", "sha1", "sha256", "expected_sha1") if k in recorded})
    extract_ckpt = processed / "extract_checkpoint.json"
    return {
        "schema_version": 1,
        "config_sha256": config_sha256(config_path or DEFAULT_CONFIG),
        "dump": dump,
        "extract": json.loads(extract_ckpt.read_text(encoding="utf-8")).get("stats") if extract_ckpt.exists() else None,
        "wikidata_snapshot": {"id": config.wikidata.snapshot_id, **snapshot_digest(config.snapshot_dir)},
        "outputs": outputs,
        "tools": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": {p: metadata.version(p) for p in ("mwparserfromhell", "pydantic", "PyYAML")},
        },
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "tool/RAGWikipediaFilm")),
    }


def write_manifest(config: PipelineConfig, config_path: Path | None = None) -> Path:
    target_dir = config.path(config.output.manifest_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / MANIFEST_NAME
    target.write_text(
        json.dumps(build_manifest(config, config_path), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def verify_manifest(config: PipelineConfig, manifest_path: Path | None = None, config_path: Path | None = None) -> list[str]:
    """Differences between the manifest and what is on disk now (empty list = identical build)."""
    path = manifest_path or config.path(config.output.manifest_dir) / MANIFEST_NAME
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual = build_manifest(config, config_path)
    problems: list[str] = []
    if expected["config_sha256"] != actual["config_sha256"]:
        problems.append("config.yaml differs from the one used for the build")
    for key in ("sha256", "bytes"):
        if key in expected["dump"] and key in actual["dump"] and expected["dump"][key] != actual["dump"][key]:
            problems.append(f"dump {key} differs")
    if "sha256" in expected["dump"] and "sha256" not in actual["dump"]:
        problems.append("dump not present locally: dump checksum NOT verified")
    if expected["wikidata_snapshot"].get("content_sha256") != actual["wikidata_snapshot"].get("content_sha256"):
        problems.append("Wikidata snapshot content differs")
    problems.extend(snapshot_body_problems(config.snapshot_dir))
    for name, info in expected["outputs"].items():
        now = actual["outputs"].get(name)
        if now is None:
            problems.append(f"{name} is missing")
        elif now["sha256"] != info["sha256"]:
            problems.append(f"{name} differs (records {info['records']} -> {now['records']})")
    for package, version in expected["tools"]["packages"].items():
        if actual["tools"]["packages"].get(package) != version:
            problems.append(f"{package} version {actual['tools']['packages'].get(package)} != {version}")
    if expected["tools"]["python"].rsplit(".", 1)[0] != actual["tools"]["python"].rsplit(".", 1)[0]:
        problems.append(f"Python {actual['tools']['python']} != {expected['tools']['python']} (minor version)")
    return problems


def compare_films(left: Path, right: Path) -> dict:
    """Record-level difference between two films.jsonl (by wikipedia_page_id), per field."""
    def load(path: Path) -> dict[int, dict]:
        return {r["wikipedia_page_id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r}

    a, b = load(left), load(right)
    changed: dict[str, int] = {}
    changed_records = 0
    for page_id in a.keys() & b.keys():
        fields = [k for k in a[page_id] if a[page_id][k] != b[page_id].get(k)]
        if fields:
            changed_records += 1
            for field in fields:
                changed[field] = changed.get(field, 0) + 1
    return {
        "left_records": len(a),
        "right_records": len(b),
        "only_in_left": sorted(a.keys() - b.keys()),
        "only_in_right": sorted(b.keys() - a.keys()),
        "changed_records": changed_records,
        "changed_fields": dict(sorted(changed.items())),
        "identical": a == b,
    }
