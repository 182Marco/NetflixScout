"""Phase 8: local scenarios for preferences like "like X but not like Y". NO API call: positive and negative examples are the stored
vectors of real films, or centroids of groups of films selected on metadata (a stand-in for a concept the planner would otherwise have to
embed as text). No human or LLM judge: the metrics are objective proxies, listed in the report with their limits.

    python -m pipelines.wikipedia_films.indexing.negative_eval"""
from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np

from . import settings as S
from . import negative as N
from .qdrant_index import make_client, point_id
from .v2 import assemble, clean_films, load_fresh, new_units, old_vectors, split_reuse

V2 = S.COLLECTION_V2


def load():
    films = clean_films()
    units = new_units(films)
    old = old_vectors()
    _, missing = split_reuse(units, old)
    vectors = assemble(units, old, load_fresh(units, missing))
    idx = {u.film_id: i for i, u in enumerate(units)}
    return films, vectors, idx


def title_ids(films, pattern):
    rx = re.compile(pattern, re.I)
    return [f for f, r in films.items() if rx.search(r["title"]) or rx.search(r.get("original_title") or "")]


def genre_centroid(films, vectors, idx, pattern, min_n=20):
    rx = re.compile(pattern, re.I)
    ids = [f for f, r in films.items() if any(rx.search(g) for g in r["genres"])]
    return N.centroid(vectors[[idx[f] for f in ids]]), ids


def text_centroid(films, vectors, idx, pattern):
    rx = re.compile(pattern, re.I)
    ids = [f for f, r in films.items() if len(rx.findall(r["synopsis"])) >= 3]
    return N.centroid(vectors[[idx[f] for f in ids]]), ids


def scenarios(films, vectors, idx):
    v = lambda fid: vectors[idx[fid]]
    one = lambda p: title_ids(films, p)[0]
    SW = title_ids(films, r"^Guerre stellari \(film\)$|^L'Impero colpisce ancora$|^Il ritorno dello Jedi$|^Star Wars - |Rogue One|Solo: A Star Wars|Star Wars: The Clone Wars")
    HP = title_ids(films, r"^Harry Potter e ")
    LR = title_ids(films, r"^Il Signore degli Anelli - ")
    MX = title_ids(films, r"^Matrix( Reloaded| Revolutions| Resurrections)?$")
    PR = title_ids(films, r"^Predator|^Predators$|Alien vs\. Predator|^Aliens vs\. Predator")
    sf, sf_ids = genre_centroid(films, vectors, idx, r"^film di fantascienza$")
    fa, fa_ids = genre_centroid(films, vectors, idx, r"^film fantasy$")
    act, act_ids = genre_centroid(films, vectors, idx, r"^film d'azione$")
    fight, fight_ids = text_centroid(films, vectors, idx, r"combattiment|arti marziali|kung fu|scontro a fuoco|lotta")
    interstellar, gravity, br, alien, matrix, inception, terminator = (one(r"^Interstellar$"), one(r"^Gravity \(film\)$"), one(r"^Blade Runner$"),
        one(r"^Alien$"), one(r"^Matrix$"), one(r"^Inception$"), one(r"^Terminator \(film\)$"))
    S_ = []
    def add(name, kind, pos, neg, *, neg_ids=(), franchise=(), avoid_genre=None, avoid_text=None, named_neg=()):
        S_.append(dict(name=name, kind=kind, pos=pos, neg=neg, neg_ids=list(neg_ids), franchise=set(franchise), avoid_genre=avoid_genre,
                       avoid_text=avoid_text, named_neg=list(named_neg)))
    add("1 positiva senza esclusioni (fantascienza)", "positiva", [sf], [])
    add("2 fantascienza, diversa da Star Wars", "titolo da evitare", [sf], [v(SW[0])], neg_ids=[SW[0]], franchise=SW, named_neg=[SW[0]])
    add("3 fantascienza, diversa da Star Wars e Matrix", "più titoli da evitare", [sf], [v(SW[0]), v(MX[0])], neg_ids=[SW[0], MX[0]], franchise=SW + MX, named_neg=[SW[0], MX[0]])
    add("4 fantasy, niente Harry Potter né Il Signore degli Anelli", "più titoli da evitare", [fa], [v(HP[0]), v(LR[0])],
        neg_ids=[HP[0], LR[0]], franchise=HP + LR, named_neg=[HP[0], LR[0]])
    add("5 come Blade Runner, senza cyberpunk", "genere da evitare", [v(br)], [genre_centroid(films, vectors, idx, r"^cyberpunk$")[0]],
        avoid_genre=r"cyberpunk")
    add("6 come Alien, ma non horror", "genere da evitare", [v(alien)], [genre_centroid(films, vectors, idx, r"orrore|horror")[0]],
        avoid_genre=r"orrore|horror")
    add("7 come Matrix, senza combattimenti", "caratteristica narrativa da evitare", [v(matrix)], [fight], avoid_text=r"combattiment|arti marziali|kung fu|scontro a fuoco|lotta")
    add("8 come Interstellar, ma non come Gravity", "simile a un titolo, non a un secondo", [v(interstellar)], [v(gravity)], neg_ids=[gravity], franchise=[gravity], named_neg=[gravity])
    add("9 Interstellar e Inception, non Gravity né Star Wars", "più positive e più negative", [v(interstellar), v(inception)],
        [v(gravity), v(SW[0])], neg_ids=[gravity, SW[0]], franchise=SW + [gravity], named_neg=[gravity, SW[0]])
    add("10 come Alien, diverso da Predator", "simile a un titolo, non a un secondo", [v(alien)], [v(PR[0])], neg_ids=[PR[0]], franchise=PR, named_neg=[PR[0]])
    add("11 Blade Runner e Terminator, assolutamente non Matrix", "più positive e un negativo", [v(br), v(terminator)], [v(matrix)],
        neg_ids=[matrix], franchise=MX, named_neg=[matrix])
    return S_, dict(SW=SW, HP=HP, LR=LR, MX=MX, PR=PR)


def evaluate():
    client = make_client()
    films, vectors, idx = load()
    pid = lambda f: point_id(f, 0)
    scen, _ = scenarios(films, vectors, idx)
    rows, tops = [], {}
    for sc in scen:
        pos, neg = sc["pos"], sc["neg"]
        base_hits = N.search(client, N.centroid(pos), limit=10)
        pos_ids = [f for f, r in films.items() if False]
        own = []  # the positive examples that are real films must not come back
        for p in pos:
            sims = vectors @ N.unit(p)
            j = int(np.argmax(sims))
            if sims[j] > 0.9999:
                own.append(next(f for f, i in idx.items() if i == j))
        ex_pos = [pid(f) for f in own]
        g_rx = re.compile(sc["avoid_genre"], re.I) if sc["avoid_genre"] else None
        t_rx = re.compile(sc["avoid_text"], re.I) if sc["avoid_text"] else None
        gflt = [g for g in {x for r in films.values() for x in r["genres"]} if g_rx and g_rx.search(g)] if g_rx else []
        strategies = {
            "baseline": lambda: N.search(client, N.centroid(pos), limit=10, flt=N.build_filter(exclude_point_ids=ex_pos)),
            "exclude_only": lambda: N.search(client, N.centroid(pos), limit=10, flt=N.build_filter(exclude_point_ids=ex_pos + [pid(f) for f in sc["named_neg"]])),
            "subtract_0.5": lambda: N.search(client, N.subtract_query(pos, neg, 0.5), limit=10, flt=N.build_filter(exclude_point_ids=ex_pos)),
            "subtract_1.0": lambda: N.search(client, N.subtract_query(pos, neg, 1.0), limit=10, flt=N.build_filter(exclude_point_ids=ex_pos)),
            "recommend_avg": lambda: N.recommend(client, pos, neg, strategy="avg", flt=N.build_filter(exclude_point_ids=ex_pos)),
            "recommend_best": lambda: N.recommend(client, pos, neg, strategy="best", flt=N.build_filter(exclude_point_ids=ex_pos)),
            "penalty_0.5": lambda: N.penalty_search(client, pos, neg, lam=0.5, flt=N.build_filter(exclude_point_ids=ex_pos)),
            "penalty_1.0": lambda: N.penalty_search(client, pos, neg, lam=1.0, flt=N.build_filter(exclude_point_ids=ex_pos)),
        }
        if sc["avoid_genre"]:
            strategies["metadata_filter"] = lambda: N.search(client, N.centroid(pos), limit=10, flt=N.build_filter(exclude_point_ids=ex_pos, avoid_genres=gflt))
            strategies["filter+penalty_0.5"] = lambda: N.penalty_search(client, pos, neg, lam=0.5, flt=N.build_filter(exclude_point_ids=ex_pos, avoid_genres=gflt))
        pc = N.centroid(pos); nc = N.centroid(neg) if len(neg) else None
        for name, fn in strategies.items():
            hits = fn()
            fids = [h.payload["film_id"] for h in hits]
            vec = vectors[[idx[f] for f in fids]]
            vec = vec / np.linalg.norm(vec, axis=1, keepdims=True)
            leak = sum(1 for f in fids if f in sc["franchise"] or f in sc["neg_ids"])
            gviol = sum(1 for h in hits if g_rx and any(g_rx.search(x) for x in h.payload["genres"])) if g_rx else None
            tviol = sum(1 for h in hits if t_rx and len(t_rx.findall(h.payload["synopsis"])) >= 3) if t_rx else None
            rows.append({"scenario": sc["name"], "kind": sc["kind"], "strategy": name, "n": len(fids), "franchise_or_named_in_top10": leak,
                         "genre_violations": gviol, "text_violations": tviol,
                         "pos_cos_mean": round(float(np.mean(vec @ pc)), 3), "neg_cos_mean": round(float(np.mean(vec @ nc)), 3) if nc is not None else None,
                         "overlap_with_baseline": len(set(fids) & {h.payload['film_id'] for h in base_hits}) / 10 if base_hits else None})
            tops[(sc["name"], name)] = [f"{h.payload['title']} ({h.payload['year']})" for h in hits[:6]]
    return rows, tops


if __name__ == "__main__":
    rows, tops = evaluate()
    out = S.ROOT / "data/embeddings" / (S.RUN_ID + "-v2")
    (out / "negative_eval.json").write_text(json.dumps({"rows": rows, "tops": {f"{a}|{b}": v for (a, b), v in tops.items()}}, ensure_ascii=False, indent=1))
    agg = defaultdict(list)
    for r in rows:
        agg[r["strategy"]].append(r)
    print(f"{'strategy':22s} n  leak/scen  gen_viol  txt_viol  pos_cos  neg_cos  overlap")
    for s, rs in agg.items():
        m = lambda k: (round(float(np.mean([r[k] for r in rs if r[k] is not None])), 3) if any(r[k] is not None for r in rs) else None)
        print(f"{s:22s} {len(rs):2d} {m('franchise_or_named_in_top10')!s:>9} {m('genre_violations')!s:>9} {m('text_violations')!s:>9} {m('pos_cos_mean')!s:>8} {m('neg_cos_mean')!s:>8} {m('overlap_with_baseline')!s:>8}")
    print()
    for r in rows:
        print(r["scenario"][:46].ljust(46), r["strategy"].ljust(20), "leak", r["franchise_or_named_in_top10"], "gen", r["genre_violations"], "txt", r["text_violations"], "pos", r["pos_cos_mean"], "neg", r["neg_cos_mean"])
