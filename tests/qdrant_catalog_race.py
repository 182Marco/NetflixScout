"""Multi-process stress test of the catalog's conditional writes against a REAL Qdrant server.

    python tests/qdrant_catalog_race.py --url http://127.0.0.1:6401 --rounds 200 --report FILE

The catalog relies on the server evaluating `update_filter` / filtered `overwrite_payload` /
guarded `set_payload` atomically with the write. That is a property of the server, not of the
client in memory, so it is tested here with separate processes, a synthetic collection (never the
real index) and a deterministic fake embedding. The same harness runs once with the guards removed
(`--unguarded`): it must then show anomalies, otherwise it cannot tell a working guard from none and
its verdict on the guarded run does not count.

Scenarios: text updates; creation of an absent point; metadata-only updates; text and metadata
mixed; links of one corpus film to two different TMDb ids; equal timestamps. An observer reads the
point continuously while the writers run. Checked after every round:
  coherence of every observed state (text_hash of the document, vector of the document, meta_hash,
  derived fields), `version` never decreasing, no lost update (final version = seed version + number
  of writes claimed as applied), final state = the writer with the highest timestamp (one winner for
  equal timestamps and for links).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import random
import sys
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import numpy as np
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tool.rag.FromQueryEmbeddingToRes.store import StorePoint, norm_title, point_uuid, year_int  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta  # noqa: E402
from tool.rag.FromQueryEmbeddingToRes.store.catalog import (  # noqa: E402
    CatalogRecord, CatalogStore, full_payload, meta_hash, text_hash)
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore  # noqa: E402

MODEL, DIM = "race-model", 8
SCENARIOS = ("text_update", "insert_race", "meta_only", "mixed", "link_race", "equal_ts")
CLAIMS = ("inserted", "updated", "metadata_updated")
GENRES = ["Crime", "War", "Family", "Music", "Drama", "Romance"]


def fake_embed(text: str) -> list[float]:
    raw = hashlib.sha256(text.encode()).digest()[:DIM]
    v = np.array([(b - 127.5) / 127.5 for b in raw], dtype=np.float64)
    return (v / np.linalg.norm(v)).tolist()


def plot(tag: str) -> str:
    return f"Plot {tag}. " + "A lighthouse keeper opens a hidden door under the sea. " * 3


class Unguarded(CatalogStore):
    """Same logic with every condition removed: the negative control."""

    def _create(self, record, text, vector):
        wid = self.new_write_id()
        payload = full_payload(record, text, model=self.model, dimension=self.dimension, version=1, write_id=wid)
        self.client.upsert(self.collection, [models.PointStruct(
            id=point_uuid(payload["legacy_id"]), vector=vector, payload=payload)], wait=self.wait)
        return self._applied(payload["legacy_id"], wid)

    def _replace(self, record, text, vector, read_version):
        wid = self.new_write_id()
        payload = full_payload(record, text, model=self.model, dimension=self.dimension,
                               version=read_version + 1, write_id=wid)
        self.client.upsert(self.collection, [models.PointStruct(
            id=point_uuid(payload["legacy_id"]), vector=vector, payload=payload)], wait=self.wait)
        return self._applied(payload["legacy_id"], wid)

    def _replace_metadata(self, record, text, read_version):
        wid = self.new_write_id()
        payload = full_payload(record, text, model=self.model, dimension=self.dimension,
                               version=read_version + 1, write_id=wid)
        self.client.overwrite_payload(self.collection, payload, points=[point_uuid(payload["legacy_id"])],
                                      wait=self.wait)
        return self._applied(payload["legacy_id"], wid)

    def _link(self, target, tmdb_id):
        self.client.set_payload(self.collection, {"tmdb_id": int(tmdb_id)}, points=[target.point_id], wait=self.wait)
        found = self.client.retrieve(self.collection, ids=[target.point_id], with_payload=["tmdb_id"])
        current = (found[0].payload or {}).get("tmdb_id") if found else None
        return ("linked", "") if current == int(tmdb_id) else ("skipped", "ambiguous:candidate_linked_elsewhere")


def worker_main(idx, url, collection, guarded, wait, seed, barrier, tasks, results):
    client = QdrantClient(url=url, check_compatibility=False)
    store = (CatalogStore if guarded else Unguarded)(client, collection, MODEL, DIM, wait=wait)
    rng = random.Random(seed * 100 + idx)

    def embed(text):  # the real embedding takes long between the read and the write: widen that gap
        time.sleep(rng.random() * 0.004)
        return fake_embed(text)

    while True:
        task = tasks.get()
        if task is None:
            break
        record = CatalogRecord(**task["record"])
        try:
            barrier.wait(timeout=60)
            time.sleep(rng.random() * 0.002)
            out = store.sync(record, embed)
            results.put((task["round"], idx, out.status, out.reason, out.attempts, None))
        except Exception as exc:  # noqa: BLE001
            results.put((task["round"], idx, "exception", type(exc).__name__, 0, repr(exc)[:200]))
    client.close()


# ---- coherence of one observed state
def incoherent(payload: dict, vector) -> list[str]:
    problems = []
    doc = payload.get("document", "")
    if payload.get("text_hash") != text_hash(MODEL, DIM, doc):
        problems.append("text_hash_vs_document")
    if vector is None or not np.allclose(np.asarray(vector), np.asarray(fake_embed(doc)), atol=1e-4):
        problems.append("vector_vs_document")
    if payload.get("meta_hash") != meta_hash(payload):
        problems.append("meta_hash_vs_payload")
    if payload.get("title_norm") != norm_title(payload.get("title")):
        problems.append("title_norm")
    if payload.get("release_year_int") != year_int(payload.get("release_year")):
        problems.append("release_year_int")
    return problems


class Observer(threading.Thread):
    """A separate client reading the point in a loop while the writers run."""

    def __init__(self, url, collection, pid):
        super().__init__(daemon=True)
        self.client = QdrantClient(url=url, check_compatibility=False)
        self.collection, self.pid = collection, pid
        self.stop = threading.Event()
        self.problems: list[str] = []
        self.versions: list[int] = []
        self.reads = 0

    def run(self):
        while not self.stop.is_set():
            try:
                got = self.client.retrieve(self.collection, ids=[self.pid], with_payload=True, with_vectors=True)
            except Exception as exc:  # noqa: BLE001
                self.problems.append(f"observer_error:{type(exc).__name__}")
                time.sleep(0.05)
                continue
            self.reads += 1
            time.sleep(0.001)  # a hot loop exhausts the ephemeral ports of the machine
            if got:
                payload = got[0].payload or {}
                if "version" in payload:
                    self.versions.append(int(payload["version"]))
                self.problems.extend(incoherent(payload, got[0].vector) if payload.get("source") == "tmdb" else [])
        self.client.close()


# ---- scenarios
def record_for(tmdb_id, title, ts, tag, genres=("Drama",), year=2014) -> dict:
    return dict(tmdb_id=tmdb_id, title=title, overview=plot(tag), year=year, fetched_ts=ts, genres=tuple(genres))


def build(scen, rnd, n, parity):
    """(seed record or None, worker records, link-scenario flag) for one round; ids unique per round."""
    base = 1_000_000 + rnd * 100
    title = f"Race Film r{rnd} {scen.replace('_', ' ')}"
    seed = None
    if scen == "text_update":
        seed = record_for(base, title, 100, "seed")
        workers = [record_for(base, title, 200 + i, f"w{i}") for i in range(n)]
    elif scen == "insert_race":
        workers = [record_for(base, title, 200 + i, f"w{i}") for i in range(n)]
    elif scen == "meta_only":
        seed = record_for(base, title, 100, "same")
        workers = [record_for(base, title, 200 + i, "same", genres=(GENRES[i % len(GENRES)],)) for i in range(n)]
    elif scen == "mixed":
        seed = record_for(base, title, 100, "same")
        workers = [record_for(base, title, 200 + i, f"w{i}" if i % 2 == 0 else "same",
                              genres=(GENRES[i % len(GENRES)],)) for i in range(n)]
    elif scen == "equal_ts":
        seed = record_for(base, title, 100, "seed") if parity else None
        workers = [record_for(base, title, 200, f"w{i}") for i in range(n)]
    else:  # link_race: distinct TMDb ids, same film
        workers = [record_for(base + i, title, 200, f"w{i}") for i in range(n)]
    return seed, workers


def run_round(coord, store_guarded, collection, url, scen, rnd, n, parity, task_qs, results_q, strict=True):
    """`strict` (wait=True) also checks the outcomes the writers report; with wait=False a writer's own
    read-back can precede its write, so only the stored state is judged."""
    seed, workers = build(scen, rnd, n, parity)
    base_id = workers[0]["tmdb_id"]
    pid = point_uuid(f"tmdb:movie:{base_id}")
    seed_version = 0
    cmu_pid = None
    if scen == "link_race":
        cmu_id = f"cmu-{rnd}"
        coord.upsert([StorePoint(id=cmu_id, vector=fake_embed("cmu " + cmu_id), document=f"cmu plot {rnd}",
                                 metadata={"title": workers[0]["title"], "movie_id": cmu_id, "source": "plots",
                                           "release_year": "2014"})])
        cmu_pid = point_uuid(cmu_id)
    elif seed is not None:
        assert store_guarded.sync(CatalogRecord(**seed), fake_embed).status == "inserted"
        seed_version = 1
    observer = Observer(url, collection, pid)
    observer.start()
    for i, w in enumerate(workers):
        task_qs[i].put({"round": rnd, "record": w})
    got = [results_q.get(timeout=120) for _ in range(n)]
    time.sleep(0.05)
    observer.stop.set()
    observer.join(5)

    issues: list[str] = list(observer.problems)
    if any(b < a for a, b in zip(observer.versions, observer.versions[1:])):
        issues.append("version_decreased")
    errors = [r for r in got if r[2] in ("exception", "error")]
    issues += [f"worker_{r[2]}:{r[3]}" for r in errors]
    claims = sum(1 for r in got if r[2] in CLAIMS)

    if scen == "link_race":
        cmu = coord.client.retrieve(coord.collection, ids=[cmu_pid], with_payload=True, with_vectors=True)[0]
        linked = [r for r in got if r[2] == "linked"]
        if strict:
            if len(linked) != 1:
                issues.append(f"links_applied:{len(linked)}")
            elif cmu.payload.get("tmdb_id") != workers[linked[0][1]]["tmdb_id"]:
                issues.append("link_not_the_winner")
            others = {r[2] for r in got if r[2] != "linked"}
            if others - {"skipped"}:
                issues.append(f"unexpected_outcomes:{sorted(others)}")
        elif cmu.payload.get("tmdb_id") not in {w["tmdb_id"] for w in workers}:
            issues.append("link_missing_or_foreign")
        if cmu.payload.get("document") != f"cmu plot {rnd}" or not np.allclose(
                cmu.vector, fake_embed(f"cmu cmu-{rnd}"), atol=1e-4):
            issues.append("corpus_point_changed")
        n_points = coord.client.count(coord.collection, count_filter=models.Filter(must=[models.FieldCondition(
            key="title_norm", match=models.MatchValue(value=norm_title(workers[0]["title"])))])).count
        if n_points != 1:
            issues.append(f"duplicate_points:{n_points}")
        return issues, claims, observer.reads

    final = coord.client.retrieve(coord.collection, ids=[pid], with_payload=True, with_vectors=True)
    if not final:
        return issues + ["point_missing"], claims, observer.reads
    payload, vector = final[0].payload, final[0].vector
    issues += [f"final_{p}" for p in incoherent(payload, vector)]
    # A write whose read-back already shows a later writer's write_id is reported as not applied (the
    # read-back only reports): version may exceed seed+claims. It must never be BELOW it: that is a lost update.
    if strict and payload.get("version") < seed_version + claims:
        issues.append(f"lost_update:version={payload.get('version')} seed={seed_version} claims={claims}")
    if scen == "equal_ts":
        if strict and claims != 1:
            issues.append(f"equal_ts_claims:{claims}")
        if payload.get("document") not in {plot(f"w{i}").strip() for i in range(n)} | {plot("seed").strip()}:
            issues.append("equal_ts_unknown_document")
        if payload.get("fetched_ts") != 200:
            issues.append("equal_ts_not_the_winner_timestamp")
    else:
        best = max(workers, key=lambda w: w["fetched_ts"])
        expected = full_payload(CatalogRecord(**best), best_text(best), model=MODEL, dimension=DIM, version=0, write_id="")
        for key in ("document", "genres", "fetched_ts", "text_hash", "meta_hash"):
            if payload.get(key) != expected.get(key):
                issues.append(f"final_not_highest_ts:{key}")
    return issues, claims, observer.reads


def best_text(record: dict) -> str:
    return record["overview"].strip()


def run(url, rounds, procs, wait, guarded, seed=7) -> dict:
    ctx = mp.get_context("spawn")
    name = f"race_{uuid.uuid4().hex[:8]}"
    coord_client = QdrantClient(url=url, check_compatibility=False)
    qs = QdrantStore(coord_client, name, IndexMeta(model=MODEL, dimension=DIM))
    qs.create()
    CatalogStore(coord_client, name, MODEL, DIM).ensure_indexes()
    guarded_store = CatalogStore(coord_client, name, MODEL, DIM)
    barrier = ctx.Barrier(procs)
    results_q = ctx.Queue()
    task_qs = [ctx.Queue() for _ in range(procs)]
    workers = [ctx.Process(target=worker_main, args=(i, url, name, guarded, wait, seed, barrier, task_qs[i], results_q))
               for i in range(procs)]
    for w in workers:
        w.start()
    summary = {s: Counter() for s in SCENARIOS}
    examples: dict[str, list] = {s: [] for s in SCENARIOS}
    reads = 0
    started = time.time()
    try:
        rnd = 0
        for r in range(rounds):
            for scen in SCENARIOS:
                rnd += 1
                issues, _claims, nread = run_round(
                    qs, guarded_store, name, url, scen, rnd, procs, r % 2, task_qs, results_q, strict=wait)
                reads += nread
                summary[scen]["rounds"] += 1
                if issues:
                    summary[scen]["rounds_with_anomalies"] += 1
                    for kind in set(i.split(":")[0] for i in issues):
                        summary[scen][kind] += 1
                    if len(examples[scen]) < 3:
                        examples[scen].append({"round": rnd, "issues": issues[:6]})
    finally:
        for q in task_qs:
            q.put(None)
        for w in workers:
            w.join(20)
            if w.is_alive():
                w.terminate()
        coord_client.delete_collection(name)
        coord_client.close()
    total = sum(c["rounds_with_anomalies"] for c in summary.values())
    return {"processes": procs, "wait": wait, "guarded": guarded, "rounds_per_scenario": rounds,
            "observer_reads": reads, "seconds": round(time.time() - started, 1),
            "rounds_with_anomalies": total, "per_scenario": {k: dict(v) for k, v in summary.items()},
            "examples": examples}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--procs", type=int, nargs="+", default=[2, 4])
    ap.add_argument("--wait", choices=["true", "false", "both"], default="both")
    ap.add_argument("--unguarded", action="store_true", help="negative control: conditions removed")
    ap.add_argument("--report", required=True)
    args = ap.parse_args(argv)
    waits = {"true": [True], "false": [False], "both": [True, False]}[args.wait]
    runs = []
    for procs in args.procs:
        for wait in waits:
            result = run(args.url, args.rounds, procs, wait, guarded=not args.unguarded)
            runs.append(result)
            sys.stdout.write(f"procs={procs} wait={wait} guarded={not args.unguarded}: "
                             f"{result['rounds_with_anomalies']} rounds with anomalies, {result['seconds']} s\n")
            sys.stdout.flush()
    Path(args.report).write_text(json.dumps({"guarded": not args.unguarded, "runs": runs}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
