"""Deterministic Markdown report of A1, rendered from `audit_a1/results.json`."""
from __future__ import annotations

import json
from pathlib import Path

from .report import _n, _table
from .util import pct

CLASSES = ["lungometraggio", "cortometraggio", "film_tv", "serie", "episodio", "altro", "non_identificabile_via_imdb"]


def render(r: dict, a0: dict | None = None) -> str:
    st, wk, pe, dr, ml, pg, ls, nf = (r[k] for k in ("staging", "works", "people", "directors", "movielens", "italian_pages", "losses", "new_films"))
    L: list[str] = []
    w = L.append
    w("# Fase 9 — A1: acquisizione IMDb e analisi (rapporto)")
    w("")
    w("Generato da `python -m cinema_db.harness.audit.run_a1 report`. Misurato = calcolato sui file; *ipotesi* e *stima* sono dichiarate. Autorizzate e usate **solo** le quattro acquisizioni IMDb "
      "(`title.basics`, `name.basics`, `title.principals`, `title.crew`). Nessuna richiesta a TMDb, OMDb, TVmaze, Wikidata, OpenAI. Nessun database, snapshot, MovieLens o catalogo RAG modificato.")
    w("")
    # -------------------------------------------------------------- 1
    w("## 1. Acquisizione e archivio")
    rows = []
    for name, e in st["manifest"].items():
        rows.append([name, _n(e["bytes"]), e["sha256"][:16] + "…", e["retrieved_at"], e["last_modified"]])
    w(_table(["dataset", "byte", "sha256", "acquisito (UTC)", "Last-Modified del server"], rows))
    w("")
    w(f"- Archivio read-only: `cinema_db/data/imdb_snapshot/{st['snapshot']}/` con `manifest.json` (URL `https://datasets.imdbws.com/<dataset>.tsv.gz`, URL finale, stato HTTP, client). Verifica degli hash: `python -m cinema_db.harness.acquire.imdb verify`.")
    w("- Nota: `name.basics` risulta modificato il 7 novembre, gli altri tre l'8 novembre (il sito li rigenera ogni giorno): i dataset non sono un'unica istantanea atomica. Effetto atteso minimo (ipotesi).")
    b = st["basics"]
    w(f"- `title.basics`: {_n(b['rows'])} titoli; conservati nel file di analisi {_n(b['kept'])} (tipi di opera audiovisiva più tutti gli ID di interesse). Per tipo: " + ", ".join(f"{k} {_n(v)}" for k, v in b["by_type"].items()) + ".")
    w(f"- `title.crew` {_n(st['crew']['rows'])} righe (conservate {_n(st['crew']['kept'])}); `title.principals` {_n(st['principals']['rows'])} righe, conservate {_n(st['principals']['kept'])} "
      f"(titoli di cinema_db, di MovieLens e candidati delle pagine italiane); `name.basics` {_n(st['names']['rows'])} persone, conservate {_n(st['names']['kept'])}.")
    w("- File di analisi (non è il database di prodotto): `cinema_db/data/audit_a1/imdb_staging.sqlite3`, ignorato da git, ricostruibile con `run_a1 stage`.")
    w("")
    # -------------------------------------------------------------- 2
    w("## 2. Copertura IMDb sulle opere di `cinema_db`")
    found = wk["found_in_title_basics_by_kind"]
    nf_k = wk["not_in_title_basics_by_kind"]
    w(f"- Opere con ID IMDb in cinema: {_n(wk['cinema_works_with_imdb_id'])}; presenti in `title.basics`: {_n(sum(found.values()))} ({pct(sum(found.values()), wk['cinema_works_with_imdb_id'])} %). "
      f"**Non** presenti (ID probabilmente fuso o ritirato): {_n(sum(nf_k.values()))} (" + ", ".join(f"{k} {v}" for k, v in nf_k.items()) + ").")
    w(f"- Accordo dell'anno: {wk['year_agreement']}; della durata: {wk['runtime_agreement']}.")
    w(f"- Dati che IMDb darebbe dove cinema è vuoto: durata {_n(wk['imdb_fills_cinema_gaps'].get('runtime_missing_in_cinema_present_in_imdb', 0))} opere, generi {_n(wk['imdb_fills_cinema_gaps'].get('genres_missing_in_cinema_present_in_imdb', 0))}, anno {_n(wk['imdb_fills_cinema_gaps'].get('year_missing_in_cinema_present_in_imdb', 0))}.")
    w(f"- Opere di cinema segnalate adulte da IMDb: {_n(wk['works_flagged_adult'])}.")
    w(f"- Opere con **due** ID IMDb (58 in A0): {wk['double_imdb_id_classes']} → in {wk['double_imdb_id_classes'].get('exactly_one_id_known_to_imdb', 0)} casi uno dei due ID non esiste più in IMDb (ID obsoleto); in {wk['double_imdb_id_classes'].get('all_ids_known_to_imdb', 0)} esistono entrambi (due titoli IMDb distinti: candidati a duplicato o a edizioni diverse, non decidibili senza ulteriori prove).")
    w("")
    w("Tipo di opera in cinema contro tipo IMDb (le 20 combinazioni più frequenti; le discordanze sono un controllo sulla classificazione di cinema, non una correzione):")
    rows = [[k.split("|")[0], k.split("|")[1], _n(v)] for k, v in list(wk["kind_vs_imdb_type"].items())[:20]]
    w(_table(["tipo in cinema", "tipo IMDb", "opere"], rows))
    w(f"\nAd esempio {_n(sum(v for k, v in wk['kind_vs_imdb_type'].items() if k.startswith('film|') and not k.endswith('|movie')))} opere classificate `film` in cinema hanno un tipo IMDb diverso da `movie` "
      "(video, cortometraggio, film TV…): da valutare in B prima di fidarsi dell'una o dell'altra classificazione.")
    w("")
    # -------------------------------------------------------------- 3
    w("## 3. Persone e crediti")
    t = pe["persons_resolved_by_tier"]
    w(f"Metodo: ID del titolo + nome normalizzato (insieme di parole) + ruolo compatibile; l'anno di nascita conferma o smentisce. **Nessuna fusione, nessun ID assegnato**: è una misura di recuperabilità.")
    w(_table(["esito per persona", "persone", "% delle persone di cinema"],
             [["risolte con prova forte (≥2 titoli concordi, o 1 titolo + anno di nascita uguale)", _n(t.get("strong", 0)), pct(t.get("strong", 0), pe["persons_total"])],
              ["risolte con un solo titolo e senza conferma dell'anno", _n(t.get("weak_single_title_no_birth_confirmation", 0)), pct(t.get("weak_single_title_no_birth_confirmation", 0), pe["persons_total"])],
              ["conflitto: anno di nascita diverso", _n(t.get("conflict_birth_year", 0)), pct(t.get("conflict_birth_year", 0), pe["persons_total"])],
              ["conflitto: più ID IMDb candidati", _n(t.get("conflict_several_nconst", 0)), pct(t.get("conflict_several_nconst", 0), pe["persons_total"])],
              ["non risolte", _n(pe["persons_unresolved"]), pct(pe["persons_unresolved"], pe["persons_total"])]]))
    w("")
    w(f"- Persone di cinema: {_n(pe['persons_total'])}; con almeno un credito su un'opera con ID IMDb: {_n(pe['persons_with_a_credit_on_an_imdb_work'])}.")
    w(f"- Crediti di cinema: {_n(pe['credits_total'])}; su opere con ID IMDb {_n(pe['credits_on_works_with_imdb_id'])}; riconosciuti in IMDb come stessa persona e ruolo: **{_n(pe['credits_matched_to_an_imdb_person'])}** ({pct(pe['credits_matched_to_an_imdb_person'], pe['credits_total'])} %).")
    w(_table(["ruolo", "crediti in cinema", "riconosciuti in IMDb", "%", "crediti IMDb non presenti in cinema (candidati nuovi o nomi diversi)"],
             [[k, _n(v), _n(pe["matched_by_role"].get(k, 0)), pct(pe["matched_by_role"].get(k, 0), v), _n(pe["imdb_credits_not_matched_to_cinema_by_role"].get(k, 0))]
              for k, v in sorted(pe["credits_by_role"].items(), key=lambda kv: -kv[1])]))
    w("")
    w(f"- **{_n(pe['nconst_claimed_by_several_cinema_persons'])} ID IMDb di persona sono reclamati da più di una persona di cinema**: candidati a duplicato (file `candidates_nconst_shared.jsonl`), da non fondere in A1.")
    w("- Persone non risolte, per motivo misurato: " + ", ".join(f"{k.replace('_', ' ')} {_n(v)}" for k, v in pe["persons_unresolved_breakdown"].items()) +
      ". `title.principals` elenca solo i primi accreditati di ogni titolo (vedi §4), mentre cinema, da Wikidata, arriva a centinaia di nomi per film. "
      "Un ID per le persone non risolte richiederebbe un'altra fonte (nessuna autorizzata ora).")
    w("")
    # -------------------------------------------------------------- 4
    c = pe["cast_order_and_characters"]
    w("## 4. Ordine del cast e personaggi")
    dist = pe["principal_cast_per_title"]
    w(f"- Crediti di cast in cinema: {_n(c['cast_credits_total'])}; riconosciuti in IMDb: {_n(c['cast_credits_matched'])} ({pct(c['cast_credits_matched'], c['cast_credits_total'])} %), tutti con un **ordine** (`ordering`).")
    w(f"- Film con crediti di cast e ID IMDb: {_n(c['films_with_cast_credits_and_imdb_id'])}; film che acquisirebbero l'ordine per almeno un credito: {_n(c['films_that_gain_order'])} ({pct(c['films_that_gain_order'], c['films_with_cast_credits_and_imdb_id'])} %).")
    w(f"- Personaggi: disponibili per {_n(c['with_characters'])} dei crediti riconosciuti; **nuovi** per cinema (cinema non li ha) {_n(c['character_new_for_cinema'])}; dove entrambi li hanno ({_n(c['both_have_character'])}) coincidono (uguali o contenuti) in {_n(c['character_comparison'].get('agree', 0))} casi e differiscono in {_n(c['character_comparison'].get('differ', 0))} ({pct(c['character_comparison'].get('differ', 0), c['both_have_character'])} %; ipotesi: lingua o formulazione diversa).")
    w(f"- Titoli di cinema con cast principale in IMDb: mediana {dist['median']} attori per titolo (90° percentile {dist['p90']}, massimo {dist['max']}); distribuzione (10 = 10 o più): {dist['histogram']}.")
    w(f"- Crediti di cast **non** riconosciuti: {_n(c['cast_credits_total'] - c['cast_credits_matched'])}; di questi {_n(c['unmatched_cast_title_with_10_or_more_principal_cast'])} stanno su titoli i cui principali IMDb sono già 10 o più (l'elenco è troncato: sono attori oltre i primi accreditati), "
      f"solo {_n(c['unmatched_cast_title_with_fewer_than_10_principal_cast'])} su titoli con meno di 10 (possibile discrepanza di nome o di identità). Conclusione: **l'ordine è recuperabile per i primi accreditati, non per l'intero cast**.")
    w("")
    w("Regia (confronto con `title.crew`, opere di tipo film/corto/film TV con ID IMDb): " + ", ".join(f"{k} {_n(v)}" for k, v in dr.items()) + ".")
    w("")
    # -------------------------------------------------------------- 5
    w("## 5. I 61.474 titoli MovieLens mancanti, classificati con IMDb")
    cl = ml["by_class"]
    w(_table(["classe (da tipo IMDb)", "titoli", "% dei mancanti", "con ≥50 voti"],
             [[k, _n(cl.get(k, 0)), pct(cl.get(k, 0), ml["missing_total"]), _n(ml["ge50"].get(k, 0))] for k in CLASSES]))
    w("")
    w("Mappatura: `movie` → lungometraggio; `short`/`tvShort` → cortometraggio; `tvMovie`/`tvSpecial` → film TV; `tvSeries`/`tvMiniSeries` → serie; `tvEpisode` → episodio; `video`, `videoGame`, `tvPilot` → altro. Tipi IMDb: "
      + ", ".join(f"{k} {_n(v)}" for k, v in ml["by_imdb_type"].items()) + ".")
    w("")
    w("Per soglia di voti MovieLens (nessuna soglia è scelta qui):")
    w(_table(["voti ≥", "mancanti"] + ["lungom.", "corto", "film TV", "serie", "episodio", "altro", "non identif."],
             [[k, _n(v["missing"])] + [_n(v.get(c, 0)) for c in CLASSES] for k, v in sorted(ml["by_threshold"].items(), key=lambda kv: int(kv[0]))]))
    m = ml["movies"]
    w("")
    w(f"**Lungometraggi** (`movie`): {_n(m['movie_total'])}. Di questi {_n(m['movie_with_cinema_candidate_same_title_and_year'])} hanno in cinema un'opera con lo stesso titolo (primario o originale) e anno ±1 (probabile stesso film con altro ID: *candidato*, non verificato), "
      f"quindi **{_n(m['movie_without_cinema_candidate'])} sarebbero lungometraggi nuovi** per il catalogo. Durata: {m['movie_runtime_bins']}; documentari {_n(m['movie_documentary'])}; segnalati adulti {_n(m['movie_flagged_adult'])}; "
      f"anno IMDb diverso da MovieLens di più di un anno: {_n(m['movie_year_disagrees_with_movielens'])}. Per decennio: " + ", ".join(f"{k} {_n(v)}" for k, v in m["movie_by_decade"].items()) + ".")
    w("")
    w(_table(["voti ≥", "lungometraggi", "di cui senza candidato in cinema"],
             [[k, _n(v["movies"]), _n(v["without_cinema_candidate"])] for k, v in sorted(ml["movies_by_threshold"].items(), key=lambda kv: int(kv[0]))]))
    ni = ml["not_identifiable"]
    w("")
    w(f"**Non identificabili tramite IMDb**: {_n(ni['count'])} (ID assente da `title.basics`; con ID TMDb in MovieLens: {_n(ni['with_tmdb_id_in_movielens'])}); per soglia: {ni['by_threshold']}. Esempi più votati: "
      + "; ".join(f"{x['title']} ({_n(x['n'])} voti)" for x in ni["top_by_ratings"][:6]) + ". Ipotesi: ID IMDb fusi o ritirati dopo la compilazione di MovieLens (2023); si possono recuperare solo con un'altra fonte (TMDb, **non autorizzata**).")
    w("")
    # -------------------------------------------------------------- 6
    w("## 6. Pagine italiane scartate per trama breve o assente")
    tiers = pg["tiers"]
    w(f"Pagine con infobox film scartate dall'estrazione e valutate: {_n(pg['rejected_pages_evaluated'])}. Criteri (rigidi, applicati nell'ordine): **identificata** = esattamente un titolo IMDb di tipo audiovisivo con anno uguale a quello della pagina, titolo (o titolo originale) uguale e "
      "almeno un regista in comune; **dubbia** = esistono candidati ma i tre requisiti non valgono in modo unico; **nessun candidato**. Nessun criterio è stato abbassato.")
    w(_table(["stato", "pagine", "%"], [["opera identificata, senza trama", _n(tiers.get("identified_without_plot", 0)), pct(tiers.get("identified_without_plot", 0), pg["rejected_pages_evaluated"])],
                                       ["opera dubbia, da non inserire automaticamente", _n(tiers.get("dubious", 0)), pct(tiers.get("dubious", 0), pg["rejected_pages_evaluated"])],
                                       ["nessun candidato IMDb", _n(tiers.get("no_candidate", 0)), pct(tiers.get("no_candidate", 0), pg["rejected_pages_evaluated"])],
                                       ["già in cinema (stesso ID)", _n(tiers.get("already_in_cinema", 0)), pct(tiers.get("already_in_cinema", 0), pg["rejected_pages_evaluated"])]]))
    w("")
    w(f"- Identificate per tipo IMDb: {pg['new_identified_by_imdb_type']}; per motivo di scarto: {pg['by_reason']}.")
    w(f"- Pagine senza anno: {_n(pg['pages_without_year'])} (mai identificate); senza regista sulla pagina: {_n(pg['pages_without_director_on_page'])} (non possono superare il requisito del regista: restano dubbie o senza candidato).")
    w("- Lo stato «opera identificata con trama» non riguarda queste pagine: sono le 41.138 già nel catalogo RAG (hanno QID e trama).")
    w("- Queste pagine hanno ora un ID IMDb ma **non** un QID Wikidata (nessuna richiesta Wikidata): per cinema servirebbe comunque un'identità interna; la riconciliazione col QID resta aperta.")
    w("")
    v = pg["validation_on_known_pages"]
    w(f"**Verifica dei criteri su verità nota**: applicati alle {_n(v['pages_with_known_imdb_id'])} pagine del catalogo RAG di cui l'ID IMDb è già noto, i criteri identificano {_n(v.get('identified_correct', 0) + v.get('identified_wrong', 0))} pagine "
      f"(richiamo {v['recall_pct']} %) e danno l'ID giusto in {_n(v.get('identified_correct', 0))} casi: **precisione {v['precision_pct']} %** ({_n(v.get('identified_wrong', 0))} errori). Gli esiti sulle pagine scartate non sono quindi perfetti: l'errore atteso è dell'ordine di (100 − precisione) %.")
    w("")
    w(f"**Lungometraggi nuovi** (stessa regola su entrambe le vie: tipo IMDb `movie`): da MovieLens, senza candidato in cinema, {_n(nf['movielens_movies_without_cinema_candidate'])}; dalle pagine italiane identificate {_n(nf['italian_pages_identified_movies'])} "
      f"(tutti i tipi: {_n(nf['italian_pages_identified_all_types'])}); in comune {_n(nf['in_both_movies'])}; **unione {_n(nf['union_movies'])}**. Nessuna soglia di rilevanza applicata: la decisione su quanti «meritano» di entrare è per B con le tabelle sopra.")
    w("")
    # -------------------------------------------------------------- 7
    w("## 7. La perdita dei film tra fonte e build (le «88»)")
    w(f"Percorso ricostruito leggendo `cinema_db/harness/build/build.py` (non eseguito) e verificato sui record. Gli identificativi IMDb presenti in una fonte locale e assenti da cinema sono **{_n(ls['identifiers_in_local_sources_not_in_cinema'])}**, di cui **{ls['of_which_in_movielens']}** in MovieLens (le 88 di A0).")
    w(_table(["causa (primo punto di esclusione)", "88 in MovieLens", "tutti i 915"],
             [[k, _n(ls["movielens_by_cause"].get(k, 0)), _n(v)] for k, v in ls["all_by_cause"].items()]))
    w("")
    w("Lettura delle cause:")
    w("1. `series_imported_without_identifiers` — `build.series()` importa la serie ma, se `ids_reliable` è falso nel catalogo s5, **non** aggiunge né QID né IMDb: l'opera è in cinema ma senza identificativi, quindi non risulta quando si cerca per ID. È la causa dominante (67 su 88 in MovieLens). "
      f"I tipi IMDb di queste 88: {ls['movielens_by_imdb_type']} (miniserie e film TV soprattutto).")
    w("2. `series_not_imported:franchise_page_mixed_media` — `default_search_eligible` falso: pagine miste manga/anime scartate per scelta (2.032 in tutto).")
    w("3. `series_catalogue_uncertain_records_not_imported` — `uncertain.jsonl` non è un input della build.")
    w("4. `tv_movie_imported_without_identifiers` — come la 1 per `tv_movies()`.")
    w("5. Entità degli snapshot senza record di catalogo: l'entità c'è ma nessun catalogo la elenca; dove possibile la causa è la pagina scartata dall'estrazione o esclusa nella pulizia (tabella).")
    w("")
    w("Quanto IMDb **conferma** i record persi (stesso titolo e anno ±1; è un minimo, perché titoli italiani e IMDb spesso differiscono): " + ", ".join(f"{k}: {v}/{ls['all_by_cause'][k]}" for k, v in ls["imdb_confirms_title_and_year"].items() if v) + ".")
    w("Opere già presenti in cinema (stesso titolo) ma senza identificativo: " + ", ".join(f"{k}: {v}" for k, v in ls["work_present_without_identifier"].items() if v) + ".")
    w("")
    w("**Soluzione proposta (NON applicata, la pipeline non è stata modificata):** (a) per i record con `ids_reliable` falso, aggiungere l'ID IMDb e il QID come identificativi *non primari* quando IMDb conferma titolo, anno e tipo (misurato sopra), conservando la provenienza e lasciando fuori gli altri; "
      "(b) per le pagine miste manga/anime ammettere solo quelle che IMDb classifica come film o serie e confermano titolo e anno; (c) leggere `uncertain.jsonl` con la stessa conferma IMDb; (d) lasciare fuori le entità escluse in pulizia per tema (argomenti, non opere). Da decidere in B insieme alla regola di ingresso.")
    w("")
    # -------------------------------------------------------------- 8
    w("## 8. Limiti residui e acquisizioni che potrebbero servire")
    w("- **Cast**: IMDb copre l'ordine e i personaggi dei soli primi accreditati (mediana 10 per titolo). Per il cast completo restano Wikidata (senza ordine) o un'altra fonte (TMDb), non autorizzata.")
    w(f"- **Persone non risolte** ({_n(pe['persons_unresolved'])}): per la maggior parte sono comparse oltre i primi accreditati; un ID richiede un'altra fonte o l'uso di `knownForTitles` di `name.basics` (non usato in A1).")
    w(f"- **Titoli non identificabili** ({_n(ni['count'])} di MovieLens, {_n(sum(nf_k.values()))} opere di cinema): servono TMDb (ID di MovieLens) o altro.")
    w("- **Valutazioni**: `title.ratings` di IMDb **non** era tra i dataset autorizzati e non è stato scaricato; MovieLens resta l'unica fonte locale di voti.")
    w("- **Episodi e stagioni**: `title.episode` non autorizzato; i 222 mila episodi di cinema restano senza ID IMDb (76 con ID).")
    w(f"- **Pagine italiane**: l'identificazione si basa su titolo, anno e regista; le {_n(tiers.get('dubious', 0))} dubbie e le {_n(tiers.get('no_candidate', 0))} senza candidato richiederebbero Wikidata (sitelink) o TMDb.")
    w("- **Anno e tipo**: IMDb e cinema discordano in migliaia di casi (§2); la scelta della fonte prevalente per campo è una decisione di B.")
    w("- Il matching di persone e titoli è un'euristica documentata; nessuna riga è stata scritta nel database di prodotto.")
    w("")
    w("## 9. Riproducibilità e integrità")
    w("```bash")
    w("python -m cinema_db.harness.acquire.imdb fetch <dataset>    # un dataset alla volta; non riscarica se già nel manifest")
    w("python -m cinema_db.harness.acquire.imdb verify            # hash dell'archivio")
    w("python -m cinema_db.harness.audit.run_a1 stage             # archivio -> file di analisi (circa 5 minuti)")
    w("python -m cinema_db.harness.audit.run_a1 run               # analisi -> results.json e candidati")
    w("python -m cinema_db.harness.audit.run_a1 report            # questo documento")
    w("python -m pytest tests/test_imdb_acquire.py tests/test_cinema_audit_imdb.py tests/test_cinema_audit.py -q")
    w("```")
    w("Output in `cinema_db/data/audit_a1/` (ignorata da git): `results.json`, `ml_missing_classified.jsonl`, `italian_pages_classified.jsonl`, `build_losses.jsonl`, `candidates_*.jsonl`, `staging_stats.json`. Copia dei risultati: `docs/cinema_db/PHASE9_A1_RESULTS.json`.")
    w("")
    return "\n".join(L) + "\n"


def write(results_path: Path, out_path: Path) -> None:
    out_path.write_text(render(json.loads(results_path.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"report written: {out_path}")
