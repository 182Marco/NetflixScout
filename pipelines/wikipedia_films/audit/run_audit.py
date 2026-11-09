"""Phase 4 audit driver (local data only, no network, nothing in Phase 1 or Qdrant is modified).

Writes:  data/audit/classification.jsonl  (every record: verdict, subtype, confidence, reasons, flags)
         audit/exclusions.json            (proposed exclusions: explicit, versioned, reversible)
         audit/review_needed.json         (doubtful records to look at before deciding)
         audit/synopsis_contamination.json (records whose synopsis contains sibling sections, from section_scan)
         data/audit/summary.json          (all the numbers of AUDIT_REPORT.md)
         AUDIT_NOYEAR_246.md              (the 246 records with no year, classified and motivated)"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from . import classify as C
from . import features as F
from . import manual_review as M

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = F.OUT


def _read_scan() -> dict[int, dict]:
    p = OUT / "section_scan.jsonl"
    if not p.exists():
        return {}
    return {r["page_id"]: r for r in map(json.loads, p.open())}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = F.load()
    manual = M.apply([r for r in rows if r["film"]["year"] is None])
    scan = _read_scan()
    records = []
    for r in rows:
        f = r["film"]
        c = C.classify(r)
        m = manual.get(f["film_id"])
        if m:
            c = {**c, "verdict": m["verdict"], "subtype": m["subtype"], "confidence": "manual",
                 "reasons": c["reasons"] + [f"manual review: {m['note']}"]}
        s = scan.get(f["wikipedia_page_id"], {})
        contaminated = bool(s.get("siblings_inside"))
        records.append({"film_id": f["film_id"], "wikipedia_page_id": f["wikipedia_page_id"], "title": f["title"], "year": f["year"],
                        "verdict": c["verdict"], "subtype": c["subtype"], "confidence": c["confidence"], "reasons": c["reasons"],
                        "infobox_film": c["infobox_film"], "has_year": f["year"] is not None, "p31": c["p31"],
                        "synopsis_chars": len(f["synopsis"]), "synopsis_contaminated": contaminated if scan else None,
                        "manual": bool(m)})
    with (OUT / "classification.jsonl").open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    non_film = [x for x in records if x["verdict"] in {"topic", "series", "other_work"}]
    doubtful = [x for x in records if x["verdict"] == "doubtful"]

    def slim(x): return {k: x[k] for k in ("film_id", "wikipedia_page_id", "title", "year", "verdict", "subtype", "confidence", "reasons", "manual")}
    (HERE / "exclusions.json").write_text(json.dumps({
        "version": 1, "basis": "Phase 4 audit: Wikidata P31 + infobox/category evidence + manual reading (see AUDIT_REPORT.md)",
        "meaning": "records proposed to leave out of the catalogue used by the chatbot; the source dataset and the collection are NOT modified",
        "count": len(non_film), "records": [slim(x) for x in non_film]}, ensure_ascii=False, indent=1))
    (HERE / "review_needed.json").write_text(json.dumps({
        "version": 1, "meaning": "records the audit could not classify with confidence", "count": len(doubtful),
        "records": [slim(x) for x in doubtful]}, ensure_ascii=False, indent=1))

    summary: dict = {"records": len(records)}
    summary["verdicts"] = dict(collections.Counter(x["verdict"] for x in records))
    summary["verdicts_by_source"] = {k: dict(collections.Counter(x["verdict"] for x in records if x["infobox_film"] == k))
                                     for k in (True, False)}
    summary["film_subtypes"] = dict(collections.Counter(x["subtype"] for x in records if x["verdict"] == "film").most_common())
    summary["non_film_subtypes"] = dict(collections.Counter(f"{x['verdict']}/{x['subtype']}" for x in non_film).most_common())
    summary["manual_overrides"] = len(manual)
    ny = [x for x in records if not x["has_year"]]
    summary["no_year"] = {"total": len(ny), "verdicts": dict(collections.Counter(x["verdict"] for x in ny)),
                          "by_subtype": dict(collections.Counter(f"{x['verdict']}/{x['subtype']}" for x in ny).most_common())}
    if scan:
        cont = [x for x in records if x["synopsis_contaminated"]]
        fixes = {int(json.loads(l)["page_id"]): json.loads(l)["synopsis"] for l in (OUT / "section_fix.jsonl").open()} if (OUT / "section_fix.jsonl").exists() else {}
        rej = [x for x in cont if scan[x["wikipedia_page_id"]].get("would_be_rejected")]
        summary["synopsis_contamination"] = {
            "scanned": len(scan), "contaminated": len(cont), "of_which_film_verdict": sum(1 for x in cont if x["verdict"] == "film"),
            "would_fall_below_plot_minimum_after_fix": len(rej),
            "chars_now": sum(x["synopsis_chars"] for x in cont),
            "chars_after_fix": sum(len(fixes.get(x["wikipedia_page_id"], "")) for x in cont)}
        (HERE / "synopsis_contamination.json").write_text(json.dumps({
            "version": 1, "meaning": "plot section captured together with sibling sections; 'fixed_chars' is the cleaned size of a correct cut",
            "count": len(cont), "records": [{"film_id": x["film_id"], "wikipedia_page_id": x["wikipedia_page_id"], "title": x["title"],
                                             "chars_now": x["synopsis_chars"], "fixed_chars": scan[x["wikipedia_page_id"]].get("fixed_chars"),
                                             "first_sibling": scan[x["wikipedia_page_id"]].get("first_sibling"),
                                             "would_be_rejected": scan[x["wikipedia_page_id"]].get("would_be_rejected")} for x in cont]},
            ensure_ascii=False, indent=1))
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))

    # the 246 records with no year, classified and motivated
    order = ["film", "series", "topic", "other_work", "doubtful"]
    names = {"film": "Film (kept)", "series": "Series, manga, anime, newsreels (not films)", "topic": "Encyclopaedic / topic articles (false positives)",
             "other_work": "Other works (not films)", "doubtful": "Doubtful (to verify)"}
    lines = ["# Audit of the 246 records with no `year` (Phase 4)", "",
             "Generated by `audit/run_audit.py` from local data. Verdict = decision list on Wikidata `P31` + infobox/category evidence + title/genre cues, "
             "then 39 manual decisions after reading the text (`manual`). Nothing was deleted.", ""]
    for v in order:
        grp = sorted((x for x in ny if x["verdict"] == v), key=lambda x: (x["subtype"], x["title"]))
        lines += [f"## {names[v]} — {len(grp)}", "", "| film_id | title | subtype | basis |", "|---|---|---|---|"]
        for x in grp:
            basis = ("manual: " + x["reasons"][-1].split("manual review: ")[-1]) if x["manual"] else x["reasons"][-1]
            lines.append(f"| {x['film_id']} | {x['title'].replace('|', '/')} | {x['subtype']} | {basis.replace('|', '/')} |")
        lines.append("")
    (ROOT / "AUDIT_NOYEAR_246.md").write_text("\n".join(lines))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
