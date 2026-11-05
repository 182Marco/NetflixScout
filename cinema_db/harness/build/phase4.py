"""Reader of the phase-4 Wikidata snapshot (cinema_db/data/wikidata_phase4): labels, life dates and the few claims the build uses.

Pure and offline. Every body is verified against its sha256 by `Snapshot`. Nothing here overrides what the film and series snapshots
already say: the build asks this object only for what the older sources could not give (a name, a date, an ISO code, an award label).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cinema_db.harness.build import extract as X
from cinema_db.harness.build.snapshot import QID_URI, Snapshot

CLAIMS_USED = {
    "classes": "P31", "part_of": "P361", "series": "P179", "country": "P17", "origin": "P495", "headquarters_country": "P17",
}
DEPRECATED = "DeprecatedRank"
PREFERRED = "PreferredRank"
ISO2 = re.compile(r"^[A-Z]{2}$")
ISO3 = re.compile(r"^[a-z]{3}$")
ISO_LANG1 = re.compile(r"^[a-z]{2}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


def render_time(value: str, precision: int) -> str | None:
    """SPARQL xsd:dateTime + Wikidata precision -> ISO partial date (9 year, 10 month, 11 day); BCE, odd years and coarser precision give None."""
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T", value or "")
    if not m or precision < 9:
        return None
    year, month, day = m.groups()
    if year == "0000":
        return None
    if precision == 9:
        return year
    if precision == 10:
        return f"{year}-{month}"
    return f"{year}-{month}-{day}"


def choose_date(rows: list[tuple[str, int, str]]) -> tuple[str | None, str]:
    """rows = (time, precision, rank). Returns (date, status): ok | none | ambiguous. Deprecated ranks are ignored, preferred beats normal,
    several dates that are the same instant at different precisions resolve to the most precise; genuinely different dates are ambiguous."""
    live = [r for r in rows if r[2] != DEPRECATED]
    preferred = [r for r in live if r[2] == PREFERRED]
    dates = {d for t, p, _ in (preferred or live) if (d := render_time(t, p))}
    if not dates:
        return None, "none"
    best = max(dates, key=len)
    if all(best.startswith(d) for d in dates):
        return best, "ok"
    return None, "ambiguous"


def _first(entity: dict, prop: str, checker) -> list[str]:
    out = []
    for c in X.statements(entity, prop):
        v = X._value(c["mainsnak"])
        if isinstance(v, str) and checker.match(v) and v not in out:
            out.append(v)
    return out


def summarize_item(entity: dict) -> dict[str, Any]:
    """The handful of claims the build reads from an award, ceremony, country, language, currency, company or place item."""
    dates = [d for c in X.statements(entity, "P585") if (d := X.iso_date(X._value(c["mainsnak"])))]
    dates = dates or [d for p in ("P580", "P577") for c in X.statements(entity, p) if (d := X.iso_date(X._value(c["mainsnak"])))]
    return {
        "classes": X.items(entity, "P31"), "part_of": X.items(entity, "P361"), "series": X.items(entity, "P179"),
        "country": X.items(entity, "P17"), "origin": X.items(entity, "P495"), "dates": dates,
        "iso2": _first(entity, "P297", ISO2), "iso639_1": _first(entity, "P218", ISO_LANG1), "iso639_3": _first(entity, "P220", ISO3),
        "currency": _first(entity, "P498", CURRENCY),
    }


class Phase4:
    def __init__(self, root: Path) -> None:
        snap = Snapshot(root)
        self.index_sha256 = snap.index_sha256
        self.acquired_range = snap.acquired_range if snap.requests else ("", "")
        self.labels: dict[str, dict[str, str]] = defaultdict(dict)
        self.items: dict[str, dict[str, Any]] = {}
        raw_dates: dict[str, dict[str, list[tuple[str, int, str]]]] = defaultdict(lambda: defaultdict(list))
        self.persons_seen: set[str] = set()
        for r in snap.requests:
            if r.status != 200:
                continue
            body = snap.body(r)
            if r.endpoint.endswith("/sparql"):
                for b in body.get("results", {}).get("bindings", []):
                    uri = b.get("p", {}).get("value", "")
                    if not uri.startswith(QID_URI):
                        continue
                    qid, kind = uri[len(QID_URI):], b["kind"]["value"]
                    self.persons_seen.add(qid)
                    if kind == "label":
                        self.labels[qid].setdefault(b["aux"]["value"], b["value"]["value"])
                    elif kind in ("birth", "death"):
                        raw_dates[qid][kind].append((b["value"]["value"], int(b["aux"]["value"]), b["rank"]["value"].rsplit("#", 1)[-1]))
            elif r.params.get("action") == "wbgetentities":
                for qid, e in body.get("entities", {}).items():
                    if "missing" in e:
                        continue
                    for lang, v in (e.get("labels") or {}).items():
                        self.labels[qid].setdefault(lang, v["value"])
                    if "claims" in e:
                        self.items.setdefault(qid, summarize_item(e))
        self.raw_dates = {q: dict(v) for q, v in raw_dates.items()}

    def life(self, qid: str) -> dict[str, tuple[str | None, str]]:
        d = self.raw_dates.get(qid, {})
        return {k: choose_date(d.get(k, [])) for k in ("birth", "death")}

    def label_of(self, qid: str) -> tuple[str, str] | None:
        lab = self.labels.get(qid, {})
        for lang in ("it", "en", "mul"):
            if lab.get(lang):
                return lab[lang], lang
        return None
