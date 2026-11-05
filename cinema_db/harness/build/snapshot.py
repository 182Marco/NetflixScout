"""Read-only reader of the Wikidata snapshots that the film and series projects already downloaded.

A snapshot is `<root>/requests.jsonl` (one line per original HTTP response: endpoint, params, status, sha256, acquired_at) plus
`<root>/bodies/<sha256>.json.gz` (the original bytes, compressed). Nothing here writes or touches the network. Every read is
verified against the recorded sha256 of the body file name, so a corrupted or swapped file is detected, never trusted.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

QID_URI = "http://www.wikidata.org/entity/"


@dataclass(frozen=True)
class Request:
    endpoint: str
    params: dict[str, Any]
    status: int
    sha256: str
    acquired_at: str

    @property
    def is_entities(self) -> bool:
        return self.params.get("action") == "wbgetentities" and "claims" in str(self.params.get("props", ""))

    @property
    def is_sparql_labels(self) -> bool:
        return self.endpoint.endswith("/sparql") and "rdfs:label" not in "" and "?label" in str(self.params.get("query", "")) and "?item" in str(self.params.get("query", ""))


class Snapshot:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        index = self.root / "requests.jsonl"
        if not index.is_file():
            raise FileNotFoundError(f"snapshot index not found: {index}")
        self.index_sha256 = hashlib.sha256(index.read_bytes()).hexdigest()
        self.requests = [
            Request(d["endpoint"], d["params"], d["status"], d["sha256"], d["acquired_at"])
            for d in (json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip())
        ]

    @property
    def acquired_range(self) -> tuple[str, str]:
        times = sorted(r.acquired_at for r in self.requests)
        return times[0], times[-1]

    def body(self, request: Request) -> Any:
        raw = gzip.decompress((self.root / "bodies" / f"{request.sha256}.json.gz").read_bytes())
        if hashlib.sha256(raw).hexdigest() != request.sha256:
            raise ValueError(f"body {request.sha256[:12]} does not match its recorded sha256")
        return json.loads(raw)

    def entities(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """(qid, entity) for every successful entity response, in file order. Duplicates are yielded as recorded."""
        for r in self.requests:
            if r.status == 200 and r.is_entities:
                for qid, entity in self.body(r).get("entities", {}).items():
                    if qid.startswith("Q") and "claims" in entity:
                        yield qid, entity

    def labels(self) -> dict[str, dict[str, str]]:
        """qid -> {language: label}, from the SPARQL label responses and from the labels carried by entity responses."""
        out: dict[str, dict[str, str]] = {}
        for r in self.requests:
            if r.status != 200:
                continue
            if r.is_sparql_labels:
                for b in self.body(r).get("results", {}).get("bindings", []):
                    uri = b.get("item", {}).get("value", "")
                    if uri.startswith(QID_URI) and "label" in b:
                        out.setdefault(uri[len(QID_URI):], {})[b["label"].get("xml:lang", b.get("lang", {}).get("value", ""))] = b["label"]["value"]
            elif r.params.get("action") == "wbgetentities" and "labels" in str(r.params.get("props", "")):
                for qid, entity in self.body(r).get("entities", {}).items():
                    for lang, v in (entity.get("labels") or {}).items():
                        out.setdefault(qid, {})[lang] = v["value"]
        return out
