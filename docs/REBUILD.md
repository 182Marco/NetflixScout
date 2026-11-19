# Rebuilding the data from a clean clone

The repository holds only code. Everything the application reads at runtime is **generated** and git-ignored (about 18 GB):
two Qdrant collections (`wikipedia_films_it_v3`, `wikipedia_series_it_v1`) and one SQLite database
(`cinema_db/data/cinema.v4.candidate6.sqlite3`, MovieLens included). This document is the one place that says how to
rebuild them, in order, with a checkpoint after every stage. It is written for a coding agent: run the stages in
sequence, run `python scripts/rebuild_status.py` after each one, and stop at the first checkpoint that fails.

## What you get: equivalent, not identical

The inputs are not frozen: the it.wikipedia dump of 2026-11-01 will disappear from Wikimedia, Wikidata keeps changing, and
IMDb republishes its datasets every day. A rebuild therefore gives a **functionally equivalent** result (same code, same
reviewed decisions, same schema, counts within a small margin), not the same bytes. Expect different content digests.
MovieLens is the exception: it never changes, so its tables are identical.

| Output | On the original machine | After a rebuild |
|---|---|---|
| `wikipedia_films_it_v3` | 41,138 points | about 41,100–41,300 |
| `wikipedia_series_it_v1` | 101,706 points (11,478 series, 9,971 seasons, 78,705 episodes, 1,552 TV films) | same order of magnitude, within about 1–2% |
| `movielens32m.sqlite3` | 87,585 films, 32,000,204 ratings, 2,000,066 tags | **exactly the same** |
| `cinema.v4.candidate6.sqlite3` | 476,271 works, 548,575 persons, 1,932,877 credits, 87,585 MovieLens films | within about 1–2%, different `content_sha256` |

## What you need

- A machine with **30 GB of free disk**, Python **3.11**, and a few hours (about **10–12 hours of machine time**, most of it unattended: the Wikidata
  enrichment of the films alone takes about 5 hours because it respects Wikimedia's rate limits).
- An **OpenAI API key** (`OPENAI_API_KEY`). It is the only key the rebuild needs; TMDb, OMDb and YouTube keys are for running the application, not for building the data.
- **About 8 USD** of OpenAI embeddings (`text-embedding-3-large`, 1,536 dimensions): films about 3.1 USD, series about 4.8 USD. Both paid steps refuse to start unless you authorise
  them in the shell for that one command (`FILMS_EMBED_AUTHORIZED=yes`, `SERIES_EMBED_AUTHORIZED=yes`); they print the estimate first.
- Internet access to `dumps.wikimedia.org`, `www.wikidata.org`, `query.wikidata.org`, `datasets.imdbws.com` and `files.grouplens.org`.

## Rules for the stages

1. Run everything **from the repository root**, with the virtual environment active.
2. Never run a paid step without reading its `plan` output first.
3. Every long step is **resumable**: if it stops, run the same command again.
4. Never edit the reviewed decision files (`pipelines/wikipedia_films/audit/*.json`, `pipelines/wikipedia_series/review/overrides.json`): they are what makes the rebuild match the original.
5. Do not read or print `.env`.

---

## Stage 0: environment and Qdrant

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-pipelines.txt pytest
cp .env.example .env            # fill OPENAI_API_KEY (and the other keys if you will run the application)
```

Qdrant **1.20.0** (the version is pinned together with `qdrant-client`): download the official binary from
https://github.com/qdrant/qdrant/releases/tag/v1.20.0, put the `qdrant` file in `bin/` (or set `QDRANT_BIN`), then in a second terminal:

```bash
./scripts/start_qdrant.sh       # leave it running; storage goes to dbVettoriale/qdrant_openai/storage
python scripts/rebuild_status.py
```

**Checkpoint:** the status script shows stage 0 `done` (Python 3.11, packages importable, Qdrant answering).

## Stage 1: films (`wikipedia_films_it_v3`)

The it.wikipedia dump is the input of both the film and the series pipelines. Wikimedia keeps only the latest dumps: if
`20261101` is no longer listed at https://dumps.wikimedia.org/itwiki/ , pick the newest one and use it **everywhere** (the same value in both variables below).
The labels inside the project (`itwiki-20261101-a`, `itwiki-20261101-large1536`) are only names and stay as they are.

```bash
export ITWIKI_DUMP_DATE=20261101                                   # or the newest dump date; read by the series pipeline and by cinema_db
export RAGWIKI_WIKIDATA_CONTACT="https://github.com/<you>/<your fork>"   # Wikimedia asks every client to identify itself; a repository URL is enough

python -m pipelines.wikipedia_films.pipeline --set dump.date=$ITWIKI_DUMP_DATE download     # about 4.3 GB, resumable
python -m pipelines.wikipedia_films.pipeline --set dump.date=$ITWIKI_DUMP_DATE extract      # about 35 min, offline: 4.1 M pages read, about 41,400 films with a plot
python -m pipelines.wikipedia_films.pipeline --set dump.date=$ITWIKI_DUMP_DATE --set wikidata.mode=online enrich   # about 5 h, free, resumable
python -m pipelines.wikipedia_films.pipeline --set dump.date=$ITWIKI_DUMP_DATE manifest
python -m pipelines.wikipedia_films.pipeline --set dump.date=$ITWIKI_DUMP_DATE verify       # "OK: the build matches the manifest"
```

The clean catalogue is derived offline from `films.jsonl` and the reviewed decisions:

```bash
python -m pipelines.wikipedia_films.audit.section_scan      # about 15 min: finds the plots that swallowed a sibling section
python -m pipelines.wikipedia_films.audit.run_audit         # classification of every record
git checkout -- pipelines/wikipedia_films/audit pipelines/wikipedia_films/AUDIT_NOYEAR_246.md   # run_audit rewrites versioned files: restore the reviewed ones
python -m pipelines.wikipedia_films.audit.build_clean build
python -m pipelines.wikipedia_films.audit.build_clean verify
python -m pipelines.wikipedia_films.audit.build_v3 build
python -m pipelines.wikipedia_films.audit.build_v3 verify
```

If `build_clean build` stops with `manual plot markers not found for <film id>`, that page changed in the newer dump: note the id in your final report and
skip it only if the code allows (do not edit the reviewed files); the rest of the catalogue is unaffected.

The embeddings (**paid**, about 3.1 USD for the whole catalogue, 30 minutes). On a new machine there are no earlier vectors, so every unit is requested:

```bash
python -m pipelines.wikipedia_films.indexing.v3 plan        # shows units, tokens and the estimated cost; no API call
FILMS_EMBED_AUTHORIZED=yes python -m pipelines.wikipedia_films.indexing.v3 embed     # paid; resumable; refuses above 4 USD (--max-usd to change)
python -m pipelines.wikipedia_films.indexing.v3 index       # creates wikipedia_films_it_v3 (refuses if it exists); no embedding is requested
python -m pipelines.wikipedia_films.indexing.v3 check       # every point against its record and vector; must print "ok": true
```

**Checkpoint:** `curl http://127.0.0.1:6333/collections` lists `wikipedia_films_it_v3` with about 41,100–41,300 points, and `v3 check` says `"ok": true`.

## Stage 2: series (`wikipedia_series_it_v1`)

It reads the dump downloaded in stage 1 (by path) and keeps its own Wikidata snapshot. Order matters.

```bash
python -m pipelines.wikipedia_series.phase0.scan_dump        # about 64 min, offline
python -m pipelines.wikipedia_series.phase0.harvest          # about 20 min
python -m pipelines.wikipedia_series.harvest_animation       # about 20 min
python -m pipelines.wikipedia_series.extract_series          # about 12 min
python -m pipelines.wikipedia_series.enrich_wikidata         # about 17 min, free, resumable
python -m pipelines.wikipedia_series.build_relations         # reads the reviewed pipelines/wikipedia_series/review/overrides.json
python -m pipelines.wikipedia_series.audit_series
python -m pipelines.wikipedia_series.build_clean build
python -m pipelines.wikipedia_series.check_catalog           # 24 consistency checks
python -m pipelines.wikipedia_series.build_clean verify      # "VERIFY OK: byte-identical rebuild"
python -m pipelines.wikipedia_series.embedding_units         # units, tokens and cost; no embedding yet
```

The embeddings (**paid**, about 4.8 USD, about 101,700 units, resumable):

```bash
python -m pipelines.wikipedia_series.embed plan
SERIES_EMBED_AUTHORIZED=yes python -m pipelines.wikipedia_series.embed run
python -m pipelines.wikipedia_series.embed verify
python -m pipelines.wikipedia_series.index plan
python -m pipelines.wikipedia_series.index build             # refuses if the collection exists
python -m pipelines.wikipedia_series.index check             # every point against its record and vector
```

**Checkpoint:** `wikipedia_series_it_v1` exists with about 101,700 points, `index check` reports 0 differences, and `python -m pytest pipelines/wikipedia_series/tests -q` passes.

## Stage 3: MovieLens

MovieLens 32M never changes, so this stage is exact. The CSV files are an **input of the cinema database build**, nothing reads them at runtime.

```bash
mkdir -p movie_db/data/raw && cd movie_db/data/raw
curl -O https://files.grouplens.org/datasets/movielens/ml-32m.zip && unzip ml-32m.zip && cd ../../..
python -m movie_db.harness.ingestion.build                    # movie_db/data/movielens32m.sqlite3 (about 1.3 GB)
```

**Checkpoint:** 87,585 movies, 32,000,204 ratings (the sum of `movie_stats.n_ratings`), 2,000,066 tags. The licence forbids redistributing the files: never commit them.

## Stage 4: the cinema database (`cinema_db`)

It needs stages 1, 2 and 3. All of it is offline except the two acquisition steps (Wikidata, IMDb).

```bash
# 4.1  targeted Wikidata requests (about 1,100 requests, free, sequential, resumable; reads only local files to decide what to ask)
python -m cinema_db.harness.enrich.fetch plan
for c in awards award_parents currencies persons countries languages relation_targets franchises companies places dual_use; do
  python -m cinema_db.harness.enrich.fetch run --category $c
done
python -m cinema_db.harness.enrich.fetch status               # nothing pending

# 4.2  the base catalogue (schema 2, about 7-12 min)
python -m cinema_db.harness.build.build --force               # writes cinema_db/data/cinema.sqlite3

# 4.3  the IMDb bulk datasets (1.4 GB). Keep THIS folder name: the layer build looks for it.
for d in title.basics name.basics title.principals title.crew title.ratings title.episode; do
  python -m cinema_db.harness.acquire.imdb fetch $d --dir cinema_db/data/imdb_snapshot/2026-11-08
done
python -m cinema_db.harness.acquire.imdb verify --dir cinema_db/data/imdb_snapshot/2026-11-08

# 4.4  local audits that feed the layer
python -m cinema_db.harness.audit.run_audit targets
python -m cinema_db.harness.audit.run_audit scan              # one streaming pass over the dump, about 15 min
python -m cinema_db.harness.audit.run_audit run
python -m cinema_db.harness.audit.run_a1 stage                # IMDb archive -> cinema_db/data/audit_a1/imdb_staging.sqlite3 (about 1.2 GB)

# 4.5  the schema-4 database: IMDb layer + every MovieLens film, genre and tag (about 15 min)
python -m cinema_db.harness.build.imdb_layer --movielens --out cinema_db/data/cinema.v4.candidate6.sqlite3
```

Optional but recommended check (builds a schema-3 file from the same inputs to compare against, about 15 more minutes):

```bash
python -m cinema_db.harness.build.imdb_layer --out cinema_db/data/cinema.v3.base.sqlite3
python -m cinema_db.harness.build.verify_movielens --new cinema_db/data/cinema.v4.candidate6.sqlite3 --base cinema_db/data/cinema.v3.base.sqlite3
```

**Checkpoint:** `verify_movielens` ends with an empty `problems` list; `build_info` says `schema_version` 4; the file opens under the application (stage 5).

**About `cinema_db/harness/candidate.py`.** It pins the digest of the original file. A rebuilt file has a different digest, so the **evaluation scripts** (not the application) will
raise `CandidateMismatch`. To use them on your build, copy the `content_sha256` printed by `verify_movielens` into `EXPECTED["content_sha256"]` in that file. The application does not check it.

## Stage 5: run

```bash
python scripts/rebuild_status.py                  # every stage must say done
./scripts/start_integrated.sh --check             # read-only: database file, schema, collections, tools, rules
python app.py                                     # the terminal chat; or nf-backend for the web API (see README)
python -m pytest -q -m "not integration and not qdrant_server"      # offline suite
```

## What is volatile and what to do

| Input | Why it changes | What to do |
|---|---|---|
| it.wikipedia dump | Wikimedia keeps only the latest dumps | use the newest date, set `ITWIKI_DUMP_DATE` and `--set dump.date=` to the same value; small count differences are expected |
| Wikidata | live data | the pipelines store every response in a local snapshot (`pipelines/*/data/cache/wikidata`); keep it if you want to rebuild offline later |
| IMDb datasets | republished daily | a newer file gives slightly different ratings and ids; keep the folder name `2026-11-08` as shown |
| OpenAI embeddings | the model can change | the model and dimensions are pinned in the code; vectors of the same text can differ in the last digits |
| MovieLens 32M | static | none: the result is exact |

## If something fails

- A step that was interrupted: run it again, it resumes.
- `QdrantUnavailable` / "Cannot reach Qdrant": start `./scripts/start_qdrant.sh`. A second Qdrant on the same storage crashes with `Can't init WAL`; stop the first one.
- `<collection> already exists`: the build commands refuse to overwrite. Drop the collection by hand only if you really want to rebuild it.
- A paid step refuses with "authorise": that is the guard; set the variable for that one command after reading the plan.
- A reviewed-decision mismatch (`build_clean`, `check_catalog`) on a newer dump: report it; do not edit the reviewed files.
- State and decisions history of each project: `pipelines/wikipedia_films/PROGRESS.md`, `pipelines/wikipedia_series/PROGRESS.md`, `docs/cinema_db/PROGRESS.md` (historical, not instructions).
