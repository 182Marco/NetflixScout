"""Phase 5: individual review of the 71 doubtful records. Decisions come from READING the page text and the Wikidata/infobox
evidence in the audit, not from an external source; the confidence column says how sure the reading is. NOTHING here changes the
catalogue: the 71 records stay included and flagged unverified until the owner decides.

Key = position in the doubtful list (document order of `data/audit/classification.jsonl`, verdict == 'doubtful'); the film_id is
checked against EXPECTED_IDS so a changed classification cannot silently shift the table."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INC, EXC, HOLD = "includere", "escludere", "sospeso"
# idx: (category, decision, confidence, reason)
D: dict[int, tuple[str, str, str, str]] = {
    0: ("serie anime", EXC, "media", "26 minuti = durata di un episodio; la pagina descrive la serie TV, l'infobox Film è un errore di pagina"),
    1: ("OVA", HOLD, "bassa", "OVA a più episodi; da valutare se la pagina tratta la serie o un lungometraggio"),
    2: ("serie anime", EXC, "bassa", "trama del personaggio di una serie TV (nome italiano della serie), nessuna durata, nessun codice IMDb"),
    3: ("film TV", INC, "alta", "film TV della serie di Perry Mason; mancano solo regista e IMDb nella pagina"),
    4: ("film anime (OVA)", INC, "alta", "71 minuti, opera unica di Oshii: lungometraggio d'animazione uscito direttamente in home video"),
    5: ("anime breve", HOLD, "bassa", "30 minuti; non è chiaro se la pagina parli del mediometraggio del 1996 o della serie"),
    6: ("serie anime", EXC, "alta", "serie TV Digimon, 20 minuti = episodio"),
    7: ("lungometraggio da manga", INC, "media", "99 minuti, regista presente: il film live-action; il manga è solo la fonte"),
    8: ("serie anime", EXC, "media", "pagina della serie TV (anche se esiste un film omonimo con altro titolo)"),
    9: ("film TV", INC, "alta", "film TV di Perry Mason"),
    10: ("film TV", INC, "alta", "film TV di Perry Mason"),
    11: ("film TV", INC, "alta", "film TV di Perry Mason"),
    12: ("film TV", INC, "alta", "film TV di Perry Mason"),
    13: ("film TV", INC, "alta", "film TV di Perry Mason"),
    14: ("film TV", INC, "alta", "film TV di Perry Mason"),
    15: ("film TV", INC, "alta", "film TV di Perry Mason"),
    16: ("film TV", INC, "alta", "film TV di Perry Mason"),
    17: ("film TV", INC, "alta", "film TV di Perry Mason"),
    18: ("speciale TV anime", INC, "media", "80 minuti, speciale televisivo di lunghezza di un film"),
    19: ("serie anime", HOLD, "bassa", "titolo italiano della serie; esiste anche un film del 1981; la trama copre la serie (cita puntate)"),
    20: ("OVA", HOLD, "media", "serie OVA di 13 episodi; la durata 120 minuti è della versione montata"),
    21: ("film breve anime", INC, "media", "27 minuti, cortometraggio uscito al cinema (Toei Manga Matsuri)"),
    22: ("lungometraggio da manga", INC, "bassa", "120 minuti e regista: sembra il film tratto dal manga"),
    23: ("serie anime", EXC, "alta", "serie TV Digimon Adventure 02"),
    24: ("speciale TV anime", INC, "media", "episodio pilota animato di X-Men (IMDb presente); è un film TV ma la pagina non ha anno"),
    25: ("OVA", HOLD, "bassa", "OVA di 4 episodi ricomposto in film; la pagina non distingue"),
    26: ("lungometraggio da manga", INC, "media", "112 minuti, regista presente: film live-action"),
    27: ("serial cinematografico", INC, "media", "serial del 1941 in 12 capitoli, distribuito al cinema; coerente con gli altri 7 serial già tenuti"),
    28: ("OVA", INC, "bassa", "140 minuti, regista e IMDb: versione lungometraggio dell'OVA"),
    29: ("lungometraggio da manga", INC, "media", "film di Nakae; l'anno 1986 è quello del manga (anno da correggere)"),
    30: ("cortometraggio anime", INC, "alta", "corto di 5 minuti di Makoto Shinkai"),
    31: ("serie anime", EXC, "alta", "serie TV, 30 minuti = episodio"),
    32: ("film anime", INC, "bassa", "la trama parla di un film; manca IMDb"),
    33: ("miniserie TV", EXC, "media", "miniserie televisiva (160 minuti in più parti), regola «niente miniserie»"),
    34: ("anime breve", HOLD, "bassa", "22 minuti, nessun dato sul regista; potrebbe essere un episodio o un corto"),
    35: ("film TV", INC, "media", "107 minuti, regista e IMDb presenti"),
    36: ("film TV", INC, "media", "film televisivo di Tommaso Rossellini"),
    37: ("film TV", INC, "media", "film TV sull'inchiesta Mani Pulite"),
    38: ("OVA", HOLD, "bassa", "OVA di 5 episodi; la pagina parla di «prima e seconda serie»"),
    39: ("cortometraggio muto", INC, "alta", "corto di Winsor McCay del 1921"),
    40: ("serie di film (anime)", HOLD, "bassa", "pagina sulla saga di film; come le altre pagine di «serie di film» andrebbe esclusa"),
    41: ("OVA", HOLD, "bassa", "OVA speciale con IMDb ma senza durata"),
    42: ("film TV anime", INC, "media", "speciale televisivo Lupin III di lunghezza film"),
    43: ("miniserie TV", EXC, "media", "miniserie tedesca in tre parti"),
    44: ("lungometraggio da manga", HOLD, "bassa", "infobox film senza durata né regista; il film è del 2008"),
    45: ("film TV", INC, "alta", "film TV"),
    46: ("anime", HOLD, "bassa", "non c'è nessun dato (regista, durata, IMDb)"),
    47: ("serie di film (anime)", HOLD, "bassa", "pagina della saga, sinossi di 432 caratteri"),
    48: ("lungometraggio da manga", INC, "media", "103 minuti: film (la pagina è intitolata al manga)"),
    49: ("lungometraggio da manga", INC, "bassa", "infobox film con durata e regista"),
    50: ("lungometraggio da manga", INC, "media", "84 minuti: film live-action"),
    51: ("progetto non realizzato", EXC, "alta", "film mai prodotto: nessuna opera da raccomandare"),
    52: ("film TV", INC, "bassa", "la pagina lo chiama «il film»; Wikidata lo dà come miniserie di 90 minuti"),
    53: ("film TV", INC, "bassa", "trama narrativa, mancano regista e IMDb"),
    54: ("lungometraggio da manga", INC, "media", "film live-action del 2014"),
    55: ("film anime", INC, "media", "regista e IMDb presenti"),
    56: ("lungometraggio da manga", INC, "media", "109 minuti: film live-action"),
    57: ("lungometraggio", INC, "bassa", "categoria film, trama narrativa, mancano regista e IMDb"),
    58: ("documentario", INC, "media", "documentario di 53 minuti"),
    59: ("progetto non realizzato", EXC, "alta", "seguito mai realizzato di Incontri ravvicinati del terzo tipo"),
    60: ("lungometraggio da manga", INC, "bassa", "regista presente; anno dell'infobox diverso da Wikidata"),
    61: ("miniserie / film in due parti", HOLD, "media", "344 minuti, uscita in sala in due film e in TV come miniserie"),
    62: ("film incompiuto", HOLD, "media", "parte del film esiste ma non è mai uscito"),
    63: ("serie anime", EXC, "media", "la sinossi inizia con «La serie parla…»: è la serie TV"),
    64: ("anime / romanzo", HOLD, "bassa", "pagina che copre romanzo, manga, anime e film; la trama è quella del romanzo"),
    65: ("manga / film", HOLD, "bassa", "il manga è del 2021, il film d'animazione del 2024; la pagina copre entrambi"),
    66: ("lungometraggio", INC, "media", "film del 2026"),
    67: ("speciale TV anime", INC, "bassa", "episodio speciale di Detective Conan, senza durata"),
    68: ("speciale TV anime", INC, "bassa", "episodio speciale di Detective Conan, senza durata"),
    69: ("film anime", INC, "media", "106 minuti: film d'animazione"),
    70: ("film anime", INC, "media", "film d'animazione di 53 minuti, regista e IMDb"),
}


def doubtful_ids() -> list[str]:
    return [json.loads(l)["film_id"] for l in (ROOT / "data/audit/classification.jsonl").open() if json.loads(l)["verdict"] == "doubtful"]


def table() -> list[dict]:
    ids = doubtful_ids()
    films = {}
    for line in (ROOT / "data/processed/films.jsonl").open():
        f = json.loads(line)
        films[f["film_id"]] = f
    if len(ids) != len(D) or set(D) != set(range(len(ids))):
        raise ValueError("the doubtful list changed: review table out of date")
    rows = []
    for i, fid in enumerate(ids):
        cat, dec, conf, why = D[i]
        f = films[fid]
        rows.append({"film_id": fid, "title": f["title"], "year": f["year"], "category": cat, "decision": dec,
                     "confidence": conf, "reason": why})
    return rows


if __name__ == "__main__":
    rows = table()
    out = ROOT / "audit" / "doubtful_review.json"
    out.write_text(json.dumps({"version": 1, "meaning": "recommended decision for each of the 71 doubtful records; none applied",
                               "records": rows}, ensure_ascii=False, indent=1) + "\n")
    from collections import Counter
    print(Counter(r["decision"] for r in rows))
