"""Turn the per-item judgments into the 0/1/2 grid of the blind sheet (pure arithmetic, no key).

    python docs/qdrant_migration/phase5/score_qualitative.py

Reads qualitative_judgments.json and writes qualitative_scores.json. It never opens
qualitative_key.json: the variants are revealed by `join_key.py`, a separate step run only after
this file has been saved and hashed.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def level(mean: float) -> int:
    mean = round(mean, 6)
    return 2 if mean >= 0.7 else 1 if mean >= 0.3 else 0


def avoid_level(n: list[float]) -> int:
    mean = round(sum(n) / len(n), 6)
    if max(n) >= 1 or mean >= 0.4:
        return 0
    if max(n) >= 0.5 or mean >= 0.15:
        return 1
    return 2


def facts_level(defects: int) -> int:
    return 2 if defects == 0 else 1 if defects == 1 else 0


def score_list(entry: dict) -> dict:
    out = {
        "pertinenza": level(sum(entry["r"]) / len(entry["r"])),
        "vicinanza": None if entry["p"] is None else level(sum(entry["p"]) / len(entry["p"])),
        "assenza": None if entry["n"] is None else avoid_level(entry["n"]),
        "fatti": facts_level(entry["defects"]),
    }
    out["means"] = {"r": round(sum(entry["r"]) / 5, 3),
                    "p": None if entry["p"] is None else round(sum(entry["p"]) / 5, 3),
                    "n": None if entry["n"] is None else round(sum(entry["n"]) / 5, 3)}
    return out


def main() -> None:
    data = json.loads((HERE / "qualitative_judgments.json").read_text(encoding="utf-8"))
    scores = {}
    for case, entry in data["cases"].items():
        scores[case] = {label: score_list(entry[label]) for label in ("X", "Y", "Z")}
        if "note" in entry:
            scores[case]["note"] = entry["note"]
    (HERE / "qualitative_scores.json").write_text(json.dumps(
        {"evaluator": data["evaluator"], "evaluated_on": data["evaluated_on"], "blindness": data["blindness"],
         "list_rules": data["list_rules"], "limits": data["limits"], "scores": scores},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(scores)} cases scored")


if __name__ == "__main__":
    main()
