"""Phase 6: the individual decisions still open after PHASE5_REPORT, with the evidence that changed or confirmed them.
Everything here is a PROPOSAL read from page text, infobox fields and Wikidata classes; nothing is applied to the catalogue.

Three tables:
  REVISED   the 27 doubtful records (11 proposed exclusions + 16 on hold) re-read with the infobox titles
  HYBRIDS   the 46 film-vs-series hybrids, one decision each
  REINSTATE records among the 259 certain exclusions that look like real films (candidates to take OUT of the exclusion list)
Decision words: includere / escludere / sospeso. `sospeso` = the owner must decide; the build keeps the record until then."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INC, EXC, HOLD = "includere", "escludere", "sospeso"

# film_id -> (decision, confidence, nature of the work, reason, consequence of the decision)
REVISED: dict[str, tuple[str, str, str, str, str]] = {}   # filled from DOUBTFUL_IDX below (keyed by position in the doubtful list)

DOUBTFUL_IDX: dict[int, tuple[str, str, str, str, str]] = {
    0: (EXC, "media", "serie anime (l'infobox descrive il corto del 1995, 26 min)", "la trama è quella della serie TV; il corto «Quello stesso giorno a casa di Yū» esiste ma non è descritto dalla pagina", "si perde il corto come film; la serie non compare tra i film"),
    2: (EXC, "media", "serie anime (l'infobox descrive il film del 1996)", "trama di serie TV; nessuna durata", "si perde il film Gokinjo Monogatari come voce autonoma"),
    6: (EXC, "alta", "serie anime (l'infobox descrive il film «The Movie», 20 min)", "trama della serie TV Digimon Savers", "si perde il film come voce autonoma"),
    8: (EXC, "media", "serie anime (l'infobox descrive il film del 2001, 50 min)", "trama della serie TV Digimon Tamers", "si perde il film come voce autonoma"),
    23: (EXC, "alta", "serie anime (l'infobox descrive il film del 2000, 65 min)", "trama della serie TV Digimon Adventure 02", "si perde il film come voce autonoma"),
    31: (EXC, "alta", "serie anime (l'infobox descrive il film del 1999)", "trama della serie TV, 30 min = episodio", "si perde il film come voce autonoma"),
    33: (EXC, "media", "miniserie TV cilena di Raúl Ruiz", "uscita come serie TV; trama di 610 caratteri", "un'opera d'autore di Ruiz non compare"),
    43: (EXC, "alta", "miniserie tedesca in 3 puntate", "l'infobox dà «135 min (episodio)»", "nessuna"),
    51: (EXC, "alta", "film mai realizzato (Lynch)", "descrive un progetto, non un'opera visibile", "la ricerca non potrà più proporre un film che non esiste"),
    59: (EXC, "alta", "seguito mai realizzato", "descrive un progetto, non un'opera", "come sopra"),
    63: (EXC, "media", "serie anime (l'infobox descrive il film del 2022, 102 min)", "la sinossi inizia con «La serie parla…»", "si perde il film come voce autonoma"),
    1: (HOLD, "bassa", "OVA a episodi", "nessuna durata né infobox; IMDb e regista presenti", "se incluso compare come film un OVA a più episodi; se escluso nessuna perdita certa"),
    5: (EXC, "media", "serie anime (l'infobox descrive il film del 1997, 30 min)", "3.774 caratteri di trama della serie TV Toei", "si perde il film come voce autonoma"),
    19: (EXC, "media", "serie anime (l'infobox descrive «Baldios – The Movie»)", "la trama cita puntate e serie", "si perde il film come voce autonoma"),
    20: (HOLD, "media", "OVA di 13 episodi (esiste anche il film montato)", "serve la tua regola sugli OVA: la pagina è l'OVA, l'infobox il film", "incluso: una serie OVA appare come film; escluso: manca un'opera del franchise"),
    25: (HOLD, "bassa", "OVA di 4 episodi (esiste una versione film)", "nessun infobox; IMDb presente", "come sopra"),
    34: (EXC, "media", "serie anime breve (22 min)", "regista e produttore solo di serie; nessun IMDb", "nessuna perdita certa"),
    38: (EXC, "media", "OVA di 5 episodi", "l'infobox dà «60 min (episodio) / 300 min (totale)»", "nessuna; la raccolta in film non è descritta dalla pagina"),
    40: (EXC, "bassa", "pagina sulla saga di 7 film", "è una pagina di serie di film, trattata come argomento come le altre 9", "i singoli film non sono voci; coerente con «Saw (serie di film)»"),
    41: (HOLD, "bassa", "OVA speciale (verosimilmente un solo episodio)", "6.359 caratteri di trama, IMDb presente, nessuna durata", "se incluso è probabilmente corretto"),
    44: (INC, "media", "film live-action del 2008 (regia e 13 attori nell'infobox)", "Wikidata lo dà come serie di romanzi, la pagina è del film", "nessuna"),
    46: (HOLD, "bassa", "anime, tipo non determinabile", "nessun dato (regista, durata, IMDb)", "voce senza dati: bassa utilità comunque"),
    47: (HOLD, "bassa", "saga/franchise anime (film del 2010 e serie)", "432 caratteri di trama, nessun dato", "se escluso si perde al più un film d'animazione"),
    61: (HOLD, "media", "serie di Bellocchio uscita in sala come due film (330 min) e in TV come miniserie in 6 puntate", "è la tua regola sulle miniserie a decidere; l'infobox è del film", "incluso: opera d'autore presente, ma è una miniserie; escluso: assente"),
    62: (EXC, "media", "film d'animazione incompiuto (1984, non uscito)", "non esiste un'opera fruibile; è una voce storica", "nessuna per l'utente"),
    64: (EXC, "bassa", "romanzo/manga/anime (la trama è del romanzo)", "pagina di franchise letterario", "il film live-action del 2023 non compare"),
    65: (HOLD, "bassa", "manga one-shot (2021) e film d'animazione (2024) nella stessa pagina", "la trama vale per entrambi; l'anno è quello del manga", "incluso: il film esiste; ma l'anno è sbagliato"),
}

# film_id -> (decision, confidence, nature, reason)
HYBRIDS: dict[str, tuple[str, str, str, str]] = {
    # A. miniseries + TV film
    "Q3937683": (HOLD, "bassa", "sceneggiato RAI (1975)", "nessun dato di durata; non è chiaro se in più puntate"),
    "Q3931217": (EXC, "media", "miniserie BBC in 4 puntate", "55 minuti = episodio"),
    "Q2322509": (HOLD, "media", "film TV canadese in due parti (230 min)", "la pagina lo chiama «film», ma è andato in onda in due serate"),
    "Q3870500": (EXC, "bassa", "sceneggiato TV italiano (Squitieri)", "sceneggiato in più puntate secondo Wikidata; nessuna durata"),
    "Q1613225": (INC, "media", "film TV (2008) di 144 minuti", "un solo film"),
    "Q9262969": (EXC, "alta", "miniserie in 4 puntate (Uccelli di rovo)", "è l'esempio tipico"),
    "Q248392": (EXC, "media", "miniserie in due parti (TNT)", "180 minuti trasmessi in due serate"),
    "Q662261": (HOLD, "media", "film TV in due parti (155 min)", "lo stesso caso di «Karol – Un uomo diventato papa» (180 min), che oggi resta tra i film"),
    "Q3888794": (EXC, "media", "miniserie RAI in due parti", "nessuna durata"),
    "Q660237": (HOLD, "media", "film TV NBC in due parti (150 min)", "evento in due serate"),
    "Q481467": (HOLD, "media", "film TV di Fassbinder in due parti", "considerato un film d'autore; 212 minuti in due puntate"),
    "Q2450626": (INC, "media", "film TV (172 min)", "singolo film Hallmark"),
    "Q3790374": (EXC, "alta", "sceneggiato in più puntate", "la trama dice «Lo sceneggiato narra…»"),
    "Q565293": (EXC, "media", "miniserie ABC in due parti", "189 minuti in due serate"),
    "Q228396": (EXC, "media", "miniserie NBC in due parti", "164 minuti in due serate"),
    "Q2095183": (EXC, "alta", "miniserie BBC in 3 puntate", "nessuna durata"),
    "Q902821": (INC, "media", "film TV BBC (114 min)", "un solo film"),
    "Q538952": (EXC, "media", "miniserie USA Network in due parti", "177 minuti in due serate"),
    "Q2421745": (EXC, "media", "miniserie NBC in due parti", "170 minuti in due serate"),
    "Q4754259": (INC, "media", "film TV TNT (167 min)", "infobox film presente"),
    # B. miniseries + other type of film
    "Q3249691": (EXC, "alta", "serie TV in 11 parti (Heimat)", "924 minuti"),
    "Q733823": (HOLD, "bassa", "documentario BBC in due puntate", "documentario televisivo; manca la durata"),
    "Q2091643": (INC, "alta", "film di Manoel de Oliveira (262 min)", "distribuito al cinema, esiste una versione in 6 puntate"),
    "Q1964231": (INC, "alta", "film di Michalkov", "film per il cinema"),
    "Q2986126": (HOLD, "media", "ciclo documentaristico di Joris Ivens in 12 parti (763 min)", "la pagina italiana lo tratta come film"),
    "Q46995368": (INC, "media", "speciale TV animato di 22 minuti", "un solo speciale"),
    "Q22986649": (INC, "media", "film olandese del 2016 (130 min)", "esiste anche una versione serie"),
    "Q7258905": (INC, "alta", "film sovietico", "film per il cinema"),
    "Q111420354": (HOLD, "bassa", "film TV italiano sull'AIDS (200 min)", "durata da miniserie, titolo «film»"),
    # C. manga / anime classes
    "Q2608646": (INC, "media", "film del 2007 (91 min)", "infobox film con regista"),
    "Q2542211": (INC, "media", "OVA di lungometraggio di Kawajiri", "singola opera di circa 80 minuti"),
    "Q980413": (EXC, "media", "serie anime TV", "nessun infobox, nessuna durata"),
    "Q2699416": (INC, "media", "film live-action (83 min)", "infobox film con regista"),
    "Q2077536": (INC, "media", "film d'animazione del 1983 (132 min)", "infobox film con regista"),
    "Q2067724": (HOLD, "bassa", "serie o film live-action Sukeban Deka", "nessun dato di regia né durata"),
    "Q11311160": (INC, "media", "film del 2004 (103 min)", "infobox film con regista"),
    # D. other TV-series classes
    "Q3055315": (INC, "media", "film di Liv Ullmann (200 min, 5 parti)", "infobox film; nella versione italiana tagliato"),
    "Q3790916": (EXC, "media", "miniserie RAI in due parti", "nessuna durata"),
    "Q5359283": (INC, "media", "film in tre episodi (72 min)", "film compilation, non una serie"),
    "Q3855269": (INC, "bassa", "film iraniano (100 min)", "infobox film"),
    "Q13435381": (INC, "media", "film TV (1982)", "singolo film TV"),
    "Q17479060": (INC, "alta", "film TV (92 min)", "un solo film"),
    "Q5507059": (INC, "media", "film TV (Bob Clark)", "un solo film"),
    "Q115563567": (INC, "media", "documentario", "documentario unico"),
    "Q5228936": (INC, "media", "film TV danese (120 min)", "infobox film"),
    "Q106912386": (INC, "media", "film TV francese", "film televisivo"),
}

# Records inside the 259 certain exclusions that look like real films: proposal to TAKE THEM OUT of the exclusion list
REINSTATE: dict[str, tuple[str, str, str]] = {
    "Q21015465": (INC, "alta", "film giapponese del 2012 (122 min, regista, IMDb, infobox film): Wikidata lo dà come opera letteraria"),
    "Q11514891": (INC, "alta", "film giapponese del 2006 (130 min, regista, infobox film): stessa causa"),
    "Q3505872": (INC, "alta", "film di Benoît Jacquot del 2021 (91 min, infobox film): stessa causa"),
    "Q567884": (HOLD, "media", "Another: infobox film con regista ma l'anno 2009 è del romanzo; il film live-action è del 2012"),
    "Q1775616": (HOLD, "media", "Il vento dell'Amnesia: anime (OVA) con infobox film; l'anno è quello del romanzo"),
    "Q97369824": (HOLD, "media", "The Connection: la pagina è intitolata allo spettacolo teatrale, ma l'infobox è il film di Shirley Clarke (1961)"),
    "Q43401515": (INC, "media", "Jesus Christ Superstar Live in Concert: la pagina lo chiama «film TV» (come «Grinch Musical Live!», che è tenuto)"),
    "Q2263018": (HOLD, "media", "Fantaghirò (1991): il titolo dice «miniserie», ma i sequel Fantaghirò 2, 4 e 5 sono tenuti tra i film TV: incoerenza da sciogliere"),
}


def revised_table() -> list[dict]:
    """The 27 records of REVISED with their film_id, title and year, checked against the doubtful list."""
    from .doubtful_review import doubtful_ids
    ids = doubtful_ids()
    films = _films()
    out = []
    for idx, (dec, conf, nature, why, cons) in sorted(DOUBTFUL_IDX.items()):
        fid = ids[idx]
        out.append({"film_id": fid, "title": films[fid]["title"], "year": films[fid]["year"], "decision": dec,
                    "confidence": conf, "nature": nature, "reason": why, "consequence": cons})
    return out


def _films() -> dict[str, dict]:
    return {json.loads(l)["film_id"]: json.loads(l) for l in (ROOT / "data/processed/films.jsonl").open()}


def hybrid_table() -> list[dict]:
    films = _films()
    groups = json.loads((ROOT / "audit/series_class_hybrids.json").read_text())["groups"]
    ids = [x["film_id"] for g in groups.values() for x in g]
    if set(ids) != set(HYBRIDS) or len(ids) != 46:
        raise ValueError("the hybrid list changed: decisions out of date")
    return [{"film_id": i, "title": films[i]["title"], "year": films[i]["year"], "decision": HYBRIDS[i][0],
             "confidence": HYBRIDS[i][1], "nature": HYBRIDS[i][2], "reason": HYBRIDS[i][3]} for i in ids]


def reinstate_table() -> list[dict]:
    films = _films()
    return [{"film_id": i, "title": films[i]["title"], "year": films[i]["year"], "decision": d, "confidence": c, "reason": r}
            for i, (d, c, r) in REINSTATE.items()]


if __name__ == "__main__":
    from collections import Counter
    out = {"version": 1, "meaning": "open decisions after PHASE5; PROPOSALS, none applied",
           "doubtful_revised": revised_table(), "hybrids": hybrid_table(), "reinstate_from_exclusions": reinstate_table()}
    (ROOT / "audit" / "decisions.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    for k in ("doubtful_revised", "hybrids", "reinstate_from_exclusions"):
        print(k, len(out[k]), dict(Counter(r["decision"] for r in out[k])))
