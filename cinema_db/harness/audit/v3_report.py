"""Deterministic reports of the v3 layer, rendered from machine-written results:
  docs/cinema_db/PHASE9_V3_REPORT.md        what the layer built, before/after coverage, recoveries, holds, sizes
  docs/cinema_db/PHASE9_RECONCILIATION.md   classification of duplicates and shared identifiers, with a merge proposal (nothing applied)
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from . import util
from .report import _n, _table
from .util import pct

DATA = util.ROOT / "cinema_db/data"
A1 = DATA / "audit_a1"
V3 = DATA / "cinema.v3.sqlite3"
SEP = DATA / "cinema.v3.separate"
REPORT = util.ROOT / "docs/cinema_db/PHASE9_V3_REPORT.md"
RECON = util.ROOT / "docs/cinema_db/PHASE9_RECONCILIATION.md"


def _mb(path: Path) -> str:
    if path.is_dir():
        total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    else:
        total = path.stat().st_size if path.exists() else 0
    return f"{total / 1_000_000:,.0f} MB".replace(",", ".")


def _jsonl(path: Path) -> list[dict]:
    return list(util.iter_jsonl(path)) if path.is_file() else []


def render_v3() -> str:
    layer = json.loads((DATA / "cinema.v3.layer_report.json").read_text())
    cmp_ = json.loads((A1 / "v3_compare.json").read_text())
    a1 = json.loads((A1 / "results.json").read_text())
    b, v, c = cmp_["base"], cmp_["v3"], layer["counts"]
    L: list[str] = []
    w = L.append
    w("# Fase 9 — Strato v3: costruzione separata, copertura e verifiche (rapporto)")
    w("")
    w("Generato da `python -m cinema_db.harness.audit.run_a1 v3report`. Il database runtime `cinema_db/data/cinema.sqlite3` **non è stato modificato** (digest `c888ebd0…`). "
      "Il file nuovo è `cinema_db/data/cinema.v3.sqlite3`, costruito da una copia con `python -m cinema_db.harness.build.imdb_layer`; non è letto dall'agente finché non si rigenerano la policy e le viste (fase F).")
    w("")
    w("## 1. Cosa è stato fatto")
    w("Ordine fisso e deterministico: (1) tabelle v3 e due nuove fonti; (2) recupero degli ID dei record con `ids_reliable=false` solo se IMDb conferma titolo, anno e tipologia; (3) ID IMDb delle persone solo con prova forte; "
      "(4) priorità IMDb per tipologia, anno, durata (il valore perdente resta in `entity_claim`); (5) valutazioni per fonte; (6) episodi collegati a IMDb con prove forti; (7) opere nuove; (8) stato, FTS, controlli di integrità.")
    w("")
    w("## 2. Copertura prima e dopo")
    rows = [
        ["opere", _n(b["works"]), _n(v["works"])], ["persone", _n(b["persons"]), _n(v["persons"])], ["crediti", _n(b["credits"]), _n(v["credits"])],
        ["crediti con ordine (`billing_order`)", _n(b["credits_with_billing_order"]), _n(v["credits_with_billing_order"])],
        ["crediti di cast con personaggio", f"{_n(b['cast_credits_with_character'])} ({pct(b['cast_credits_with_character'], b['cast_credits'])} %)", f"{_n(v['cast_credits_with_character'])} ({pct(v['cast_credits_with_character'], v['cast_credits'])} %)"],
        ["opere con ID IMDb", _n(b["works_with_imdb_id"]), _n(v["works_with_imdb_id"])], ["opere (film, corti, TV, serie) senza ID IMDb", _n(b["screen_works_without_imdb_id"]), _n(v["screen_works_without_imdb_id"])],
        ["persone con ID IMDb", _n(b["persons_with_imdb_name"]), _n(v["persons_with_imdb_name"])], ["episodi con ID IMDb", _n(b["episodes_with_imdb_id"]), _n(v["episodes_with_imdb_id"])],
        ["film con durata", _n(b["films_with_runtime"]), _n(v["films_with_runtime"])],
        ["valutazioni (righe)", "0", _n(sum(v.get("ratings_by_source", {}).values()))], ["opere con due o più valutazioni di fonti diverse", "0", _n(v.get("works_with_two_or_more_ratings", 0))],
        ["gruppi di film con stesso titolo e anno", _n(b["film_groups_with_same_title_and_year"]), _n(v["film_groups_with_same_title_and_year"])],
        ["dimensione del file", _mb(Path(DATA / "cinema.sqlite3")), _mb(V3)],
    ]
    w(_table(["misura", "v2 (runtime)", "v3"], rows))
    w("")
    w("Opere per tipo: " + "; ".join(f"{k} {_n(b['works_by_kind'].get(k, 0))} → {_n(v['works_by_kind'].get(k, 0))}" for k in ("film", "short", "tv_film", "series", "miniseries", "episode", "season", "other")) + ".")
    w("")
    w("Copertura dei film di MovieLens in `cinema_db` (per numero minimo di voti):")
    w(_table(["voti ≥", "film MovieLens", "in v2", "% v2", "in v3", "% v3"],
             [[k, _n(b["movielens_coverage_by_min_votes"][k]["movielens_films"]), _n(b["movielens_coverage_by_min_votes"][k]["in_cinema"]), b["movielens_coverage_by_min_votes"][k]["pct"],
               _n(v["movielens_coverage_by_min_votes"][k]["in_cinema"]), v["movielens_coverage_by_min_votes"][k]["pct"]] for k in b["movielens_coverage_by_min_votes"]]))
    w("")
    w("## 3. Opere nuove: regola di ingresso e vie")
    w(_table(["via", "tipo", "opere nuove"], [[k.split("|")[0], k.split("|")[1], _n(n)] for k, n in sorted(v["new_works_by_route_kind"].items())]))
    w("")
    ident = v["identification"]
    w("Affidabilità dell'identificazione (`work_status.identification`): " + ", ".join(f"{k} {_n(n)}" for k, n in ident.items()) + ". Completezza delle opere audiovisive: " + ", ".join(f"{k} {_n(n)}" for k, n in v["completeness_screen_works"].items()) +
      " (`rich` = regia, cast, genere e durata; `basic` = almeno uno; `skeleton` = nessuno).")
    w("")
    ne = _jsonl(SEP / "not_entered.jsonl")
    reasons = collections.Counter(r["reason"] for r in ne)
    w("**Non entrate nel catalogo principale** (archivio separato `cinema_db/data/cinema.v3.separate/not_entered.jsonl`, con motivo): " + ", ".join(f"{k} {_n(n)}" for k, n in reasons.most_common()) + ". "
      "I tipi fuori regola sono video (musicali o direct-to-video), serie, episodi e altro; gli adulti e le coppie titolo+anno già presenti (*reconciliation hold*) restano fuori finché non c'è una decisione.")
    dub = a1["dubious_pages"]
    r2 = dub["rule_unique_title_year"]
    w(f"- **Pagine italiane dubbie** ({_n(dub['dubious_pages'])}): {_n(dub['recovered_by_rule'])} risolte con i dati IMDb già acquisiti da una regola (un solo titolo IMDb entro un anno, con l'anno esatto della pagina), la cui precisione sulle pagine con ID noto è {r2['precision_pct']} % "
      f"({_n(r2.get('rule_correct', 0))} giusti, {_n(r2.get('rule_wrong', 0))} sbagliati su {_n(r2.get('rule_applies', 0))}; soglia che mi sono dato: {r2['required_precision_pct']} %). Sono marcate `imdb_itwiki_page_rule` / `imdb_title_year_unique`, quindi distinguibili e ritirabili. "
      f"Restano nell'archivio separato {_n(dub['left_in_archive'])} pagine con candidati e motivo: " + ", ".join(f"{k.replace('_', ' ')} {_n(n)}" for k, n in dub["by_reason"].items()) + " (conteggi sulle 8.842).")
    w("")
    w("## 4. Correzione dei record con `ids_reliable=false`")
    rec = _jsonl(SEP / "recovered_identifiers.jsonl")
    w(f"Candidati (record del catalogo serie importati senza ID, con IMDb non ancora in cinema): {_n(c.get('recovery_candidates', 0))}. **Recuperati: {_n(c.get('recovered_identifiers', 0))}** (con QID: {_n(c.get('recovered_qids', 0))}). "
      "Non confermati: " + ", ".join(f"{k.split(':', 1)[1]} {_n(n)}" for k, n in sorted(c.items()) if k.startswith("recovery_not_confirmed:")) + ". I non confermati con un record IMDb restano come candidati `ids_reliable_false_unconfirmed`.")
    w("Criterio: titolo uguale (anche senza qualificatore tra parentesi), anno entro uno, tipo IMDb televisivo (`tvSeries`, `tvMiniSeries`, `tvMovie`, `tvSpecial`). Tipi dei recuperati: " +
      ", ".join(f"{k} {n}" for k, n in collections.Counter(r["imdb_type"] for r in rec).most_common()) + ". Elenco completo in `cinema.v3.separate/recovered_identifiers.jsonl`.")
    losses = _jsonl(A1 / "build_losses.jsonl")
    mixed = [r for r in losses if r["cause"] == "series_not_imported:franchise_page_mixed_media"]
    film_like = [r for r in mixed if r["imdb_type"] in ("movie", "short", "tvMovie", "tvSpecial", "tvShort")]
    w(f"**Pagine miste manga/anime**: {len(mixed)} con un ID IMDb; tipo IMDb: " + ", ".join(f"{k or '(assente)'} {n}" for k, n in collections.Counter(r["imdb_type"] for r in mixed).most_common()) +
      f". Solo {len(film_like)} sono di un tipo cinematografico e **nessuna** supera la conferma di titolo e anno: ne è entrata 0. Le {sum(1 for r in mixed if r['imdb_type'] in ('tvSeries', 'tvMiniSeries'))} serie non entrano (decisione del proprietario).")
    w("")
    w("## 5. Priorità tra fonti: tipologia, anno, durata")
    cl = v.get("claims_by_field", {})
    w(f"- Tipologia cambiata (IMDb `titleType`): {_n(c.get('kind_changed', 0))} opere; valore precedente in `entity_claim` ({_n(cl.get('kind', 0))}). Tipi IMDb non mappabili (video, videogioco, episodio, pilot) o opere con figli: kind invariato e tipo IMDb registrato come claim `imdb_title_type` ({_n(cl.get('imdb_title_type', 0))}).")
    w(f"- Anno (IMDb `startYear`): cambiato su {_n(c.get('year_changed', 0))} opere (valore precedente conservato), compilato su {_n(c.get('year_filled', 0))}; data di uscita incompatibile spostata in `entity_claim`: {_n(c.get('release_date_moved_to_claim', 0))}.")
    w(f"- Durata (IMDb `runtimeMinutes`): cambiata su {_n(c.get('runtime_changed', 0))}, compilata su {_n(c.get('runtime_filled', 0))} (in gran parte episodi). Dove IMDb non ha il dato resta quello di `cinema_db`.")
    w("")
    w("## 6. Persone e crediti")
    w(f"- ID IMDb attaccati con prova forte: {_n(c.get('person_ids_attached_strong', 0))}. Candidati non attaccati (`external_id_candidate`): " + ", ".join(f"{k} {_n(n)}" for k, n in sorted(v["candidates_by_tier"].items())) + ".")
    w(f"- Persone create dalle opere nuove (ognuna con il suo ID IMDb): {_n(c.get('people_created', 0))}. Crediti aggiunti alle opere nuove: {_n(c.get('credits_added_to_new_works', 0))}. "
      f"**Crediti trattenuti** perché la persona IMDb è un candidato di una persona esistente (nessun duplicato creato): {_n(c.get('credits_held_nconst_is_a_candidate_of_an_existing_person', 0))}; categorie non mappate (`casting_director`): {_n(c.get('credit_category_not_mapped:casting_director', 0))}.")
    w(f"- Crediti già esistenti che hanno ricevuto l'ordine: {_n(c.get('credits_given_billing_order', 0))}; il personaggio: {_n(c.get('credits_given_character', 0))} (mai sovrascritto).")
    w(f"- Le persone di `cinema_db` senza ID IMDb restano distinguibili: nessuna riga `imdb_name` in `external_id` (con candidati dove esistono). Persone senza ID IMDb nel v3: {_n(v['persons'] - v['persons_with_imdb_name'])}.")
    w("")
    w("## 7. Valutazioni ed episodi")
    w("- Valutazioni per fonte: " + ", ".join(f"{k} {_n(n)}" for k, n in v["ratings_by_source"].items()) + f" (IMDb: {_n(c.get('ratings_imdb', 0))} opere + {_n(c.get('ratings_imdb_episodes', 0))} episodi). Ogni riga ha scala, voti e data (`as_of`); nessuna media né conversione.")
    w(f"- Episodi: {_n(c.get('episodes_of_series_with_imdb_id', 0))} episodi di cinema appartengono a serie con ID IMDb; collegati con prove forti {_n(c.get('episodes_matched_strong', 0))} "
      f"(numero + anno {_n(c.get('episode_match:number+year', 0))}, numero + titolo {_n(c.get('episode_match:number+title', 0))}, titolo unico {_n(c.get('episode_match:title_unique', 0))}); "
      f"solo-numero (candidati) {_n(c.get('episodes_weak_candidates', 0))}. Episodi presenti in IMDb ma **non** in cinema per le stesse serie: {_n(c.get('imdb_episodes_not_in_cinema', 0))} (non inseriti: decisione aperta).")
    w("")
    w("## 8. Duplicati: controlli")
    w(f"- Coppie nuovo-vecchio con stesso titolo e anno: {v['new_vs_old_same_title_year']} (devono essere poche e spiegate: un titolo nuovo non può coincidere con un'opera esistente senza essere trattenuto).")
    w(f"- Gruppi di film con lo stesso titolo e anno: {b['film_groups_with_same_title_and_year']} → {v['film_groups_with_same_title_and_year']}. Quasi tutti sono omonimi legittimi (registi diversi in IMDb): la verifica per regista dà la distribuzione nel rapporto di riconciliazione.")
    w(f"- Verifica per regista dei gruppi con stesso titolo e anno (opere audiovisive): {v['same_title_year_groups_by_director']}.")
    w(f"- Titoli MovieLens/pagine con lo stesso titolo e anno di un'opera esistente, **trattenuti**: {_n(c.get('not_entered:reconciliation_hold_same_title_and_year_in_cinema', 0))}; per regista: stesso regista {_n(c.get('hold:same_director', 0))} (probabilmente lo stesso film; "
      f"in {_n(c.get('hold:same_director_and_the_existing_work_has_no_imdb_id', 0))} casi l'opera esistente non ha ID IMDb: l'ID si potrebbe attaccare), registi diversi {_n(c.get('hold:different_directors', 0))} (probabili omonimi), regista ignoto {_n(c.get('hold:director_unknown', 0))}. "
      f"ID IMDb di MovieLens attaccati come alias non primari tramite lo stesso ID TMDb: {_n(c.get('imdb_alias_attached_through_the_same_tmdb_id', 0))}.")
    w("- `foreign_key_check`, `integrity_check`, coerenza FTS e invarianti della build: superati (la costruzione si interrompe altrimenti). Riproducibilità: due costruzioni con gli stessi input danno lo stesso digest (test `tests/test_cinema_imdb_layer.py`).")
    w("")
    w("## 9. Dimensioni degli archivi")
    w(_table(["archivio", "dimensione"], [["cinema.sqlite3 (runtime, invariato)", _mb(DATA / "cinema.sqlite3")], ["cinema.v3.sqlite3", _mb(V3)], ["archivi separati v3", _mb(SEP)],
                                           ["imdb_snapshot (6 dataset .gz originali)", _mb(DATA / "imdb_snapshot")], ["audit_a1 (file di analisi IMDb e candidati)", _mb(A1)], ["audit_a0", _mb(DATA / "audit_a0")],
                                           ["movielens32m.sqlite3 (invariato)", _mb(util.MOVIELENS_DB)]]))
    w("")
    w("## 10. Stato di verifica (checkpoint del 2026-11-08)")
    w("**Verificato [V] su questo file** (`cinema_db/data/cinema.v3.sqlite3`, digest `8760f0fdbd003fdb…`, 963.887.104 byte, schema 3, `builder = imdb_layer/1`): `foreign_key_check` vuoto, `integrity_check` ok, coerenza FTS e invarianti (la costruzione si ferma altrimenti); due costruzioni consecutive con gli stessi input hanno lo stesso digest; "
      "la mappa `docs/cinema_db/schema_v3.html` coincide con lo schema SQLite reale (36 tabelle più la virtuale FTS, 20 viste, 76 gruppi di chiavi esterne, 65 indici, colonne, chiavi primarie e conteggi); il file runtime `cinema.sqlite3` (digest `c888ebd0f6cf953f…`) è invariato; suite richiesta da AGENTS.md: 2.661 passati, 1 saltato.")
    w("**Stime [S]**: l'errore atteso della regola «titolo unico» (circa 0,8 % su 6.424 opere) è la stima da una misura su pagine di ID noto; la distribuzione omonimi/duplicati per regista confronta nomi normalizzati e può sbagliare con traslitterazioni.")
    w("**Ipotesi [I]**: i 719 titoli trattenuti con registi diversi sono omonimi (non verificato); i 3.576 episodi «solo numero» sono probabilmente gli stessi episodi con anno diverso (non verificato); l'effetto di `name.basics` più vecchio di un giorno è trascurabile.")
    w("**Non verificato**: l'uso del v3 da parte di `cinema_sql` (viste e policy non rigenerate); la qualità semantica dei personaggi IMDb rispetto a quelli italiani (differiscono nel 18 % dei casi con entrambi); i dati delle opere nuove contro una fonte indipendente (nessun campione a mano).")
    w("**Difetto noto non corretto**: per le 58 opere con due ID IMDb la priorità su tipologia, anno e durata è stata applicata a entrambi gli ID in ordine alfabetico, quindi vale l'ultimo ID elaborato (l'altro valore finisce in `entity_claim`). Va applicata al solo ID primario: da correggere in `imdb_layer.py` prima di una ricostruzione definitiva.")
    w("**Attenzione ai file**: la cartella del progetto è sul Desktop con iCloud attivo. Dopo la costruzione finale il sistema ha rinominato il file corretto in `cinema.v3 2.sqlite3` e lasciato come `cinema.v3.sqlite3` la prima costruzione (digest `54629e6e66218d15…`, 384.708 opere, codice precedente). Sono stati rinominati: la prima costruzione è ora `cinema.v3.first_build.sqlite3` (superata, non usare) e il file corretto è tornato `cinema.v3.sqlite3`. **Dopo ogni costruzione verificare il digest** (`python -m cinema_db.harness.build.imdb_layer` lo scrive anche in `cinema.v3.layer_report.json`).")
    w("")
    return "\n".join(L) + "\n"


def render_reconciliation() -> str:
    s = json.loads((A1 / "reconciliation/summary.json").read_text())
    L: list[str] = []
    w = L.append
    w("# Fase 9 — Riconciliazione: classificazione dei duplicati e degli identificativi condivisi")
    w("")
    w("**Nessuna entità è stata modificata e nessuna fusione eseguita.** Questa è una classificazione con prove e una proposta. Dati: `cinema_db/data/audit_a1/reconciliation/*.jsonl` (per ogni caso: entità, identificativi, prove, classe, rischio di fusione errata, azione proposta).")
    w("")
    names = {"shared_nconst": "430 ID IMDb di persona reclamati da più persone di cinema", "double_imdb_id": "58 opere con due ID IMDb", "person_pairs_strong": "256 coppie di persone (stesso nome, stesso ruolo nella stessa opera)"}
    for key, title in names.items():
        w(f"## {title}")
        w(_table(["classe", "casi"], [[k, _n(n)] for k, n in s[key]["by_class"].items()]))
        w("")
        w("Rischio di fusione errata: " + ", ".join(f"{k} {_n(n)}" for k, n in s[key]["by_merge_risk"].items()) + ".")
        rows = _jsonl(A1 / f"reconciliation/{key}.jsonl")
        shown: dict[str, dict] = {}
        for r in rows:
            shown.setdefault(r["class"], r)
        for cls, r in shown.items():
            brief = {k: r[k] for k in r if k in ("nconst", "work_id", "persons", "imdb_ids", "qids", "birth_years", "imdb_birth", "entities", "details", "imdb_tiers", "evidence")}
            w(f"- Esempio `{cls}`: `{json.dumps(brief, ensure_ascii=False)[:420]}` → {r['proposed_action']}.")
        w("")
    w("## Proposta di riconciliazione (da approvare, non applicata)")
    w("1. **Identificativi condivisi**: dove l'anno di nascita decide (`id_belongs_to_one_person_birth_year_decides`) l'ID va alla sola persona coerente; le altre restano senza ID e con il candidato registrato. Dove non c'è prova (`homonym_or_split_no_proof`) nessuno riceve l'ID.")
    w("2. **Persone doppie**: le coppie `duplicate_confirmed_by_imdb_same_person_id` (stessa persona IMDb per entrambe) sono candidate alla fusione in una **build nuova**, con una mappa `canonical_entity_id`, conservando entrambi i QID come identificativi e il nome dell'entità superstite; sopravvive l'entità con anno di nascita o con più crediti. Le `homonym_*` non si toccano mai.")
    w("3. **Opere con due ID IMDb**: `stale_id_one_unknown_to_imdb` → l'ID noto a IMDb diventa primario, l'altro resta non primario; `imdb_has_two_entries_same_title_year_type` → entrambi gli ID sulla stessa opera; `different_titles_possible_conflation_of_two_works` → **nessuna fusione**, candidate a *scissione* dell'opera in una build nuova (l'elemento Wikidata ne unisce due).")
    w("4. Prima e dopo ogni build di riconciliazione: `foreign_key_check`, conteggio di crediti, relazioni e ID per entità prima/dopo, 100 interrogazioni campione identiche; il file attuale resta come `.previous`.")
    w("")
    w("## Decisioni e questioni aperte (checkpoint del 2026-11-08)")
    w("**Approvato dal proprietario**: nessuna fusione automatica; classificare i casi con entità, identificativi, prove, classe proposta e rischio; preparare una proposta; eseguire le fusioni **solo** in una build nuova con controlli FK e verifica delle relazioni prima/dopo. Nessuna regola di fusione è stata approvata.")
    w("**Non ancora deciso (proposte di questo documento)**: tutte le azioni della tabella «Proposta di riconciliazione». Nel v3 prototipo NON sono stati attaccati ID di persona condivisi tra più entità (restano candidati `shared_by_several_entities`), nessuna persona è stata fusa, nessuna opera con due ID IMDb è stata modificata né scissa, e nessuna entità è stata cancellata.")
    w("**Fatto nel v3 senza essere una fusione**: 25 ID IMDb di MovieLens attaccati come alias non primari a un'opera esistente perché MovieLens e il catalogo danno lo stesso ID TMDb (identificazione certa da ID locali); 237 ID recuperati per record con `ids_reliable=false` confermati da IMDb.")
    w("**Questioni aperte**: (1) approvare le classi `duplicate_confirmed_by_imdb_same_person_id` (125 coppie) come candidate alla fusione in una build di riconciliazione; (2) decidere come trattare le 25 opere con due ID IMDb di titoli diversi (scissione?); (3) decidere se attribuire l'ID alla persona coerente per anno di nascita nelle 205 `id_belongs_to_one_person_birth_year_decides`; (4) stabilire il sopravvissuto e la mappa `canonical_entity_id` (non esiste ancora nello schema); (5) i 1.656 titoli trattenuti (26 con lo stesso regista, di cui 6 su opere senza ID IMDb) sono un secondo insieme di candidati, in `cinema.v3.separate/not_entered.jsonl`.")
    w("")
    return "\n".join(L) + "\n"


def write() -> None:
    REPORT.write_text(render_v3(), encoding="utf-8")
    RECON.write_text(render_reconciliation(), encoding="utf-8")
    print(f"written: {REPORT}, {RECON}")
