# MovieLens parity: old `movie_db_search` against `cinema_sql` `movielens`

File: `cinema.v4.candidate5.sqlite3`. 99 cases, offline. Old = the old SQL on the MovieLens file (no TMDb); new = `CinemaSqlTool.run` end to end.

## Results

| operation | cases | identical top-k (after explained removals) | same set | mean overlap | no result (new) |
|---|---|---|---|---|---|
| top_rated | 6 | 6 | 6 | 1.0 | 0 |
| most_rated | 6 | 6 | 6 | 1.0 | 0 |
| by_genre_year | 38 | 38 | 38 | 1.0 | 0 |
| by_title | 25 | 25 | 25 | 1.0 | 1 |
| by_tag | 17 | 17 | 17 | 1.0 | 1 |
| stats_by_genre | 7 | 0 | 0 | - | 0 |

Old results removed because the catalogue knows them as non-films or documents their exclusion:

- excluded:outside_entry_rule:tvMiniSeries: 52
- not_film:miniseries: 44
- not_film:series: 16
- excluded:not_identifiable_via_imdb: 16
- excluded:outside_entry_rule:video: 13
- excluded:reconciliation_hold_same_title_and_year_in_cinema: 9
- excluded:outside_entry_rule:tvSeries: 8
- not_film:episode: 7
- excluded:id_belongs_to_an_episode_not_confirmed_by_title_and_year: 4
- excluded:outside_entry_rule:tvEpisode: 3
- excluded:another_movielens_film_has_the_primary_id_of_the_same_work: 2

Interruptions of the OLD tool's own 2 s guard before a warm retry: 0.

## Timings (ms, per case: median of warm repeats; then median and p95 over the cases)

| operation | cases | old median | old p95 | new median | new p95 | new/old (median) | old p95 first pass | new p95 first pass | CPU old median | CPU new median | CPU new p95 | CPU new/old |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| top_rated | 6 | 7.3 | 21.9 | 12.8 | 14.1 | 1.76 | 28.9 | 28.8 | 7.3 | 12.7 | 13.8 | 1.75 |
| most_rated | 6 | 2.1 | 9.0 | 12.4 | 13.2 | 5.85 | 11.5 | 25.6 | 2.1 | 12.4 | 13.2 | 5.93 |
| by_genre_year | 38 | 9.7 | 16.6 | 27.0 | 55.7 | 2.78 | 18.4 | 62.3 | 9.7 | 26.8 | 55.2 | 2.77 |
| by_title | 25 | 26.5 | 33.9 | 39.8 | 48.0 | 1.5 | 34.3 | 118.7 | 26.5 | 39.4 | 47.5 | 1.49 |
| by_tag | 17 | 14.2 | 24.8 | 20.1 | 25.2 | 1.42 | 350.0 | 75.8 | 14.2 | 19.8 | 24.8 | 1.4 |
| stats_by_genre | 7 | 18.9 | 79.3 | 56.8 | 134.5 | 3.0 | 91.6 | 152.5 | 18.8 | 55.9 | 132.8 | 2.97 |

## Cases that are not identical (7)

- `{"op": "stats_by_genre"}` status=ok differences={"Action": {"old": [2586, 3.123, 9608067], "new": [2562, 3.121, 9603199]}, "Adventure": {"old": [1722, 3.188, 7559459], "new": [1703, 3.186, 7545565]}, "Animation": {"old": [968, 3.337, 2181700], "new": [927, 3.335, 2166714]}, "Children": {"old": [999, 3.074, 2706005], "new": [986, 3.076, 2703585]},
- `{"op": "stats_by_genre", "year_from": 1990, "year_to": 1999}` status=ok differences={"Action": {"old": [430, 2.977, 3013599], "new": [428, 2.976, 3013464]}, "Adventure": {"old": [256, 3.059, 1995839], "new": [255, 3.055, 1987227]}, "Animation": {"old": [98, 3.339, 580088], "new": [92, 3.336, 570856]}, "Children": {"old": [200, 2.881, 911153], "new": [198, 2.881, 910785]}, "Comedy":
- `{"op": "stats_by_genre", "year_from": 2000, "year_to": 2009}` status=ok differences={"Action": {"old": [661, 3.11, 2885184], "new": [654, 3.109, 2883158]}, "Adventure": {"old": [435, 3.101, 2421862], "new": [429, 3.101, 2419548]}, "Animation": {"old": [296, 3.221, 791520], "new": [275, 3.218, 787459]}, "Children": {"old": [272, 2.925, 807626], "new": [266, 2.934, 805936]}, "Comedy"
- `{"op": "stats_by_genre", "year_from": 1950, "year_to": 1969}` status=ok differences={"Comedy": {"old": [314, 3.475, 340083], "new": [313, 3.473, 340027]}, "Documentary": {"old": [14, 3.729, 3594], "new": [13, 3.707, 3019]}, "Horror": {"old": [118, 3.112, 120391], "new": [117, 3.126, 120324]}, "Sci-Fi": {"old": [109, 3.062, 146096], "new": [108, 3.076, 146029]}}
- `{"op": "stats_by_genre", "year_from": 2010, "year_to": 2022}` status=ok differences={"Action": {"old": [894, 3.135, 1782449], "new": [883, 3.134, 1781408]}, "Adventure": {"old": [502, 3.181, 1331378], "new": [497, 3.179, 1330799]}, "Animation": {"old": [381, 3.313, 421174], "new": [370, 3.307, 419777]}, "Children": {"old": [271, 3.124, 326357], "new": [268, 3.121, 326120]}, "Comedy
- `{"op": "stats_by_genre", "genre": "Drama"}` status=ok differences={"Drama": {"old": [7499, 3.408, 13765337], "new": [7472, 3.408, 13754970]}}
- `{"op": "stats_by_genre", "genre": "Horror"}` status=ok differences={"Horror": {"old": [1798, 2.933, 2437608], "new": [1777, 2.938, 2432993]}}
