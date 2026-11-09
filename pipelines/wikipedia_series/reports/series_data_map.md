# Mappa dei dati delle serie TV (generata dai dati reali)

Generata da `python -m pipelines.wikipedia_series.schema_map`. Nessuna base SQL: i record sono file JSONL (`data/s5`) e punti Qdrant (`wikipedia_series_it_v1`, un punto per unità embeddata, id = uuid5(namespace, `record_id`)).


## `series.jsonl` — 15697 record

| campo | tipi osservati (conteggio) |
|---|---|
| `cast` | str 9191, null 6506 |
| `catalog_class` | str 15697 |
| `class_check` | str 15697 |
| `country` | list 15697 |
| `creators` | null 9821, str 5876 |
| `declared_episodes` | null 10250, str 5447 |
| `declared_seasons` | null 14140, str 1557 |
| `default_search_eligible` | bool 15697 |
| `entity_type` | str 15697 |
| `flags` | list 15697 |
| `genres` | list 15697 |
| `has_episode_pages` | bool 15697 |
| `ids` | dict 15697 |
| `ids_reliable` | bool 15697 |
| `inline_episode_row_count` | int 15697 |
| `language` | str 15561, null 136 |
| `lead_chars` | int 15697 |
| `lead_text` | str 15697 |
| `network` | str 8167, null 7530 |
| `original_classification` | dict 9 |
| `original_title` | str 13151, null 2546 |
| `page_id` | int 15697 |
| `plot_chars` | int 15697 |
| `plot_flags` | list 15697 |
| `plot_heading` | str 13285, null 2412 |
| `plot_text` | str 15697 |
| `plot_text_shared_by` | int 9 |
| `record_id` | str 15697 |
| `review_note` | str 49 |
| `revision_id` | str 15697 |
| `subtype` | str 15697 |
| `text_kind` | str 15697 |
| `text_provenance` | dict 15697 |
| `title` | str 15697 |
| `wikidata_classes` | list 15697 |
| `wikipedia_url` | str 15697 |
| `year` | int 13754, null 1943 |
| `year_end` | int 11733, null 3964 |

## `seasons.jsonl` — 15032 record

| campo | tipi osservati (conteggio) |
|---|---|
| `entity_type` | str 15032 |
| `episode_section_count` | int 15032 |
| `evidence` | str 4175 |
| `flags` | list 15032 |
| `ids` | dict 15032 |
| `lead_chars` | int 15032 |
| `lead_text` | str 15032 |
| `logical` | bool 15032 |
| `page_id` | int 15032 |
| `parent_ids` | list 15032 |
| `record_id` | str 15032 |
| `relation_sources` | dict 10857 |
| `relation_status` | str 15032 |
| `revision_id` | str 10857, null 4175 |
| `season_number` | int 14999, null 33 |
| `season_number_sources` | dict 10857 |
| `series_id` | str 15004, null 28 |
| `series_title` | str 15032 |
| `subtype` | str 15032 |
| `table_row_count` | int 15032 |
| `text_kind` | str 15032 |
| `title` | str 15032 |
| `wikipedia_url` | str 10857, null 4175 |

## `episodes.jsonl` — 78705 record

| campo | tipi osservati (conteggio) |
|---|---|
| `air_dates` | list 78705 |
| `entity_type` | str 78705 |
| `episode_number` | int 54261, null 24444 |
| `flags` | list 78705 |
| `ids` | dict 78705 |
| `numbering` | str 78705 |
| `page_id` | int 78705 |
| `parent_ids` | list 78705 |
| `parent_page_id` | int 78599, null 106 |
| `plot_chars` | int 78705 |
| `plot_text` | str 78705 |
| `record_id` | str 78705 |
| `relation_status` | str 78705 |
| `revision_id` | str 78705 |
| `season_id` | str 64364, null 14341 |
| `season_number` | int 64465, null 14240 |
| `series_id` | str 78354, null 351 |
| `series_title` | str 78354, null 351 |
| `source` | str 78705 |
| `subtype` | str 78705 |
| `text_kind` | str 78705 |
| `title` | str 78705 |
| `title_it` | str 49321, null 29384 |
| `title_original` | str 50932, null 27773 |
| `wikipedia_url` | str 78705 |

## `tv_movies.jsonl` — 2578 record

| campo | tipi osservati (conteggio) |
|---|---|
| `cast` | str 2545, null 33 |
| `catalog_class` | str 2578 |
| `class_check` | str 2578 |
| `classification` | dict 2578 |
| `country` | list 2578 |
| `default_search_eligible` | bool 2578 |
| `director` | str 2534, null 44 |
| `entity_type` | str 2578 |
| `flags` | list 2578 |
| `genres` | list 2578 |
| `has_text` | bool 2578 |
| `ids` | dict 2578 |
| `ids_reliable` | bool 2578 |
| `language` | str 2487, null 91 |
| `lead_chars` | int 2578 |
| `lead_text` | str 2578 |
| `network` | str 1495, null 1083 |
| `original_classification` | dict 23 |
| `original_title` | str 2361, null 217 |
| `page_id` | int 2578 |
| `parent_ids` | list 2578 |
| `plot_chars` | int 2578 |
| `plot_flags` | list 2578 |
| `plot_heading` | str 2459, null 119 |
| `plot_text` | str 2578 |
| `plot_text_shared_by` | int 25 |
| `record_id` | str 2578 |
| `revision_id` | str 2578 |
| `season_id` | null 2578 |
| `series_id` | null 2578 |
| `subtype` | str 2578 |
| `text_kind` | str 2578 |
| `text_provenance` | dict 2578 |
| `title` | str 2578 |
| `wikidata_classes` | list 2578 |
| `wikipedia_url` | str 2578 |
| `year` | int 2578 |
| `year_end` | null 2556, int 22 |

## Chiavi e relazioni (misurate)

| relazione | chiave | cardinalità | verifica |
|---|---|---|---|
| `series` PK | `record_id` (`wp-<pageid>`) | — | 15697 id unici |
| `season` → `series` | `seasons.series_id` → `series.record_id` | N:1 (0..1: 28 orfane) | max 79 stagioni per serie; riferimenti rotti 0; 149 con padre in `uncertain` (record senza vettore) |
| `episode` → `series` | `episodes.series_id` → `series.record_id` | N:1 (0..1: 351 senza serie) | max 746 episodi per serie; rotti 0; 1 con padre in `uncertain` |
| `episode` → `season` | `episodes.season_id` → `seasons.record_id` | N:1 (0..1: 14341 senza stagione-pagina) | max 78 episodi per stagione; rotti 0 |
| `tv_movie` | `record_id` | nessuna relazione con serie/stagioni (`series_id`/`season_id` nulli: 2578/2578) | autonomo |
| stagione logica | `seasons.logical = true` | nodo senza testo né vettore | non presente in Qdrant |


## Collezione Qdrant `wikipedia_series_it_v1`

- punti 101706, vettore 1536 × Cosine, stato green
- indici di payload: `cast` (text), `catalog_class` (keyword), `country` (keyword), `creators` (text), `default_search_eligible` (bool), `director` (text), `entity_type` (keyword), `episode_number` (integer), `flags` (keyword), `genres_norm` (keyword), `ids_reliable` (bool), `imdb_id` (keyword), `network_norm` (keyword), `original_title_norm` (keyword), `plot_text` (text), `record_id` (keyword), `season_id` (keyword), `season_number` (integer), `series_id` (keyword), `series_title_norm` (keyword), `subtype` (keyword), `text_kind` (keyword), `title_base_norm` (keyword), `title_norm` (keyword), `year` (integer)
- campi aggiunti al record: `unit_id`, `embedded_text_kind`, `title_norm`, `original_title_norm`, `title_base_norm`, `series_title_norm`, `genres_norm`, `imdb_id`, `network_norm`, `text_embedded_prefix` (solo episodi)
- esempio di chiavi del payload di un punto: `air_dates`, `default_search_eligible`, `embedded_text_kind`, `entity_type`, `episode_number`, `flags`, `genres_norm`, `ids`, `imdb_id`, `lead_text`, `network_norm`, `numbering`, `original_title_norm`, `page_id`, `parent_ids`, `parent_page_id`, `plot_chars`, `plot_text`, `record_id`, `relation_status`, `revision_id`, `season_id`, `season_number`, `series_id`, `series_title`, `series_title_norm`, `source`, `subtype`, `text_embedded_prefix`, `text_kind`, `title`, `title_base_norm`, `title_it`, `title_norm`, `title_original`, `unit_id`, `wikipedia_url`
