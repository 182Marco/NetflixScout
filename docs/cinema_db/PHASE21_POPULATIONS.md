# FASE 21 — Popolazioni delle operazioni di `cinema_sql` e semantica proposta (2026-11-09)

Misure sulla candidata 5 (`cinema.v4.candidate5.sqlite3`, schema 4), in sola lettura. **Il comportamento NON è stato modificato**: questo documento descrive lo stato attuale (verificato da `tests/test_cinema_populations_and_determinism.py`) e propone una semantica coerente da approvare.

## Tipi di opera del catalogo
Costanti: film = `film`, `short`, `tv_film`; serie = `series`, `miniseries`; schermo = film + serie. Altri tipi (`season`, `episode`, `other`) esistono nella tabella `work` ma nessuna operazione li elenca come risultato di ricerca di titoli (compaiono solo nella struttura di una serie o, per errore di classificazione, nei dati MovieLens: vedi sotto).

## Stato attuale per operazione
| Operazione | Popolazione | Dati usati | Note |
|---|---|---|---|
| `find_work`, `work_card`, `provenance`, `relations`, `awards`, `companies` | `type` assente = schermo; `film` = film; `series` = serie | catalogo, ID, relazioni, premi | un titolo ambiguo è `ambiguous`, mai una fusione |
| `filmography`, `collaborations` | schermo (con `type` si restringe) | crediti | |
| `ratings` (senza titolo: classifica) | `type` assente = **film e serie insieme**; con `type` rispettato | solo voti IMDb (scala 10), minimo 1.000 voti | non usa MovieLens |
| `movielens` `top_rated`, `most_rated`, `by_genre_year` | **solo film, corti, film TV** collegati; minimo 50 voti | MovieLens: media, numero di voti, generi MovieLens, anno MovieLens per i filtri | coerente con il vecchio tool (che toglieva le serie con TMDb) |
| `movielens` `genre_stats` | **ogni opera collegata** con generi MovieLens e ≥50 voti, serie ed episodi inclusi | media dei voti medi, conteggi | 90 su 15.845 opere (0,57 %) non sono film; il vecchio tool contava anche i titoli non collegati |
| `movielens` `by_tag` | ogni opera collegata con quel tag (nessun minimo di voti) | `work_tag.n_users` (utenti distinti), media | include miniserie, serie, 55 episodi |
| `movielens` `by_title` | **ogni film MovieLens**, anche escluso dal catalogo (con `status: excluded` e il motivo, `work_id` nullo) | titolo MovieLens in tre livelli (esatto, articolo normalizzato, sottostringa) | gli unici risultati con `status: excluded` |

Ogni elemento MovieLens riporta già `kind` (e `status`/`reason` se escluso): il risultato dice cosa è.

## Quanto vale l'incoerenza (misurato)
Se `genre_stats` si limitasse ai film: 16 generi su 19 cambierebbero; al massimo −1,6 % di film per genere, −0,005 della media, −0,5 % dei voti (Dramma 7.472 → 7.417 film). Le tre popolazioni non-film di MovieLens: miniserie 209 (59 con ≥50 voti), episodi 136 (12), serie 53 (19), altro 2. Esempi che oggi sono nelle statistiche e nei tag ma non nelle classifiche: *Band of Brothers*, *Pride and Prejudice* (1995), *Firefly*, *Cosmos*.

## Semantica proposta (da approvare; nulla applicato)
1. **Liste e statistiche di FILM** (`top_rated`, `most_rated`, `by_genre_year`, **`genre_stats`**): una sola popolazione, quella dei film (film, corti, film TV) collegati; `genre_stats` si allinea (effetto ≤1,6 % sui conteggi, nessun effetto pratico sulle medie). Motivo: sono domande sui film; una statistica di genere che mescola serie e film non è citabile come «film».
2. **Ricerca per titolo** (`by_title`): invariata, tutti i titoli MovieLens, con `kind`, `status`, `reason` (chi cerca «Band of Brothers» lo trova e vede che è una miniserie; chi cerca un titolo escluso vede perché).
3. **Ricerca per tag** (`by_tag`): invariata nel contenuto (le opere collegate con quel tag), ma con **`kind` sempre mostrato** e un parametro opzionale `type` (film/serie) analogo a quello di `ratings`, predefinito = tutte le opere collegate; le istruzioni di risposta dicono di nominare il tipo quando non è un film.
4. **`ratings` senza `type`**: invariato (schermo), la risposta deve dichiarare che la classifica può contenere serie; per «i migliori film» il planner passa `type: film`.
5. **Parità col vecchio tool**: si mantiene dove ha senso (classifiche, titoli, tag: 99 casi + 395 casi diversi, 392 identici e 3 spiegati); `genre_stats` non è mai stata identica (titoli non collegati) e non lo diventa.
Decisione richiesta al proprietario: approvare 1, 3 (parametro `type` per i tag) e 4; altrimenti restano le popolazioni attuali, già testate e documentate.
