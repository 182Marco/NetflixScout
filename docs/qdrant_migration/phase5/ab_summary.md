# Fase 5 - risultati automatici A/B/C (nessun giudizio qualitativo)

## Medie per variante (casi con il dato disponibile)

| variante | pertinenza testo | vicinanza positivi | vicinanza negativi | max coseno a un positivo | latenza mediana (ms) |
|---|---|---|---|---|---|
| A normale | 0.521 | 0.518 | 0.468 | 0.529 | 28.4 |
| B average_vector | 0.482 | 0.582 | 0.409 | 0.598 | 34.1 |
| C best_score | 0.442 | 0.658 | 0.512 | 0.677 | 38.5 |

Casi: {'total': 28, 'with_negative': 21, 'with_positive': 18, 'active': 23, 'controls': 5}. Sovrapposizione media con A: {'B': 0.361, 'C': 0.226}. HNSW ef=128 contro esatta, sovrapposizione minima: {'B': 1.0, 'C': 1.0}.

## Criteri del protocollo (scritti prima della misura)

| criterio | B average_vector | C best_score |
|---|---|---|
| 1 negativi: calo medio >= 0,02 e in >= 60% dei casi | OK: media -0.0588, calo in 86% (21 casi) | **NON soddisfatto**: media +0.0439, calo in 19% |
| 2 pertinenza al testo: calo medio <= 0,02 | **NON soddisfatto**: media -0.0473 | **NON soddisfatto**: media -0.0962 |
| 2 (per caso) nessuna perdita > 0,05 | 8 eccezioni su 23 | 16 eccezioni su 23 |
| 3 positivi: calo medio <= 0,02 | OK: media +0.0645 | OK: media +0.1406 |
| 3 (per riferimento) nessuna perdita > 0,05 | 0 eccezioni | 0 eccezioni |
| 4 vincoli: violazioni totali <= A | **NON soddisfatto**: 19 contro 16 | **NON soddisfatto**: 20 contro 16 |
| 5 riferimenti nei risultati = 0 | OK: 0 (senza esclusioni del parser: 0) | OK: 0 (senza: 0) |
| 6 controlli senza riferimenti validi = A | OK: 5/5 | OK: 5/5 |
| **Tutti i criteri** | **NO** | **NO** |

Esito: **nessuna variante migliora abbastanza la baseline**.

## Per caso (differenza rispetto ad A: negativi, testo, positivi; violazioni A/B/C; sovrapposizione con A)

| caso | categoria | riferimenti usabili (+/-) | neg B/C | testo B/C | pos B/C | viol. A/B/C | sovrapp. B/C |
|---|---|---|---|---|---|---|---|
| c01 | single_pos_neg | 1/1 | -0.024 / +0.099 | -0.036 / -0.086 | +0.046 / +0.142 | 0/0/0 | 0.4 / 0.1 |
| c02 | single_pos_neg | 1/1 | -0.008 / +0.106 | -0.013 / -0.037 | +0.012 / +0.094 | 0/0/0 | 0.6 / 0.2 |
| c03 | single_pos_neg | 1/1 | -0.043 / +0.015 | -0.113 / -0.125 | +0.150 / +0.182 | 0/0/0 | 0.1 / 0.0 |
| c04 | single_pos_neg | 1/1 | +0.009 / +0.071 | -0.046 / -0.103 | +0.130 / +0.211 | 0/0/0 | 0.2 / 0.0 |
| c05 | single_pos_neg | 1/1 | -0.143 / +0.001 | -0.101 / -0.214 | +0.013 / +0.166 | 0/0/0 | 0.0 / 0.0 |
| c06 | single_pos_neg | 1/1 | -0.059 / +0.010 | -0.066 / -0.248 | +0.070 / +0.209 | 0/0/0 | 0.4 / 0.0 |
| c07 | single_pos_neg | 1/1 | -0.012 / +0.101 | -0.008 / -0.090 | +0.004 / +0.069 | 0/0/0 | 0.8 / 0.2 |
| c08 | positive_only | 1/0 | - / - | -0.054 / -0.157 | +0.139 / +0.189 | 0/0/0 | 0.3 / 0.0 |
| c09 | positive_only | 1/0 | - / - | -0.044 / -0.185 | +0.121 / +0.189 | 0/0/0 | 0.3 / 0.0 |
| c10 | negative_only | 0/1 | -0.131 / -0.050 | -0.041 / -0.015 | - / - | 0/0/0 | 0.4 / 0.6 |
| c11 | negative_only | 0/1 | -0.065 / +0.000 | -0.025 / +0.000 | - / - | 0/0/0 | 0.6 / 1.0 |
| c12 | multi_positive | 3/1 | -0.011 / +0.043 | -0.070 / -0.090 | +0.103 / +0.116 | 0/0/0 | 0.2 / 0.1 |
| c13 | multi_positive | 3/1 | -0.049 / +0.049 | -0.070 / -0.058 | +0.046 / +0.069 | 0/0/0 | 0.3 / 0.1 |
| c14 | multi_negative | 1/3 | +0.021 / +0.082 | -0.002 / -0.042 | +0.029 / +0.082 | 0/0/0 | 0.8 / 0.3 |
| c15 | multi_both | 2/3 | -0.013 / +0.069 | -0.022 / -0.057 | +0.029 / +0.080 | 0/0/0 | 0.3 / 0.1 |
| c16 | multi_both | 2/2 | +0.023 / +0.097 | -0.048 / -0.180 | +0.082 / +0.123 | 0/0/0 | 0.5 / 0.1 |
| c17 | ambiguous_partial | 0/1 | -0.178 / -0.032 | -0.042 / -0.008 | - / - | 0/0/0 | 0.2 / 0.7 |
| c18 | ambiguous_partial | 0/1 | -0.165 / -0.049 | -0.045 / -0.009 | - / - | 0/0/0 | 0.3 / 0.6 |
| c19 (controllo) | ambiguous_all | 0/0 | - / - | +0.000 / +0.000 | - / - | 0/0/0 | 1.0 / 1.0 |
| c20 | absent_partial | 0/1 | -0.201 / -0.018 | -0.072 / -0.002 | - / - | 0/0/0 | 0.1 / 0.9 |
| c21 (controllo) | absent_all | 0/0 | - / - | +0.000 / +0.000 | - / - | 0/0/0 | 1.0 / 1.0 |
| c22 (controllo) | absent_all | 0/0 | - / - | +0.000 / +0.000 | - / - | 0/0/0 | 1.0 / 1.0 |
| c23 (controllo) | no_references | 0/0 | - / - | +0.000 / +0.000 | - / - | 0/0/0 | 1.0 / 1.0 |
| c24 (controllo) | no_valid_reference | 0/0 | - / - | +0.000 / +0.000 | - / - | 0/0/0 | 1.0 / 1.0 |
| c25 | constraints | 1/1 | -0.108 / +0.034 | -0.070 / -0.130 | +0.038 / +0.153 | 0/0/0 | 0.2 / 0.1 |
| c26 | constraints_homonyms | 1/1 | -0.033 / +0.114 | -0.031 / -0.119 | +0.024 / +0.146 | 8/9/10 | 0.5 / 0.1 |
| c27 | constraints_homonyms | 1/1 | -0.027 / +0.087 | -0.026 / -0.123 | +0.039 / +0.122 | 8/10/10 | 0.4 / 0.0 |
| c28 | constraints | 1/1 | -0.019 / +0.094 | -0.042 / -0.133 | +0.086 / +0.190 | 0/0/0 | 0.4 / 0.0 |

## Stato di risoluzione dei riferimenti

ambiguous: 4, not_in_index: 5, resolved: 50. Anomalie di risoluzione rispetto all'atteso congelato: nessuna.
