# Ottimizzazione del riordino (S6): latenza, qualità, pool, contesto e modelli

Stessa batteria di 62 domande sul solo corpus nuovo (56 liste A–G per le percentuali). **Giudice dei film: gpt-5.5** (diverso dal modello che esegue parser, riordino e risposte). Qualità = film validi e violazioni su 5 film per domanda; la latenza è il tempo reale di ricerca + riordino su 6 domande, in sequenza, senza cache (parser escluso, circa 3,4–4,1 s). Rumore di misura: circa ±3 punti sulle percentuali (280 film per riga) e ±1 punto tra due giudizi della stessa lista.

| Variante | Configurazione del riordino | Latenza (s) | Violazioni | Validi | A | C | D | H |
|---|---|---|---|---|---|---|---|---|
| X1 | gpt-5.6-sol none, pool 40, 450 | 3,2 | 5.0% | 85.7% | 76% | 82% | 67% | 57% |
| V9 | luna low, pool 50, 600 | ~9 | 4.3% | 85.4% | 84% | 78% | 67% | 77% |
| X6 | gpt-5.6-sol none, pool 50, 700 | 3,7 | 4.3% | 85.0% | 76% | 82% | 80% | 47% |
| X4 | gpt-5.6-sol none, pool 40, 700 | ~3,2 | 3.6% | 84.6% | 72% | 90% | 80% | 43% |
| X5 | gpt-5.6-sol none, pool 40, 1500 (quasi la trama intera) | 3,0 | 2.5% | 84.6% | 76% | 85% | 77% | 50% |
| X7 | gpt-5.6-sol none, pool 40, 700, top 8 | 2,2 | 3.6% | 84.3% | 72% | 90% | 77% | 43% |
| W5 | luna low, pool 50, 600, top 8 | ~5,5 | 6.1% | 83.6% | 76% | 82% | 67% | 50% |
| V7 | luna low, pool 40, 450 | ~6 | 5.7% | 83.2% | 72% | 80% | 70% | 73% |
| X8 | gpt-5.6-sol none, pool 30, 700 | 2,9 | 5.7% | 82.9% | 64% | 88% | 73% | 43% |
| V8 | luna low, pool 25, 1200 | ~6 | 3.9% | 82.1% | 68% | 82% | 63% | 67% |
| S6 | gpt-5.6-luna ragionamento predefinito, pool 25, 450 car. | ~10 (misurato in A/B) | 3.6% | 81.8% | 62% | 88% | 70% | 60% |
| W2 | luna none, pool 50, 600 | ~3,4 (con picchi) | 8.2% | 81.4% | 74% | 85% | 57% | 47% |
| X2 | gpt-5.6-terra none, pool 40, 450 | 2,8 | 5.4% | 81.4% | 78% | 80% | 60% | 50% |
| X3 | gpt-5.4 none, pool 40, 450 | 3,5 | 6.4% | 81.4% | 72% | 85% | 67% | 50% |
| W4 | luna none, pool 50, 600, top 8 | ~2,9 | 7.9% | 80.7% | 70% | 88% | 60% | 50% |
| W1 | luna none, pool 40, 450 | ~2,8 | 9.6% | 80.0% | 68% | 80% | 60% | 53% |
| V1 | luna low, pool 25, 450 | ~6 | 6.4% | 78.6% | 58% | 75% | 63% | 70% |
| V10 | gpt-5.4-mini low, pool 25 | ~4,7 | 5.7% | 77.9% | 62% | 80% | 60% | 57% |
| W6 | gpt-5.4-mini, pool 50, 600, top 8 | ~2,7 | 7.5% | 76.1% | 68% | 80% | 53% | 43% |
| V2 | luna none, pool 25, 450 | ~2,6 | 7.9% | 75.0% | 62% | 70% | 60% | 60% |
| V3 | gpt-5.4-mini, pool 25 | ~2,1 | 7.1% | 74.6% | 60% | 80% | 53% | 47% |
| W3 | gpt-5.4-mini, pool 40 | ~3,4 | 8.2% | 74.6% | 64% | 70% | 63% | 37% |
| V5 | gpt-4.1-mini, pool 25 | ~1,9 | 8.2% | 71.8% | 62% | 72% | 53% | 47% |
| V6 | luna low, pool 15, 300 | ~5 | 7.5% | 71.1% | 56% | 68% | 53% | 70% |
| V4 | gpt-5.4-nano, pool 25 | ~1,3-2,0 | 10.4% | 70.0% | 66% | 70% | 47% | 33% |
| C1 | Cohere rerank-v3.5 (non conosce i film) | ~1 | 18.3% | 59.6% | 44% | 73% | 40% | 32% |
| S5 | nessun riordino LLM | - | 12.9% | 53.6% | 46% | 55% | 47% | 37% |

## Latenza del turno intero (misura dal vivo, query «horror psicologici come Hereditary…»)

| Fase | prima (S6, luna) | dopo (gpt-5.6-sol senza ragionamento, 40 candidati, 1.500 caratteri) |
|---|---|---|
| classificatore | 1,0 s | 1,0 s |
| planner | 3,0 s | 3,0 s |
| parser | 4,5 s | 3,4–4,1 s (ragionamento predefinito, vedi PARSER_REPORT.md) |
| embedding, risoluzione dei titoli, ricerca Qdrant | 1,0 s | 1,0 s |
| riordino LLM | 6–10 s | ~3,0 s |
| locandine TMDb | 1,0 s | ~0,8 s |
| prima parola della risposta dopo la fine del tool | +3–4 s | +3–4 s |
| **retriever (parser→riordino)** | **~14,5 s** misurato nel tool | **~8–9 s** (stima: somma delle misure per fase; il turno intero con la configurazione finale non è stato rimisurato perché i crediti OpenAI sono finiti, vedi PROGRESS.md) |

## Conclusioni

- **Il costo è il ragionamento del modello, non la dimensione del contesto.** Con lo stesso modello (luna) togliere il ragionamento porta il riordino da 6–10 s a ~2,6 s ma raddoppia le violazioni (6–9% contro 4%). Un modello più grande senza ragionamento (gpt-5.6-sol) mantiene la qualità: **X5 3,0 s, 2,5% di violazioni, 84,6% di film validi**, meglio del riferimento S6 (3,6–4,6%, 81%).
- **Più testo di trama aiuta**: a parità di modello, 450 → 700 → 1.500 caratteri porta le violazioni 5,0% → 3,6% → 2,5% (X1, X4, X5) e i tratti in linguaggio naturale da 8,7% a 4,4%. Il testo intero della trama non è stato provato oltre i 1.500 caratteri (la mediana dei film è più lunga).
- **Il pool conta poco oltre 40**: 25 → 40 candidati migliora (V1 → V7: 77,9% → 83,2% validi), 50 non aggiunge qualità (X6 85,0% / 4,3%) e costa 0,7 s; 30 è peggio (X8 5,7%).
- **Modelli piccoli (gpt-5.4-mini/nano, gpt-4.1-mini)**: 1,3–2,1 s ma 7–9% di violazioni e 70–73% validi: scartati. **Cohere** non conosce i film e vede le esclusioni solo come testo: 18,6% di violazioni, scartato come riordino.
- **Categorie D e H** (dove il vecchio RAG era avanti): con X5 D sale a 77% (vecchio 77%) e H a 50% (vecchio 47%); l'effetto viene dal pool di 40 e dal testo più lungo. Attenzione: H ha solo 30 film per riga (±15 punti di rumore) e con luna `low` (V9) vale 77%: le richieste contraddittorie sono il punto in cui il ragionamento aiuta ancora; la differenza non è stata isolata.
- **Scelta**: `rag.film_index.rerank = {model: gpt-5.6-sol, effort: none, pool: 40, plot_chars: 1500}` in `app.py`. Il parser resta gpt-5.6-luna con il ragionamento predefinito (`none` ne peggiora la qualità, `PARSER_REPORT.md`).
