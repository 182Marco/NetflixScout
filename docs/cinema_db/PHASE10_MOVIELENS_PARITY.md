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
| top_rated | 6 | 7.4 | 20.5 | 12.7 | 13.1 | 1.71 | 97.5 | 32.0 | 7.3 | 12.6 | 13.1 | 1.73 |
| most_rated | 6 | 2.0 | 8.6 | 12.6 | 14.2 | 6.25 | 11.3 | 30.2 | 2.0 | 12.4 | 13.8 | 6.17 |
| by_genre_year | 38 | 9.4 | 16.6 | 26.9 | 54.3 | 2.87 | 25.5 | 56.7 | 9.4 | 26.8 | 54.1 | 2.86 |
| by_title | 25 | 25.7 | 31.6 | 37.1 | 46.6 | 1.44 | 43.3 | 48.8 | 25.5 | 36.7 | 46.6 | 1.44 |
| by_tag | 17 | 12.5 | 21.4 | 20.3 | 22.9 | 1.62 | 355.8 | 29.6 | 12.5 | 20.3 | 23.0 | 1.63 |
| stats_by_genre | 7 | 16.3 | 69.2 | 53.8 | 126.1 | 3.3 | 102.3 | 133.9 | 16.2 | 53.5 | 125.4 | 3.3 |

## Cases that are not identical (7)

- `{"op": "stats_by_genre"}` status=ok differences={"Action": {"old": [2586, 3.123, 9608067], "new": [2562, 3.121, 9603199]}, "Adventure": {"old": [1722, 3.188, 7559459], "new": [1703, 3.186, 7545565]}, "Animation": {"old": [968, 3.337, 2181700], "new": [927, 3.335, 2166714]}, "Children": {"old": [999, 3.074, 2706005], "new": [986, 3.076, 2703585]},
- `{"op": "stats_by_genre", "year_from": 1990, "year_to": 1999}` status=ok differences={"Action": {"old": [430, 2.977, 3013599], "new": [428, 2.976, 3013464]}, "Adventure": {"old": [256, 3.059, 1995839], "new": [255, 3.055, 1987227]}, "Animation": {"old": [98, 3.339, 580088], "new": [92, 3.336, 570856]}, "Children": {"old": [200, 2.881, 911153], "new": [198, 2.881, 910785]}, "Comedy":
- `{"op": "stats_by_genre", "year_from": 2000, "year_to": 2009}` status=ok differences={"Action": {"old": [661, 3.11, 2885184], "new": [654, 3.109, 2883158]}, "Adventure": {"old": [435, 3.101, 2421862], "new": [429, 3.101, 2419548]}, "Animation": {"old": [296, 3.221, 791520], "new": [275, 3.218, 787459]}, "Children": {"old": [272, 2.925, 807626], "new": [266, 2.934, 805936]}, "Comedy"
- `{"op": "stats_by_genre", "year_from": 1950, "year_to": 1969}` status=ok differences={"Comedy": {"old": [314, 3.475, 340083], "new": [313, 3.473, 340027]}, "Documentary": {"old": [14, 3.729, 3594], "new": [13, 3.707, 3019]}, "Horror": {"old": [118, 3.112, 120391], "new": [117, 3.126, 120324]}, "Sci-Fi": {"old": [109, 3.062, 146096], "new": [108, 3.076, 146029]}}
- `{"op": "stats_by_genre", "year_from": 2010, "year_to": 2022}` status=ok differences={"Action": {"old": [894, 3.135, 1782449], "new": [883, 3.134, 1781408]}, "Adventure": {"old": [502, 3.181, 1331378], "new": [497, 3.179, 1330799]}, "Animation": {"old": [381, 3.313, 421174], "new": [370, 3.307, 419777]}, "Children": {"old": [271, 3.124, 326357], "new": [268, 3.121, 326120]}, "Comedy
- `{"op": "stats_by_genre", "genre": "Drama"}` status=ok differences={"Drama": {"old": [7499, 3.408, 13765337], "new": [7472, 3.408, 13754970]}}
- `{"op": "stats_by_genre", "genre": "Horror"}` status=ok differences={"Horror": {"old": [1798, 2.933, 2437608], "new": [1777, 2.938, 2432993]}}
