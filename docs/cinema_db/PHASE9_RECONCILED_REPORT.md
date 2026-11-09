# Fase 9 — v3 riconciliata: costruzione, regole applicate e verifiche (2026-11-08)

File: `cinema_db/data/cinema.v3.reconciled.sqlite3` (1.049.333.760 byte, schema 3, `builder = imdb_layer/2`, `content_sha256 = 044c35f8bfe5f58c2871ab8de88e38bbdf5049b7523750ae7da11c9f35d2e336`). Archivi separati: `cinema.v3.reconciled.separate/` (`not_entered`, `released_from_hold`, `dubious_pages`, `recovered_identifiers`). Rapporto numerico: `cinema.v3.reconciled.layer_report.json`; verifica indipendente: `cinema.v3.reconciled.verify.json` (`python -m cinema_db.harness.build.verify_reconciled`).
**Non attivata**: il runtime usa il v2 (`cinema.sqlite3`, digest `c888ebd0…`), `cinema_db.enabled = False`, policy e viste approvate sono quelle del v2. v2, v3 precedente (`8760f0fd…`) e prima costruzione (`54629e6e…`) sono byte-identici a prima (sha256 confrontati).

## Regole applicate (decisioni del proprietario del 2026-11-08; codice puro in `cinema_db/harness/build/reconcile_rules.py`)
| Area | Regola | Risultato effettivo |
|---|---|---|
| Doppi ID IMDb | primario = noto a IMDb → titolo uguale a un nome dell'opera → più voti → ordine lessicografico; `is_primary` riscritto solo in questa build; tipo/anno/durata/valutazione IMDb **solo** dal primario; i dati dei secondari in `entity_claim` (`imdb_alt_*`, `source_ref` = ID) | 58 opere, primario cambiato in 16 (`imdb_title_previous_primary`); 50 opere con l'unico ID marcato non primario nel v2 ora lo hanno primario |
| Persone: fusioni | `merge_check`: credito condiviso con lo stesso ruolo, anno di nascita IMDb noto e non contraddetto, nascite uguali se entrambe note, nessuna morte che IMDb non confermi | **12** fusioni (mappa `entity_canonical`, nessuna riga cancellata); rifiutate 113: 81 nascita contraddice, 26 IMDb senza nascita, 4 nascite diverse, 2 morte non confermata |
| Persone: ID condivisi | l'ID va alla sola persona la cui nascita coincide e che tutte le altre contraddicono con una nascita nota | **204** ID attaccati |
| Titoli trattenuti | rilascio se tutti i candidati non sono film/corto/film TV (A), oppure ogni candidato film ha un altro ID noto a IMDb e registi IMDb disgiunti (B) o durata lontana >15 min (B2); stesso regista = resta | **1.133** rilasciati (A 275, B 857, B2 1; `released_from_hold.jsonl`, claim `reconciliation_released_hold`); **523** restano (vedi anomalie) |
| Titolo unico | stato `imdb_title_year_unique_director_mismatch` se la pagina cita un regista che IMDb non elenca per l'unico candidato | 6.595 opere: 3.323 `imdb_title_year_unique`, **3.272** `…_director_mismatch` (non identità verificate) |
| Episodi | solo serie che hanno già episodi, padre = ID primario della serie, `tvEpisode` non adulto con titolo, stagione e numero, posizione libera; genitore = stagione esistente, altrimenti la serie | **90.824** importati (`entry_route = imdb_episode`); non importati: 3.371 posizione occupata, 1.228 senza stagione/numero, 2 senza titolo |
| Crediti | un nconst solo candidato di una persona esistente diventa una persona NUOVA con l'ID IMDb; claim `imdb_person_possibly_existing_person` (valore = persona esistente, `source_ref` = `nconst:livello`) e riga candidata invariata sull'esistente; mai fusione | **52.190** crediti recuperati, 11.514 persone create per questi candidati |
| MovieLens sugli alias | una valutazione per opera, dal film del primario; altrimenti dall'unico film che porta un alias; più film senza primario = ambigua, saltata | 23 valutazioni via alias, 0 ambigue |

## Conteggi prima/dopo
| | v2 (runtime) | v3 precedente | **v3 riconciliata** |
|---|---|---|---|
| opere | 301.718 | 384.300 | **476.086** |
| di cui episodi | 222.415 | 222.415 | **313.239** |
| persone | 141.646 | 532.138 | **547.814** |
| crediti | 675.327 | 1.861.764 | **1.930.064** |
| valutazioni | 0 | 328.597 | **404.416** |
| opere con ID IMDb | 54.612 | 305.059 | **396.807** |
| persone con ID IMDb | 0 | 460.876 | **476.766** |

## Verifiche (sul file, non sul builder)
`integrity_check` ok · `foreign_key_check` 0 · ogni opera con ID IMDb ha esattamente un primario · 0 ID esterni duplicati · 12 righe canoniche, 0 catene, tutte persona→persona · 0 persone fuse visibili in `v_person`/`v_credit` · 0 valutazioni IMDb non provenienti dall'ID primario · ogni ID secondario (86) ha un claim o il marcatore «sconosciuto a IMDb» · 0 episodi senza genitore valido · 100 interrogazioni campione sulle viste (50 opere, 50 persone) senza perdite rispetto al v2 · suite di `AGENTS.md`: 2.667 passati, 1 saltato (+6 test nuovi rispetto a 2.661) · `generate --check` exit 0 · mappa `schema_v3.html` rigenerata dal file (38 tabelle, 20 viste, 66 indici, tutte le tabelle presenti).

## Anomalie e limiti (non corretti, da decidere)
1. **523 titoli ancora trattenuti, di cui 457 solo per un difetto del confronto dei titoli.** Un nome scritto solo in alfabeto non latino ha `name_norm` vuoto e la chiave `("", anno)` collega ogni film con titolo IMDb non latino a tutte le 4.132 opere con nome non latino dello stesso anno: per questi 457 `candidate_basis = empty_normalised_name_only` in `not_entered.jsonl` (nessun candidato reale); i restanti 66 hanno un candidato vero (11 con lo stesso regista). Il difetto esiste dal v3 precedente; non l'ho corretto perché avrebbe allargato la regola d'ingresso oltre quanto approvato. Correggerlo = ignorare le chiavi vuote in `cinema_candidates` (una ricostruzione; entrerebbero fino a ~457 titoli identificati, con il rischio di duplicati dove il nome romanizzato non coincide).
2. **Rilasciati 1.133, non 1.574.** L'analisi del rapporto considerava solo i primi 5 candidati; la regola applicata richiede la prova per **tutti** i candidati film (più severa, mai più permissiva).
3. **Episodi 90.824, non 91.143.** Esclusi gli episodi di serie il cui ID è secondario (potrebbero appartenere a un'altra serie), le posizioni doppie dentro IMDb e 2 titoli senza lettere.
4. **39 episodi di cinema perdono l'ID episodio IMDb** che il v3 precedente aveva attaccato confrontandoli con la serie *secondaria* di un'opera con due ID; ora si confrontano solo con la serie primaria. Un episodio che ha già un ID non ne riceve un secondo (32 abbinamenti diventano candidati `episode_number_only`).
5. **Due film non entrati** perché il titolo è fatto solo di simboli (`$` 1971, `()` 2003): lo schema richiede un nome primario ricercabile (`title_without_searchable_characters`).
6. **186 collisioni di posizione (serie, stagione, episodio) nel v2**, ereditate invariate.
7. Persone create per i candidati deboli (11.514) possono essere **duplicati** di persone esistenti: dichiarati con claim e candidato, mai fusi. Le persone fuse sono solo le 12 approvate; le due coppie al limite (Aaron Abrams, Jana Nováková) restano distinte.
8. Lo strato debole del titolo unico (3.272 opere) ha precisione misurata 98,27 % sui cortometraggi con ID noto; **non** è generalizzabile alle pagine senza ID.
9. Viste per valutazioni, stato, claim e mappa canonica **non esistono** (fase F); le 6 viste modificate (`v_person`, `v_name`, `v_external_id`, `v_credit`, `v_award_result`, `v_title_search`) hanno stessi nomi e colonne del v2 ma la policy `approved_views.py` non è stata rigenerata.

## Costruzioni eseguite (trasparenza)
Quattro costruzioni complete in `cinema.v3.reconciled.sqlite3`: le prime due si sono fermate sul controllo interno (titoli senza lettere negli episodi; poi due film con titolo di soli simboli), la terza è stata scartata dopo la verifica per tre difetti trovati (alias di episodio con ID già presente, duplicato di un film via alias MovieLens, assenza del segnalatore dei trattenuti), la quarta è quella documentata. Il file della terza è rimasto come `cinema.v3.reconciled.sqlite3.previous` (superato). Una quinta costruzione in `cinema.v3.verify.sqlite3` (stesso codice, stessi input) ha dato **lo stesso digest, gli stessi contatori e la stessa dimensione**: riproducibilità confermata.


---
# Seconda correzione (2026-11-08, sera): difetto Unicode dei titoli trattenuti, stato dei titoli incerti, persone

File della seconda correzione (superato dalla candidata `cinema.v3.candidate.sqlite3`): `cinema_db/data/cinema.v3.reconciled2.sqlite3` (1.050.128.384 B, `builder = imdb_layer/2`, `content_sha256 = 59b575982ab0e6f9ce912e2705a7b4782376d9a3a51221971e29af4f0fef58ef`). Una seconda build indipendente (`cinema.v3.reconciled2.verify.sqlite3`, costruita in parallelo) ha **lo stesso digest e gli stessi contatori**. Il file precedente `cinema.v3.reconciled.sqlite3` (`044c35f8…`) resta come rollback; v2, v3 prototipo e prima costruzione sono byte-identici (sha256).

## Il difetto, dove sta e che cosa è stato corretto
Responsabile: `audit/util.py:norm_title` (ASCII soltanto, `re.sub(r"[^a-z0-9]+", " ")`). È il formato già memorizzato nell'archivio IMDb (`title.pnorm/onorm`) e usato da molte regole verificate, quindi **non è stato cambiato**. Un titolo scritto solo in un alfabeto non latino diventava `""`; l'indice dei titoli del catalogo aveva la chiave `("", anno)` che collegava ogni titolo con **originale della pagina italiana** non latino (la rotta delle pagine passa `original_title` tra i titoli) alle 4.132 opere con nome non latino dello stesso anno (e ±1). Non riguarda i titoli IMDb (sempre in alfabeto latino) né il percorso MovieLens.
Correzione (`cinema_db/harness/build/title_keys.py`, usata da `imdb_layer.py`): `norm_title_unicode` conserva lettere e cifre di ogni alfabeto (gli accenti si tolgono solo su base latina, greca o cirillica; in giapponese, coreano, thai un segno cambia la lettera e resta); `title_keys` dà la chiave storica più quella Unicode; una **chiave vuota non corrisponde mai a nulla**. Le persone si confrontano con `person_key` nella loro scrittura. Test: 3 nuovi (chiavi per alfabeto, accentate, simboli, vuote, `None`; pagina con titolo coreano che non collega più un'opera non correlata; vista di stato).

## I 523 titoli (522 identificativi IMDb distinti)
Quantificati con una esecuzione a secco (`--select-only`, nessun database) prima della build e poi confermati dal file:
| Esito | Titoli |
|---|---|
| **Recuperati** (entrano come opere) | **456**: 450 senza alcun candidato reale dopo la correzione (classe `U_no_title_match_after_unicode_correction`, claim `reconciliation_released_hold`) + 4 provati distinti con la regola B + 2 con la A |
| **Restano esclusi** | **66**, tutti con un candidato REALE (stesso titolo, anche nell'originale non latino, e anno): 54 regista ignoto, 11 stesso regista, 1 registi diversi senza prova sufficiente. Archivio: `cinema.v3.reconciled2.separate/not_entered.jsonl` (`candidate_basis = real_title_match`) |
Prove richieste ai 450 per non creare duplicati: nessuna opera con lo stesso titolo (in qualunque alfabeto: primario, originale, alias) entro un anno; nessuna opera film/corto/film TV dello stesso anno (±1) con **lo stesso regista** (nome nella propria scrittura) **priva di un altro ID IMDb noto** (una versione più severa teneva 60 titoli perché un regista prolifico ha più film all'anno; dopo aver escluso chi ha già un altro ID IMDb noto a IMDb i casi sono 0); l'ID IMDb non è già nel catalogo; l'identificazione di pagina è quella validata (titolo, anno, regista). Controllo a posteriori sui 456: **10** condividono una chiave di titolo (±1 anno) con un'altra opera; ho verificato ciascuno: ID IMDb diversi, registi diversi, durate diverse → omonimi, non duplicati. **Limite**: un'opera del catalogo che porta il film solo con un nome romanizzato diverso, senza regista condiviso, non verrebbe vista; non uso romanizzazioni approssimative come prova.
Effetti collaterali misurati: nessun titolo già entrato è stato escluso (0 nuovi trattenuti); le 271 opere che entravano dalla rotta MovieLens e hanno anche una pagina ora non più trattenuta passano alla rotta della pagina (186 → `imdb_title_year_director_confirmed`, 84 → `…_director_mismatch`, 1 → `imdb_title_year_unique`): vedi sotto. Le opere totali crescono di 185 (456 nuove − 271 che cambiavano solo rotta).

## Le 3.272 opere con regista in conflitto
Tutte e 3.272 (stessi ID IMDb) sono conservate con `imdb_title_year_unique_director_mismatch`: 0 perse. Lo stato ora è totale **3.423** (+151: 84 passate dalla rotta MovieLens, il resto pagine entrate). Nuova vista pubblica **`v_work_status`** (nel file v3; non ancora nella policy): colonna `identity_level` = `verified` (469.521) · `rule_based` (3.327, regola del titolo unico) · `uncertain` (3.423). Nessuna precisione misurata sui casi con ID è stata estesa a quelli senza ID.
**Osservazione da decidere**: 693 + 12 delle opere incerte/rule_based hanno anche un collegamento MovieLens verso lo stesso ID IMDb; la rotta della pagina ha la precedenza sulla rotta MovieLens (comportamento già presente) e il livello `uncertain` riguarda il collegamento con la pagina italiana, non l'esistenza del titolo IMDb. Per 85 di esse l'etichetta è peggiorata a causa di questa correzione. Alternativa (una ricostruzione): una pagina debole non sostituisce un'identificazione MovieLens.

## Le persone create per candidati deboli
11.524 persone (+10 rispetto alla build precedente per le 456 opere recuperate), nessuna fusione: tutte hanno ID `imdb_name`, ≥1 claim `imdb_person_possibly_existing_person` (12.117 claim in totale, valore = persona esistente, `source_ref = nconst:livello`) e la riga candidata sulla persona esistente intatta (verificato per ogni claim; 0 orfane). Rapporto di sola lettura (`python -m cinema_db.harness.build.person_merge_report`, file `cinema.v3.reconciled2.person_merge_candidates.jsonl`): `plausible_single_candidate` **8.199** (livello `weak_single_title`, nome unico tra le persone del catalogo e tra quelle IMDb, un titolo, date non contraddittorie), `homonym_risk` **1.986** (nome condiviso da più persone), `contradicted` **1.932** (anno di nascita o di morte in conflitto: da tenere separate). Il primo gruppo è l'unico che potrebbe diventare oggetto di una fusione futura, **solo con autorizzazione esplicita**: l'unicità del nome non esclude un omonimo non registrato.

## Differenze esatte dalla build precedente (`044c35f8…` → `59b57598…`)
| | prima | dopo |
|---|---|---|
| opere | 476.086 | **476.271** (+185) |
| persone | 547.814 | **548.575** (+761) |
| crediti | 1.930.064 | **1.932.877** (+2.813) |
| valutazioni | 404.416 | **404.585** (+169) |
| opere con ID IMDb | 396.807 | **396.992** |
| persone con ID IMDb | 476.766 | **477.527** |
| titoli trattenuti (voci) | 523 | **67** (66 ID distinti) |
| `…_director_mismatch` | 3.272 | **3.423** |
| `imdb_itwiki_page` / `_page_rule` / `imdb_movielens` | 27.463 / 6.595 / 49.486 | **27.764 / 6.750 / 49.215** |
Per le opere già presenti nel v2 nessun valore di tipo, anno, durata è cambiato (confronto con la build precedente: 0 differenze).

## Verifiche
`integrity_check` ok · `foreign_key_check` 0 · un solo ID primario per opera · 0 ID duplicati · 12 righe canoniche senza catene · 0 valutazioni IMDb da ID secondari · 0 episodi senza genitore · 100 interrogazioni campione senza perdite · suite di `AGENTS.md` **2.670 passati, 1 saltato** (+3) · `generate --check` exit 0 · mappa `schema_v3.html` rigenerata (include `v_work_status`).


---
# Terza tornata (2026-11-09): classificazione MovieLens vs pagina debole, candidata v3 e Fase F
Vedi `PHASE9_F_REPORT.md`. File di riferimento: `cinema.v3.candidate.sqlite3` (`9db2c80d…`, riproducibile). Una pagina debole non declassa più un'identificazione MovieLens coerente con IMDb: 642 delle 705 opere collegate sono `verified` (64 delle 85 declassate ripristinate; 21 restano deboli per titoli MovieLens diversi), la pagina resta nei claim. Livelli: verified 470.163 · rule_based 3.316 · uncertain 2.792.
