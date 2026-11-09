# Arricchimento TMDb per IMDb ID (prova live, nessuna chiamata a OpenAI)

30 film campionati a caso dal catalogo v3 con IMDb ID, in 6 gruppi da 5 (come i `k_finale` di un turno).

- Film trovati su TMDb per IMDb ID: 28/30; locandine: 28/28 schede.
- Chiamate HTTP: 31 in tutto, 5.2 per gruppo di 5 (una `/find` per film più la lista dei generi); ricerche per titolo: 0; chiamate non GET: 0.
- Tempo per gruppo: media 0.8 s.
- Film senza IMDb ID (3): stato ['skipped', 'skipped', 'skipped']; nessuna ricerca per titolo.

