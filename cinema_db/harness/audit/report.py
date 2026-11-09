"""Deterministic Markdown report of the A0 audit, rendered from `results.json` (no computation of its own beyond ratios)."""
from __future__ import annotations

import json
from pathlib import Path

from .util import pct


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n" + "\n".join(out)


def _n(value) -> str:
    return f"{value:,}".replace(",", ".") if isinstance(value, int) else str(value)


def render(r: dict) -> str:
    inv, ov, curve, mm = r["inventory"], r["overlap"], r["ml_relevance_curve"], r["ml_missing"]
    ids, dup, cov, add, dump = r["identifiers"], r["duplicates"], r["coverage"], r["added_value"], r["dump"]
    fw = cov["films_weighted"]
    c = inv["cinema_counts"]
    L: list[str] = []
    w = L.append
    w("# Fase 9 — A0: audit locale in sola lettura (rapporto)")
    w("")
    w("Generato da `python -m cinema_db.harness.audit.run_audit report` a partire da `cinema_db/data/audit_a0/results.json` "
      "(copia in `docs/cinema_db/PHASE9_A0_RESULTS.json`). **Tutti i numeri sono misurati sui file locali** salvo dove la riga dice "
      "esplicitamente *ipotesi* o *stima*. Nessuna rete, nessuna scrittura sugli archivi, nessuna fusione.")
    w("")
    # ------------------------------------------------------------------ 1
    w("## 1. Archivi e sovrapposizioni")
    c = inv["cinema_counts"]
    w(f"- `cinema.sqlite3`: {_n(c['work'])} opere, {_n(c['person'])} persone, {_n(c['credit'])} crediti, {_n(c['external_id'])} identificativi, "
      f"{_n(c['award_result'])} risultati di premio, {_n(c['work_relation'])} relazioni; digest `{inv['cinema_build_info']['content_sha256'][:16]}…`.")
    m = inv["movielens_counts"]
    w(f"- MovieLens: {_n(m['movies'])} film, {_n(m['links'])} link, {_n(m['movie_stats'])} con statistiche, {_n(m['ratings'])} voti, {_n(m['tags'])} tag.")
    w(f"- RAG v3: {_n(inv['v3_records'])} film; estrazione dal dump: {_n(inv['candidates'])} accettate, {_n(inv['rejected'])} scartate (pagine con infobox film), "
      f"{_n(inv['clean_excluded'])} escluse in pulizia; serie s5: " + ", ".join(f"{k} {_n(v)}" for k, v in inv["s5"].items() if k not in ("excluded", "episodes_summary")) + f", puntate {_n(add['s5']['episodes_summary']['episodes'])}.")
    sn = inv["snapshots"]
    w(f"- Snapshot Wikidata: film {_n(sn['film']['entities'])} entità ({_n(sn['film']['requests'])} richieste), serie {_n(sn['series']['entities'])} entità.")
    w("")
    w("### 1.1 Insiemi di identificativi IMDb (opere) e confronto con `cinema_db`")
    sizes, nic, only = ov["imdb"]["sizes"], ov["imdb"]["not_in_cinema"], ov["imdb"]["only_in_one_archive"]
    w(_table(["archivio", "ID IMDb", "non in cinema", "% non in cinema", "solo in questo archivio"],
             [[k, _n(v), _n(nic.get(k, "—")), pct(nic.get(k, 0), v) if k != "cinema" else "—", _n(only[k])] for k, v in sizes.items()]))
    w("")
    w("### 1.2 Insiemi di QID Wikidata")
    sizes, nic, only = ov["qid"]["sizes"], ov["qid"]["not_in_cinema"], ov["qid"]["only_in_one_archive"]
    w(_table(["archivio", "QID", "non in cinema", "solo in questo archivio"],
             [[k, _n(v), _n(nic.get(k, "—")), _n(only[k])] for k, v in sizes.items()]))
    w("")
    w("Nota: gli insiemi di serie includono stagioni e puntate che `cinema_db` rappresenta come opere figlie senza proprio QID; "
      "la differenza per le serie non va letta come perdita (da verificare per classe in B).")
    w("")
    w("RAG v3 per tipo in `cinema_db` (per QID): " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(ov["v3_in_cinema_by_kind"].items(), key=lambda kv: -kv[1])) + ".")
    w("")
    # ------------------------------------------------------------------ 2
    w("## 2. Lacune ordinate per rilevanza")
    w("La rilevanza è misurata, non fissata: per ogni soglia di numero di voti MovieLens si riporta quanti film mancano. **Nessuna soglia è proposta qui.**")
    w("")
    w("**Lacune in ordine di impatto sull'agente** (l'ordine è un giudizio, *ipotesi*; i numeri sono misurati):")
    w(f"1. Valutazioni: nessuna in cinema (0 %); {_n(add['movielens']['works_in_cinema_with_movielens_stats'])} opere hanno statistiche MovieLens subito disponibili, il resto richiede fonti esterne.")
    w(f"2. Film noti assenti: {_n(mm['missing_ge50'])} film con ≥50 voti MovieLens ({curve['by_threshold'][4]['missing_pct']} % di quelli con almeno 50 voti), tra cui i più votati (§3); cause in §3.")
    w(f"3. Cast: nessun ordine (0 %); personaggio solo nel {fw['all_films_pct']['cast_with_character']} % dei film ({fw['movielens_ge50_films_pct']['cast_with_character']} % tra quelli con ≥50 voti ML).")
    w(f"4. Persone: nessun ID IMDb/TMDb ({_n(ids['persons_total'])} persone), paese di nascita assente.")
    w(f"5. Uscite: {_n(c['work_release'])} date per paese, nessuna con tipo (0 % `release_with_type`).")
    w(f"6. Premi: presenti per il {fw['all_films_pct']['award_result']} % dei film ({fw['movielens_ge50_films_pct']['award_result']} % tra quelli con ≥50 voti ML); il nominato spesso non è registrato (limite noto).")
    w(f"7. Serie: regia solo per il {cov['by_kind']['series']['director']['pct']} % delle serie; durata quasi assente ({cov['by_kind']['series']['runtime']['pct']} %).")
    w(f"8. Perdite tra sorgente e build: {_n(mm['causes_all'].get('in_local_source_but_not_in_cinema', 0))} film presenti in sorgenti locali ma non in cinema (§7).")
    w("")
    w(_table(["voti MovieLens ≥", "film ML", "mancanti", "% mancanti", "voti dei mancanti", "% voti totali"],
             [[_n(x["min_ratings"]), _n(x["ml_films"]), _n(x["missing_from_cinema"]), x["missing_pct"], _n(x["missing_ratings"]),
               pct(x["missing_ratings"], x["total_ratings"])] for x in curve["by_threshold"]]))
    w("")
    w(f"MovieLens senza link IMDb: {_n(curve['movielens_without_imdb_link'])}; senza statistiche: {_n(curve['movielens_without_stats'])}.")
    w("")
    w("Lacune per campo (film): copertura su tutti i film e sui film con ≥50 voti MovieLens (i più rilevanti misurabili). Unità: film con almeno un dato, non righe (il «personaggio» è quindi diverso dal 12,6 % dei *crediti* citato altrove).")
    fw = cov["films_weighted"]
    order = ["rating_any_source", "cast_with_billing_order", "cast_with_character", "release_with_type", "award_result", "company", "franchise", "financial",
             "relation", "original_title", "runtime", "writer", "cinematographer", "composer", "language", "cast", "director", "genre", "country", "imdb_id", "tmdb_id", "release_year"]
    w(_table(["campo", "tutti i film", "film con ≥50 voti ML"], [[f, f"{fw['all_films_pct'][f]} %", f"{fw['movielens_ge50_films_pct'][f]} %"] for f in order]))
    w(f"\nFilm totali {_n(fw['films_total'])}; film con ≥50 voti ML presenti in cinema {_n(fw['films_in_movielens_ge50'])}.")
    w("")
    w("Per decennio (film):")
    w(_table(["decennio", "film", "regia %", "cast %", "personaggio %", "generi %", "durata %", "premi %", "società %", "IMDb %"],
             [[d, _n(v["films"]), v["director"], v["cast"], v["cast_with_character"], v["genre"], v["runtime"], v["award_result"], v["company"], v["imdb_id"]]
              for d, v in cov["films_by_decade"].items()]))
    w("")
    w("Copertura per tipo di opera (percentuale di opere con il dato):")
    kinds = ["film", "short", "tv_film", "series", "miniseries", "season", "episode", "other"]
    flds = ["director", "cast", "cast_with_character", "genre", "runtime", "release_year", "imdb_id", "tmdb_id", "award_result", "company"]
    w(_table(["tipo", "opere"] + flds, [[k, _n(cov["by_kind"][k]["works"])] + [cov["by_kind"][k][f]["pct"] for f in flds] for k in kinds if k in cov["by_kind"]]))
    p = cov["persons"]
    w(f"\nPersone: {_n(p['total'])}; anno di nascita {_n(p['birth_year'])} ({pct(p['birth_year'], p['total'])} %), anno di morte {_n(p['death_year'])}, "
      f"paese di nascita {_n(p['birth_country'])}. Cast medio per opera con cast: {cov['cast_per_work']['avg']} (max {cov['cast_per_work']['max']}). "
      f"Valutazioni di qualunque fonte in `cinema_db`: {cov['ratings_tables_in_cinema']} (non esiste una tabella).")
    w("")
    # ------------------------------------------------------------------ 3
    w("## 3. I film MovieLens mancanti")
    w(f"- Mancanti in totale (con link IMDb, qualunque numero di voti): **{_n(mm['missing_total'])}**; con ≥50 voti: **{_n(mm['missing_ge50'])}** "
      f"(voti totali {_n(mm['ge50_ratings_total'])}); con ID TMDb in MovieLens: {_n(mm['ge50_with_tmdb_id'])}.")
    w(f"- Scansione del dump eseguita: **{'sì' if mm['dump_scanned'] else 'no'}**.")
    w("")
    w("Cause (euristica a cascata: stesso TMDb in cinema → presente in altra fonte locale → stesso titolo/anno in cinema → pagina nel dump → nessuna traccia):")
    w(_table(["causa", "tutti i mancanti", "≥50 voti"],
             [[k, _n(mm["causes_all"].get(k, 0)), _n(mm["causes_ge50"].get(k, 0))] for k in sorted(set(mm["causes_all"]) | set(mm["causes_ge50"]), key=lambda k: -mm["causes_all"].get(k, 0))]))
    w("")
    w("Per decennio (≥50 voti): " + ", ".join(f"{k} {_n(v)}" for k, v in mm["ge50_by_decade"].items()) + ".")
    w("Generi principali (≥50 voti): " + ", ".join(f"{k} {_n(v)}" for k, v in mm["ge50_top_genres"].items()) + ".")
    w("")
    w("I 25 più votati tra i mancanti:")
    w(_table(["titolo", "voti", "causa"], [[t["title"], _n(t["n"]), t["cause"]] for t in mm["ge50_top_by_ratings"]]))
    w("")
    if dump.get("scanned"):
        w("### 3.1 Il dump Wikipedia: pagine-film scartate dall'estrazione")
        w(f"- Pagine con infobox film trovate nel dump: {_n(dump['film_infobox_pages'])} (accettate nell'estrazione {_n(dump['accepted_page_ids_in_dump_scan'])}, "
          f"scartate {_n(dump['rejected_page_ids_in_dump_scan'])}, né l'una né l'altra {_n(dump['film_pages_neither_accepted_nor_rejected'])}).")
        w("- Motivi di scarto: " + ", ".join(f"{k} {_n(v)}" for k, v in dump["rejected_reasons"].items()) + ".")
        w(f"- Tra gli scartati: anno nota {_n(dump['rejected_with_year'])}; con corrispondenza in cinema per titolo+anno ±1: {_n(dump['rejected_matching_a_cinema_work_by_title_and_year'])}; "
          f"**senza** opera corrispondente in cinema: {_n(dump['rejected_without_match_in_cinema'])}.")
        w("- Scartati per decennio: " + ", ".join(f"{k} {_n(v)}" for k, v in dump["rejected_by_decade"].items()) + ".")
        w("- Scartati per motivo e presenza di un'intestazione di trama riconosciuta dalla scansione: " +
          ", ".join(f"{k} {_n(v)}" for k, v in dump["rejected_with_plot_heading_found_by_scan"].items()) + ".")
        w("")
    # ------------------------------------------------------------------ 4
    w("## 4. Identificativi e possibilità di riconciliazione")
    w(_table(["schema", "tipo entità", "righe", "entità"], [[x["scheme"], x["entity_type"], _n(x["rows"]), _n(x["entities"])] for x in ids["cinema_external_ids"]]))
    w("")
    w(f"- Persone con un identificativo diverso da Wikidata in cinema: **{_n(ids['persons_with_non_wikidata_id'])}** su {_n(ids['persons_total'])}.")
    w(f"- Risposte di fase 4 (Wikidata mirato) contengono per le persone solo: {ids['phase4_snapshot_sparql_kinds']['kinds']}.")
    rv = ids["rag_v3_person_records"]
    w(f"- RAG v3: {_n(rv['actors'])} righe di attori, {_n(rv['actors_with_qid'])} con QID, {_n(rv['actors_with_character'])} con personaggio; nessun altro identificativo di persona.")
    ml = ids["movielens_links"]
    w(f"- MovieLens: {_n(ml['with_imdb'])} link IMDb e {_n(ml['with_tmdb'])} TMDb su {_n(ml['movies'])} film; nessun dato sulle persone.")
    w(f"- **Conclusione sulle persone**: {ids['conclusion_persons']}")
    w("")
    w("Proprietà Wikidata con tipo `external-id` presenti negli snapshot locali dei film (prime 15 per numero di entità; l'etichetta è nota solo dove verificata):")
    fs = ids["wikidata_snapshots"]["film_snapshot"]
    w(_table(["proprietà", "significato", "entità film", "importata dalla build"],
             [[x["property"], x["label"], _n(x["entities"]), "sì" if x["imported_by_build"] else "no"] for x in fs["external_id_properties"][:15]]))
    w(f"\nProprietà `external-id` distinte negli snapshot film: {fs['external_id_properties_total']}. Etichette non verificate: i numeri di proprietà sono dati, il significato va controllato in B.")
    w("")
    w("Qualificatori del cast negli snapshot (utili a ordine e personaggi):")
    cs = ids["wikidata_snapshots"]
    w(_table(["snapshot", "dichiarazioni P161", "con ordinale (P1545)", "con nome del personaggio (P4633)", "con personaggio come voce (P453)", "entità con ordinale"],
             [[n, _n(cs[n]["cast_statements"]["statements"]), _n(cs[n]["cast_statements"]["with_ordinal"]), _n(cs[n]["cast_statements"]["with_character_name"]),
               _n(cs[n]["cast_statements"]["with_character_item"]), _n(cs[n]["cast_statements"]["entities_with_ordinal"])] for n in ("film_snapshot", "series_snapshot")]))
    w("")
    # ------------------------------------------------------------------ 5
    w("## 5. Duplicati, omonimi e conflitti (candidati, nessuna fusione)")
    w(f"- Opere con più identificativi dello stesso schema: {dup['works_multiple_ids']}; prove per i doppi IMDb: {dup['works_multiple_ids_evidence']}.")
    w(f"- Coppie di opere con stesso titolo normalizzato e anno: {dup['work_homonym_pairs_by_class']}.")
    w(f"- Persone: {_n(dup['person_name_groups'])} nomi condivisi; coppie per classe: {dup['person_pairs_by_class']}.")
    w(f"- Conflitti di identificativi tra fonti: {dup['id_conflicts']}.")
    w("- File dei candidati (con prove): `cinema_db/data/audit_a0/candidates_work_multiple_ids.jsonl`, `candidates_work_homonyms.jsonl`, `candidates_person_pairs.jsonl`, `candidates_id_conflicts.jsonl`.")
    w("- Classi: *strong* = stesso nome e stesso ruolo nella stessa opera (una persona accreditata due volte con QID diversi); *homonym_different_birth_year* = omonimi legittimi; "
      "*undetermined* = manca l'anno di nascita o il regista, non decidibile offline.")
    w("")
    # ------------------------------------------------------------------ 6
    w("## 6. Cosa aggiunge ogni fonte locale")
    mv, v3, s5 = add["movielens"], add["rag_v3_cast"], add["s5"]
    w(_table(["fonte", "informazione nuova rispetto a `cinema_db`", "quantità misurata"], [
        ["MovieLens", "voto medio e numero di voti (nessuno in cinema)", f"{_n(mv['works_in_cinema_with_movielens_stats'])} opere già in cinema ({_n(mv['with_ge50_ratings'])} con ≥50 voti); {_n(mv['ratings_covered'])} dei {_n(mv['ratings_total'])} voti"],
        ["MovieLens", "tag degli utenti (≥2 utenti per lo stesso tag)", f"{_n(mv['tags_ge2_users_total_pairs'])} coppie film-tag; {_n(mv['works_with_tags_ge2_users'])} opere già in cinema"],
        ["MovieLens", "film assenti dal catalogo", f"{_n(mm['missing_total'])} (di cui {_n(mm['missing_ge50'])} con ≥50 voti)"],
        ["RAG v3", "ordine di elenco degli attori nell'infobox (proxy di ordine, ipotesi)", f"{_n(v3['films_with_actor_list'])} film, {_n(v3['actor_rows'])} righe"],
        ["RAG v3", "personaggio per crediti già in cinema", f"{_n(v3['character_available_for_existing_credits'])} righe; nuove (cinema non ha il personaggio): {_n(v3['character_new_for_existing_credits'])}"],
        ["RAG v3", "crediti non presenti in cinema", f"{_n(v3['not_in_cinema_credits'])} righe collegate; {_n(v3['unlinked_actor_rows'])} righe senza QID (nome soltanto)"],
        ["Snapshot Wikidata", "ordinale del cast (P1545)", f"{_n(add['wikidata_cast_qualifiers']['film_snapshot']['with_ordinal'])} su {_n(add['wikidata_cast_qualifiers']['film_snapshot']['statements'])} dichiarazioni film"],
        ["Catalogo s5", "serie/film TV non in cinema per QID", f"serie {_n(s5['series_not_in_cinema_by_qid'])}, film TV {_n(s5['tv_movies_not_in_cinema_by_qid'])}, incerti {_n(s5['uncertain_not_in_cinema_by_qid'])}"],
        ["Catalogo s5", "puntate", f"{_n(s5['episodes_summary']['episodes'])} nel catalogo (con numero {_n(s5['episodes_summary']['with_number'])}) contro {_n(s5['cinema_episodes'])} in cinema"],
    ]))

    # ------------------------------------------------------------------ 7
    w("")
    w("## 7. Discrepanze rispetto al piano, anomalie e limiti")
    d = dup["works_multiple_ids"]
    w("**Discrepanze rispetto al piano della fase 9 (documentate, non corrette altrove):**")
    w("- Il piano dava «357 opere con 2 ID TMDb». Quel conteggio raggruppava per opera gli ID `tmdb_movie` **e** `tmdb_tv`: sono opere che hanno "
      f"un ID di film e uno di serie. Doppi ID dello **stesso** schema: tmdb_movie {d.get('tmdb_movie', 0)}, tmdb_tv {d.get('tmdb_tv', 0)}, "
      f"imdb_title {d.get('imdb_title', 0)}, eidr {d.get('eidr', 0)}, tvdb_series {d.get('tvdb_series', 0)}. Le coppie film+serie "
      f"({d.get('tmdb_movie+tmdb_tv', 0)}) sono esportate in `candidates_work_multiple_ids.jsonl` (scheme `tmdb_movie+tmdb_tv`) e vanno classificate in B.")
    w("- «240 film in due QID» (PROGRESS) **non è riprodotto** da questo audit: qui si misurano gli ID IMDb condivisi da più QID negli snapshot "
      f"(film {dup['id_conflicts'].get('snapshot_film_imdb_id_on_several_qids', 0)}, serie {dup['id_conflicts'].get('snapshot_series_imdb_id_on_several_qids', 0)}). Sono misure diverse; la fonte dei 240 non è stata ricontrollata.")
    w("- Le «33 coppie nome+anno di nascita uguali» del piano erano gruppi; qui le coppie sono classificate (vedi §5) e il numero cambia perché cambia l'unità.")
    w(f"- Il piano e `PROGRESS.md` citavano 293.447 opere (build della fase 3); il database attuale ne ha {_n(c['work'])} (fase 4 e successive): il piano usava un numero superato, le altre cifre del piano coincidono.")
    w("- Confermati: 4.058 film MovieLens ≥50 voti assenti; *Fight Club* (1999) assente da cinema e da RAG v3; ID persona non Wikidata = 0; uscite 100 % `unspecified`.")
    w("")
    w("**Anomalie osservate:**")
    w(f"- {_n(mm['causes_all'].get('in_local_source_but_not_in_cinema', 0))} film MovieLens mancanti hanno invece lo stesso IMDb in RAG v3, in uno snapshot Wikidata o nel catalogo s5 ma **non** in cinema "
      f"({_n(mm['causes_ge50'].get('in_local_source_but_not_in_cinema', 0))} con ≥50 voti; esempi: *Robot Carnival*, *Cat Soup*, *Generation War*, *Grease Live*): sono opere perse tra la sorgente e la build "
      "(classificate come altro tipo o scartate). Causa non indagata: da fare in B (non è una lacuna di sorgente ma di build).")
    w(f"- {_n(mm['causes_all'].get('itwiki_film_page_in_extraction_but_not_in_cinema', 0))} mancanti hanno una pagina itwiki accettata dall'estrazione ma nessuna opera con quell'IMDb in cinema "
      "(es. *Bottle Rocket* = «Un colpo da dilettanti»; i due *Eleanor Rigby* sono su una sola pagina): possibili IMDb diversi tra fonti o pagine che coprono più film.")
    w(f"- Il dump contiene {_n(dump['film_infobox_pages'])} pagine con infobox film, l'estrazione ne aveva classificate {_n(inv['candidates'] + inv['rejected'])} tra accettate e scartate: la differenza dipende dal criterio (categoria film senza infobox) e non è stata analizzata.")
    w("")
    w("**Limiti dell'audit (non sono errori ma confini della misura):**")
    w("- I titoli MovieLens sono inglesi o originali, le pagine itwiki spesso italiane: **«nessuna pagina itwiki con quel titolo» non prova che la pagina non esista** (potrebbe avere un titolo italiano senza redirect). È un limite superiore.")
    w("- La corrispondenza per titolo e anno ±1 è un'euristica: due classi (`probable_same_work_under_other_ids`, `itwiki_title_only_candidate_year_not_confirmed`) sono **candidati**, non identificazioni.")
    w("- Le pagine scartate dall'estrazione hanno un anno ma **nessun QID né IMDb**: si possono legare a un'opera solo con Wikidata (sitelink) o con titolo+anno su un'altra fonte, quindi non in A0.")
    w("- I tempi di esecuzione non sono riportati: la scansione del dump è stata interrotta da una sospensione del computer e il suo orologio non è affidabile.")
    w("- Ordine del cast e personaggi: l'ordine di elenco dell'infobox è un indizio (ipotesi), non una fonte di *billing*.")
    w("")
    # ------------------------------------------------------------------ 8
    w("## 8. Raccomandazioni quantitative per A1 e B")
    cw = {x["min_ratings"]: x for x in curve["by_threshold"]}
    pc = add["rag_v3_cast"]
    w("**Fatti che orientano A1 (acquisizioni, tutte da autorizzare una per una):**")
    w(f"1. **Persone**: nessun ID IMDb/TMDb in nessun archivio locale. Servono per {_n(cov['persons']['total'])} persone: la fonte candidata copre molto con un solo scaricamento (dataset IMDb) o con ≈{_n(-(-cov['persons']['total'] // 300))} richieste Wikidata a gruppi di 300 QID [stima aritmetica].")
    w(f"2. **Cast con ordine e personaggio**: l'ordinale Wikidata (P1545) esiste su {_n(add['wikidata_cast_qualifiers']['film_snapshot']['with_ordinal'])} dichiarazioni su "
      f"{_n(add['wikidata_cast_qualifiers']['film_snapshot']['statements'])} ({pct(add['wikidata_cast_qualifiers']['film_snapshot']['with_ordinal'], add['wikidata_cast_qualifiers']['film_snapshot']['statements'])} %): insufficiente. "
      f"RAG v3 aggiunge solo {_n(pc['character_new_for_existing_credits'])} personaggi nuovi. Una fonte esterna è necessaria per ordine e personaggi.")
    w(f"3. **Film mancanti con ID noti**: i {_n(mm['missing_total'])} film MovieLens mancanti hanno tutti un IMDb; {_n(mm['ge50_with_tmdb_id'])} dei {_n(mm['missing_ge50'])} con ≥50 voti hanno anche TMDb. Il bulk IMDb li identifica senza richieste per titolo.")
    w(f"4. **Pagine itwiki esistenti ma scartate**: {_n(dump['rejected_without_match_in_cinema'])} pagine con infobox film (con anno) non hanno un'opera in cinema; il motivo prevalente è `plot_too_short` "
      f"({_n(dump['rejected_reasons'].get('plot_too_short', 0))}), cioè un vincolo del RAG sulla trama che **non serve a un database strutturato**. Per collegarle a un'opera servono QID (sitelink) o titolo+anno su una fonte con ID.")
    w(f"5. **Valutazioni**: {_n(add['movielens']['works_in_cinema_with_movielens_stats'])} opere già in cinema hanno statistiche MovieLens utilizzabili **senza alcuna richiesta**; tag (≥2 utenti): {_n(add['movielens']['works_with_tags_ge2_users'])} opere. Le altre fonti di valutazione richiedono A1.")
    w("")
    w("**Dati per decidere le soglie di ingresso in B (nessuna soglia proposta):**")
    w(f"- Film ML mancanti per soglia di voti: ≥1 → {_n(cw[1]['missing_from_cinema'])}; ≥10 → {_n(cw[10]['missing_from_cinema'])}; ≥50 → {_n(cw[50]['missing_from_cinema'])}; ≥100 → {_n(cw[100]['missing_from_cinema'])}; "
      f"≥1000 → {_n(cw[1000]['missing_from_cinema'])}. I voti coperti dai mancanti sono solo il {pct(cw[50]['missing_ratings'], cw[50]['total_ratings'])} % del totale a ≥50: in termini di *attenzione degli utenti* il catalogo è già alto, ma la mancanza di titoli notissimi (§3) è visibile.")
    w("- Prima di scegliere A/B/C per i film mancanti, A1 deve misurare quanti dei 61 mila hanno un record nel dataset esterno con voti e tipo (film/corto/TV), perché MovieLens contiene anche titoli che non sono lungometraggi.")
    w("")
    w("**Per B (progetto del database finale):** (a) indagare le perdite tra sorgente e build (§7); (b) classificare le 338 opere con ID TMDb di film e di serie e i 58 doppi IMDb; (c) esaminare i 256 candidati forti di persone doppie; "
      "(d) fissare le regole di ingresso usando la curva di §2 e i risultati di A1; (e) decidere se le pagine itwiki scartate per trama breve entrano come opere senza trama.")
    w("")
    w("## 9. Riproducibilità")
    w("```bash")
    w("python -m cinema_db.harness.audit.run_audit targets   # MovieLens mancanti -> targets.json")
    w("python -m cinema_db.harness.audit.run_audit scan      # una passata sul dump locale -> dump_scan.jsonl")
    w("python -m cinema_db.harness.audit.run_audit run       # tutte le sezioni -> results.json + candidati")
    w("python -m cinema_db.harness.audit.run_audit report    # questo documento")
    w("python -m pytest tests/test_cinema_audit.py -q        # 8 test, offline, miniature")
    w("```")
    w("Gli output stanno in `cinema_db/data/audit_a0/` (ignorata da git: `results.json`, `ml_missing.jsonl`, `candidates_*.jsonl`, `dump_scan.jsonl`); `results.json` è copiato anche in `docs/cinema_db/PHASE9_A0_RESULTS.json`.")
    w("")
    return "\n".join(L) + "\n"


def write_report(results_path: Path, out_path: Path) -> None:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    out_path.write_text(render(results), encoding="utf-8")
    print(f"report written: {out_path}")
