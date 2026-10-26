# Fase 7 - seconda batteria di 20 domande reali (2026-10-26)

Servizi reali: OpenAI (classificatore, planner, parser, risposta, embedding), Cohere (rerank), TMDb; motore Qdrant (predefinito), server 1.20.0
avviato con `scripts/start_qdrant.sh` sull'indice reale (42.522 punti), catalogo spento, pause di 30 s. Domande nuove (`questions_v2.json`), stessa
composizione della prima batteria: 10 RAG, 3 MovieLens, 4 TMDb, 1 composta, 1 follow-up, 1 fuori tema. Risultati grezzi: `results_v2/`.

## Esito (giudizio di un solo valutatore, il modello: evidenza indicativa)
Pre-classificazione meccanica: 20 completed, 0 partial, 0 missed, 0 error (nessun errore di turno, nessun fallback silenzioso).
Giudizio sulle risposte: **13 complete, 5 parziali, 2 errate/non risposta**.

| Id | Domanda | Esito | Nota |
|---|---|---|---|
| r01 | Consigliami 4 film su un viaggio nello spazio con un finale commovente | completa | 4 titoli (tra cui *Gravity*); dichiara che spazio e finale commovente non sono verificabili |
| r02 | Film francesi degli anni 60 sulla gioventù e la ribellione | parziale | film del periodo, ma la nazionalità francese e il tema della gioventù non sono verificabili (solo un titolo confermato) |
| r03 | Thriller ambientati su un treno o su una nave | completa | thriller su treno (*Night Train* ecc.); dichiara la nave non verificabile |
| r04 | Cerco un film in cui c'è un personaggio chiamato Norman Bates | errata | hybrid scelto bene e il pool conteneva il film giusto (*Psycho IV*), ma il rerank ha messo primo un film che cita Norman Bates solo di passaggio (*You Lucky Dog*); la risposta ammette che il personaggio non è verificabile |
| r05 | Commedie sull'amicizia tra due uomini di età molto diversa | parziale | tre titoli, ma 'amicizia tra due uomini di età molto diversa' non è confermata per nessuno; dichiarato |
| r06 | Film sul tema della memoria e dell'identità senza violenza | parziale | titoli deboli (*Reminiscences*, identità TMDb non verificata); temi dichiarati non verificabili |
| r07 | Consigliami 3 film western con un protagonista antieroe | completa | 3 western, genere verificato, 'antieroe' dichiarato non verificabile |
| r08 | Film di animazione per adulti con temi filosofici | completa | 3 film d'animazione, animazione verificata, 'per adulti/filosofici' dichiarato non verificabile |
| r09 | Drammi giudiziari ambientati nel sud degli Stati Uniti | completa | drammi giudiziari (*Heavens Fall*, 2006, ecc.), vincoli dichiarati |
| r10 | Film sulla mafia giapponese (yakuza) degli anni 70 | completa | 3 film yakuza anni 70 (*Battles Without Honour and Humanity*, 1973, ecc.) |
| d01 | Quali sono i 5 film con il voto medio più alto tra quelli con almeno 5000 voti? | parziale | la soglia 'almeno 5000 voti' non è supportata dal tool DB (usa 50): la lista include film con meno voti, e la risposta lo segnala |
| d02 | Quali sono i film più votati del 2003? | parziale | 'più votati' interpretato come voto medio più alto (dichiarato nel testo), non come numero di voti |
| d03 | Qual è il voto medio dei film horror? | completa | voto medio horror 2,93/5 su 1.798 film e 2.437.608 voti |
| t01 | Chi è il protagonista di Blade Runner 2049 e in che anno è uscito? | completa | Ryan Gosling (Agente K), 2017, regia di Denis Villeneuve |
| t02 | Quali film ha diretto Greta Gerwig? | completa | filmografia da regista di Greta Gerwig da TMDb |
| t03 | Dove posso vedere Oppenheimer in streaming in Italia? | completa | Oppenheimer (2023), disponibilità in Italia da TMDb |
| t04 | Quali sono i film più popolari del momento? | completa | classifica TMDb con la data odierna (26 ottobre 2026) dichiarata |
| m01 | Consigliami un thriller psicologico e dimmi anche chi lo ha diretto | completa | consiglia *Silent Night, Bloody Night* (1974) con regia; vincoli dichiarati |
| f01 | Ne hai uno più recente? | errata | il follow-up passa a TMDb ordinato per data decrescente e propone *Avatar 5* (2031, non uscito, senza dati); non risponde a 'più recente' in modo utile |
| x01 | Qual è la capitale della Francia? | completa | bloccata come non cinematografica |

## Confronto con la prima batteria (`phase7_report.md`)
| | complete | parziali | errate / corrette durante il test |
|---|---|---|---|
| Batteria 1 (20 domande) | 14 | 5 | 1 (t04, corretta durante il test) |
| Batteria 2 (20 domande, domande diverse) | 13 | 5 | 2 |
Le domande sono diverse, quindi il confronto è indicativo, non una misura di regressione. Nella batteria 2 le due risposte errate non dipendono da Qdrant
(il pool di Qdrant conteneva il film giusto in r04; f01 è una scelta di instradamento/ordinamento TMDb). I casi parziali sono vincoli non verificabili
e limiti dichiarati dei tool.

## Errori di risposta contro problemi infrastrutturali
- **Infrastrutturali: nessuno.** 20 turni su 20 completati, nessun errore di rete, di chiave, di quota (nessun 429 di Cohere con le pause di 30 s), server Qdrant sempre raggiungibile.
- **Errori di risposta (aperti, non corretti in questa fase):**
  1. r04: il reranker Cohere preferisce una menzione di passaggio ("come Norman Bates in Psycho") al film che ha davvero il personaggio; con `k_finale=1` il film giusto è perso.
  2. f01: "Ne hai uno più recente?" diventa `discover_movies` per data decrescente e include film non ancora usciti e senza dati.
  3. d01: il tool MovieLens non accetta una soglia di voti scelta dall'utente (solo `min_ratings` di configurazione).
  4. d02: "più votati" ambiguo tra numero di voti e voto medio; il parser sceglie il voto medio (lo dichiara).

## Limiti
Un solo run e un solo valutatore; il costo non è misurato (il runner non registra i token); nessun confronto cieco con Chroma.
