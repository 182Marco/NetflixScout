"""Decisions of 2026-11-04 on top of the Phase 7 reconciliation, written to SEPARATE files (the v2 plan is never rewritten, so
`build_clean verify` and the v2 collection stay verifiable).

    python -m pipelines.wikipedia_films.audit.reconcile_v3     # writes audit/decisions_manifest_v3.json and audit/plan_overrides_v3.json

Owner decisions applied: Aftershock – Terremoto a New York (Q2421745) is INCLUDED (verified: the page says "film TV" with a single
"Trama"); Anne Frank, Atomic Train and Attila l'unno stay excluded and are listed as "not verified"; the confirmed miniseries stay out."""
from __future__ import annotations

import hashlib
import json

from . import reconcile as R

AFTERSHOCK = "Q2421745"
NOT_DETERMINABLE = {   # excluded, reported as not verified (evidence: audit/two_part_review.json)
    "Q565293": "La storia di Anne Frank: lead «miniserie» ma anche «un film controverso»",
    "Q228396": "Atomic Train - Disastro ad alta velocità: lead «miniserie», una sola «Trama», categorie di film",
    "Q538952": "Attila, l'unno: lead «miniserie», una sola «Trama», categorie di film",
}


def reconcile_v3() -> dict:
    out = R.reconcile()
    m, plan = out["manifest"], out["plan"]
    recs = {r["film_id"]: r for r in m["records"]}
    if recs[AFTERSHOCK]["decision"] != R.EXC:
        raise SystemExit("Aftershock is not excluded in the v2 reconciliation: unexpected, stopping")
    recs[AFTERSHOCK] = {**recs[AFTERSHOCK], "decision": R.VER, "sources": recs[AFTERSHOCK]["sources"] + ["owner:2026-11-04"],
                        "reason": "film TV (la pagina lo dice) con una sola «Trama»: incluso per decisione del proprietario del 2026-11-04"}
    for fid in NOT_DETERMINABLE:
        if recs[fid]["decision"] != R.EXC:
            raise SystemExit(f"{fid} is expected to stay excluded")
    plan["extra_exclude"] = [e for e in plan["extra_exclude"] if e["film_id"] != AFTERSHOCK]
    plan["version"] = 2
    plan["meaning"] = "v3: built by audit/reconcile_v3.py (v2 plus the owner decision of 2026-11-04 on Aftershock)"
    m["records"] = [recs[k] for k in sorted(recs)]
    from collections import Counter
    m["decisions"] = dict(Counter(r["decision"] for r in m["records"]))
    m["exclusions_total"] = len(plan["extra_exclude"]) + m["from_259_kept_excluded"]
    m["included_by_owner_2026_11_04"] = [AFTERSHOCK]
    m["excluded_not_verified"] = [{"film_id": k, "reason": v} for k, v in NOT_DETERMINABLE.items()]
    m["records_sha256"] = hashlib.sha256(json.dumps(m["records"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"manifest": m, "plan": plan}


def main() -> None:
    out = reconcile_v3()
    (R.ROOT / "audit/decisions_manifest_v3.json").write_text(json.dumps(out["manifest"], ensure_ascii=False, indent=1) + "\n")
    (R.ROOT / "audit/plan_overrides_v3.json").write_text(json.dumps(out["plan"], ensure_ascii=False, indent=1) + "\n")
    m = out["manifest"]
    print({k: m[k] for k in ("records_decided", "decisions", "exclusions_total")})


if __name__ == "__main__":
    main()
