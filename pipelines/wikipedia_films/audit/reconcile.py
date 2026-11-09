"""Phase 7: one canonical decision per record, from the lists of Phases 4, 5 and 6 and the decisions the owner approved.

    python -m pipelines.wikipedia_films.audit.reconcile      # writes audit/decisions_manifest.json and audit/plan_overrides.json

Records are matched by film_id only. A record that appears in several lists must end with ONE decision; the only sanctioned change of
mind is the owner's reinstatement of 8 of the 259 exclusions. Any other disagreement stops the run (SystemExit) instead of being
guessed. The output is the input of `build_clean`."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXC, VER, UNV = "exclude", "include_verified", "include_unverified"
LOBO = "Q140393354"   # sampling false positive (a comic); in no other list


def _load(rel: str):
    return json.loads((ROOT / rel).read_text())


def reconcile() -> dict:
    ex259 = {r["film_id"]: r for r in _load("audit/exclusions.json")["records"]}
    d = _load("audit/decisions.json")
    rev = {r["film_id"]: r for r in d["doubtful_revised"]}
    hyb = {r["film_id"]: r for r in d["hybrids"]}
    rein = {r["film_id"]: r for r in d["reinstate_from_exclusions"]}
    doubtful = {r["film_id"]: r for r in _load("audit/review_needed.json")["records"]}
    films = {json.loads(l)["film_id"]: json.loads(l)["title"] for l in (ROOT / "data/processed/films.jsonl").open()}

    overlaps = {"259&27": sorted(set(ex259) & set(rev)), "259&46": sorted(set(ex259) & set(hyb)), "27&46": sorted(set(rev) & set(hyb)),
                "71&46": sorted(set(doubtful) & set(hyb)), "27_not_in_71": sorted(set(rev) - set(doubtful)),
                "259&71": sorted(set(ex259) & set(doubtful)), "lobo_elsewhere": sorted({LOBO} & (set(ex259) | set(rev) | set(hyb)))}
    bad = {k: v for k, v in overlaps.items() if v}
    if bad:
        raise SystemExit(f"unexpected overlaps between the lists, stopping: {bad}")
    if set(rein) - set(ex259):
        raise SystemExit("a reinstatement is not among the 259 exclusions")

    final: dict[str, dict] = {}

    def put(fid, decision, reason, source):
        if fid in final:
            raise SystemExit(f"{fid} decided twice ({final[fid]['sources']} / {source})")
        final[fid] = {"film_id": fid, "title": films[fid], "decision": decision, "reason": reason, "sources": [source]}

    for fid, r in ex259.items():
        if fid in rein:
            continue
        put(fid, EXC, f"{r['verdict']}/{r['subtype']}: " + "; ".join(r["reasons"][:2]), "fase4:259")
    for fid, r in rein.items():
        dec = VER if r["decision"] == "includere" else UNV
        put(fid, dec, "reinserito dall'elenco delle 259 (decisione approvata): " + r["reason"], "fase6:riesame-259")
        final[fid]["sources"].insert(0, "fase4:259")
    for fid, r in rev.items():
        dec = {"escludere": EXC, "sospeso": UNV, "includere": VER}[r["decision"]]
        put(fid, dec, f"{r['nature']}: {r['reason']}", "fase6:27-dubbi")
        final[fid]["sources"].insert(0, "fase4:71")
    for fid, r in hyb.items():
        dec = {"escludere": EXC, "sospeso": UNV, "includere": VER}[r["decision"]]
        put(fid, dec, f"{r['nature']}: {r['reason']}", "fase6:46-ibridi")
    put(LOBO, EXC, "Lobo Paramilitary Christmas Special: è un fumetto (falso positivo del campionamento, fase 5)", "fase5:campione")
    for fid, r in doubtful.items():
        if fid not in final:
            put(fid, UNV, f"dubbio non riesaminato singolarmente ({r['subtype']}): resta incluso, non verificato", "fase4:71")

    counts = Counter(v["decision"] for v in final.values())
    plan = {
        "version": 1,
        "meaning": "built by audit/reconcile.py from the approved decisions; read by audit/build_clean.py",
        "reinstate": sorted(rein),
        "extra_exclude": [{"film_id": f, "subtype": "approved", "reason": v["reason"]} for f, v in sorted(final.items())
                          if v["decision"] == EXC and f not in ex259],
        "extra_unverified": sorted(f for f, v in final.items() if v["decision"] == UNV and f not in doubtful),
        "mark_verified": sorted(f for f, v in final.items() if v["decision"] == VER and f in doubtful),
    }
    expected_excluded = len(ex259) - len(rein) + len(plan["extra_exclude"])
    manifest = {
        "version": 1, "records_decided": len(final), "decisions": dict(counts),
        "exclusions_total": expected_excluded, "from_259_kept_excluded": len(ex259) - len(rein),
        "reinstated_from_259": {"verified": sum(1 for f in rein if final[f]["decision"] == VER),
                                "unverified": sum(1 for f in rein if final[f]["decision"] == UNV)},
        "overlaps_checked": {k: len(v) for k, v in overlaps.items()},
        "records": [final[k] for k in sorted(final)],
    }
    manifest["records_sha256"] = hashlib.sha256(json.dumps(manifest["records"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"manifest": manifest, "plan": plan}


def main() -> None:
    out = reconcile()
    (ROOT / "audit/decisions_manifest.json").write_text(json.dumps(out["manifest"], ensure_ascii=False, indent=1) + "\n")
    (ROOT / "audit/plan_overrides.json").write_text(json.dumps(out["plan"], ensure_ascii=False, indent=1) + "\n")
    m = out["manifest"]
    print({k: m[k] for k in ("records_decided", "decisions", "exclusions_total", "from_259_kept_excluded", "reinstated_from_259")})


if __name__ == "__main__":
    main()
