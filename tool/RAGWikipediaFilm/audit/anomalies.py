"""Phase 4: further anomalies of the catalogue, from local data only. Writes audit/anomalies.json (ids and values, versioned)."""
from __future__ import annotations

import collections
import json
import re
import unicodedata
from pathlib import Path

from . import features as F

HERE = Path(__file__).resolve().parent


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def main() -> dict:
    rows = F.load()
    cand = {int(json.loads(l)["page_id"]): json.loads(l) for l in (F.PROCESSED / "candidates.jsonl").open()}
    out: dict = {}
    short = lambda f: {"film_id": f["film_id"], "title": f["title"], "year": f["year"]}

    imdb = collections.defaultdict(list)
    for r in rows:
        if r["film"]["imdb_id"]:
            imdb[r["film"]["imdb_id"]].append(short(r["film"]))
    out["shared_imdb_id"] = {k: v for k, v in imdb.items() if len(v) > 1}

    ty = collections.defaultdict(list)
    for r in rows:
        ty[(_norm(r["film"]["title"]).strip(), r["film"]["year"])].append(short(r["film"]))
    out["same_title_and_year"] = [v for v in ty.values() if len(v) > 1]

    syn = collections.defaultdict(list)
    for r in rows:
        syn[r["film"]["synopsis"]].append(short(r["film"]))
    out["identical_synopsis_groups"] = {"groups": sum(1 for v in syn.values() if len(v) > 1),
                                        "films": sum(len(v) for v in syn.values() if len(v) > 1),
                                        "examples": [v for v in syn.values() if len(v) > 1][:10]}

    mism, recov = [], []
    for r in rows:
        f = r["film"]
        m = re.search(r"\((?:[a-z' ]*?)(\d{4})\b", f["title"])
        if m and f["year"] and abs(int(m.group(1)) - f["year"]) > 1:
            mism.append({**short(f), "title_year": int(m.group(1))})
        if m and f["year"] is None:
            recov.append({**short(f), "title_year": int(m.group(1))})
    out["title_year_differs_from_year"] = mism
    out["year_missing_but_in_title"] = recov

    ym, dm = [], []
    for r in rows:
        f = r["film"]
        ib = cand[f["wikipedia_page_id"]]["infobox"]
        if "no_infobox" in r["flags"] or not ib:
            continue
        m = re.search(r"\b(1[89]\d\d|20[0-2]\d)\b", str(ib.get("anno uscita") or ib.get("anno") or ""))
        iy = int(m.group(1)) if m else None
        if iy is not None and f["year"] is not None and abs(iy - f["year"]) > 3:
            ym.append({**short(f), "infobox_year": iy})
        reg = _norm(re.sub(r"\[\[|\]\]|\{\{.*?\}\}", "", str(ib.get("regista") or "")))
        wd = {t for d in f["director"] for t in _norm(d["name"]).split() if len(t) > 3}
        toks = {t for t in reg.split() if len(t) > 3}
        if toks and wd and not (toks & wd):
            dm.append({**short(f), "infobox_director": reg.strip()[:40], "wikidata_director": [d["name"] for d in f["director"]][:2]})
    out["infobox_year_far_from_wikidata_year"] = ym
    out["infobox_director_unrelated_to_wikidata_director"] = {"count": len(dm), "examples": dm[:25]}

    out["wp_fallback_id_no_wikidata_item"] = [short(r["film"]) for r in rows if r["film"]["film_id"].startswith("wp-")]
    dur = [(r["film"], r["film"]["duration_minutes"]) for r in rows if r["film"]["duration_minutes"]]
    out["duration"] = {"missing": sum(1 for r in rows if r["film"]["duration_minutes"] is None),
                       "under_5_min": sum(1 for _, d in dur if d < 5), "over_400_min": [{**short(f), "minutes": d} for f, d in dur if d > 400]}
    out["year_range"] = {"year_2026_or_later": sum(1 for r in rows if r["film"]["year"] and r["film"]["year"] >= 2026),
                         "before_1895": [short(r["film"]) for r in rows if r["film"]["year"] and r["film"]["year"] < 1895]}
    out["plot_heading_storia"] = dict(collections.Counter(("infobox" if "no_infobox" not in r["flags"] else "category-only")
                                                         for r in rows if r["plot_heading"] == "Storia"))
    out["director_missing"] = sum(1 for r in rows if not r["film"]["director"])
    out["cast_missing"] = sum(1 for r in rows if not r["film"]["actors"])
    out["imdb_missing"] = sum(1 for r in rows if not r["film"]["imdb_id"])
    (HERE / "anomalies.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in o.items()})
