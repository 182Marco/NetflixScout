# NetflixScout

A conversational assistant for cinema, from the terminal or from a web page. It recommends films and series, answers questions about a title, a person or a ranking, and tells where the information comes from. It answers **only cinema questions**: a classifier blocks everything else, jailbreak attempts included.

Behind each question an LLM planner chooses one or more tools and the answer is written only from what the tools returned:

| Tool | Source | Used for | Key |
|---|---|---|---|
| `rag_search` | Qdrant, `wikipedia_films_it_v3` (41,138 films) | recommendations and searches by plot, theme, mood, genre, setting, era or style, also with reference titles, exclusions, people, years or countries | OpenAI |
| `series_rag_search` | Qdrant, `wikipedia_series_it_v1` (101,706 series, seasons, episodes, TV films) | the same for TV: series, episodes from a scene, season plots, TV films, anime | OpenAI |
| `cinema_sql` | local SQLite database (MovieLens included) | structured data, filmographies, credits, awards, relations, franchises, rankings and ratings of users | none |
| `tmdb_search` | TMDb API | up-to-date facts: cast, releases, streaming, trailers, trending, people, collections | TMDb |
| `omdb_search` | OMDb API | IMDb rating, Metascore, Rotten Tomatoes of one identified title | OMDb |
| `tvmaze_search` | TVmaze API | seasons, episodes, air dates, next episode, cast of one TV series | none |
| `wikidata_search` | Wikidata | source works, remakes, adaptations, order in a series, franchises, homonyms | none |
| `wikipedia_search` | Wikipedia (MediaWiki API) | encyclopedic information: biographies, history and production, anthologies, comparison with the source novel | none |
| `youtube_search` | YouTube Data API v3 | interviews, making-of, behind the scenes, commentary on one identified film | YouTube |

`cinema_sql` and `series_rag_search` are on by default; `CINEMA_DB_ENABLED=0` and `SERIES_RAG_ENABLED=0` switch each off on its own (the film RAG and the external tools stay).

## Start the services (two terminals, from the repository root)

NetflixScout needs two processes: **Qdrant** (the database that stores the film and series vectors, so the app can search by meaning) and the **backend** (the program that receives the questions, calls the tools and the AI model, and streams the answer to the web page). Qdrant must be up before the backend.

**One-time setup: four aliases** (add them to `~/.zshrc`, then run `source ~/.zshrc`; replace the path if the project lives elsewhere):

```bash
alias nf-qdrant='/path/to/NetflixScout/scripts/start_qdrant.sh'
alias nf-backend='/path/to/NetflixScout/scripts/start_backend.sh'
alias nf-stop='/path/to/NetflixScout/scripts/stop_services.sh'
alias nf-status='/path/to/NetflixScout/scripts/status_services.sh'
```

| Step | Alias | What it does |
|---|---|---|
| 1. Terminal 1 | `nf-qdrant` | Starts the vector database on `127.0.0.1:6333`. Leave the terminal open. |
| 2. Terminal 2 | `nf-backend` | Starts the API on `127.0.0.1:8000` (it refuses to start if Qdrant is down or the port is taken). Leave it open. |
| 3. When you finish | `nf-stop` | Stops Qdrant and the backend cleanly (also the ones left running in closed terminals). |
| Any time | `nf-status` | Read-only check: for each port (6333, 8000, 8001, 8080) says `RUNNING` or `free`; exit code 0 means everything is stopped. |

Ready when `curl http://127.0.0.1:6333/collections` lists `wikipedia_films_it_v3` and `wikipedia_series_it_v1`, and `curl http://127.0.0.1:8000/health` answers `{"status":"ok"}`.

Without aliases the same commands are `./scripts/start_qdrant.sh`, `./scripts/start_backend.sh` (= `source .venv/bin/activate && uvicorn web_api.main:app --host 127.0.0.1 --port 8000`), `./scripts/stop_services.sh` and `./scripts/status_services.sh`. `./scripts/start_integrated.sh --check` is a read-only check of the integrated runtime (database file, schema and digest, flags).

- A second Qdrant on the same storage crashes with `Can't init WAL: Kind(WouldBlock)`: one is already running, often in a closed terminal (`nf-stop` finds it by port). Check with `lsof -nP -iTCP -sTCP:LISTEN | grep -E ":(6333|8000|8001|8080)\b"`. Never `kill -9` Qdrant.
- `scripts/start_qdrant.sh` runs the official Qdrant 1.20.0 binary over `dbVettoriale/qdrant_openai/storage`. It looks for the binary in `$QDRANT_BIN`, then `bin/qdrant` (not versioned), then the `PATH`; if none is found it says where to put it (https://github.com/qdrant/qdrant/releases/tag/v1.20.0).
- The backend uses **one worker only** (conversations live in memory). For the terminal chat use `python app.py` instead of `nf-backend`.
- `nf-backend` lets the browser call the API from `localhost` and `127.0.0.1` on ports 8080, 8081 and 5173 (CORS); another origin: `WEB_API_CORS_ORIGINS="http://host:port,..." nf-backend` (it replaces the list, so repeat the ones you need). A "CORS error" with the backend running means the page origin is not in the list.
- `nf-stop` stops ports 6333, 8000 and 8001; add the frontend with `PORTS="6333 8000 8001 8080" nf-stop`.

## Prerequisites and setup

Python 3.11, a virtual environment, and API keys in `.env` (copy `.env.example`):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env
```

```env
OPENAI_API_KEY=...              # classifier, planner, parsers, rerankers, embeddings, answer
VUE_APP_TMDB_API_KEY=...        # TMDb v3 API key or v4 read access token
VUE_APP_TMDB_BASE_URL=https://api.themoviedb.org/3
YOUTUBE_API_KEY=...             # YouTube Data API v3 key (Google Cloud project)
OMDB_API_KEY=...                # OMDb key (free: 1,000 requests a day; non-commercial use)

VECTORSTORE_QDRANT_URL=         # where the Qdrant server is; empty = http://127.0.0.1:6333
CINEMA_DB_ENABLED=              # empty = on; 0/false/no/off switches cinema_sql off
CINEMA_DB_PATH=                 # another database file than the default
SERIES_RAG_ENABLED=             # empty = on; 0/false/no/off switches series_rag_search off
```

Wikipedia, TVmaze and Wikidata need no key. Each key is read by one module only, on the first use of its tool (`tool/tmdb/auth.py`, `tool/youtube/auth.py`, `tool/omdb/auth.py`) and never appears in code, logs, traces, cache or frontend. The `VUE_APP_` prefix of the TMDb variables is the Vue CLI convention for variables exposed to client bundles: never point a Vue frontend at this `.env`.

Dependencies (`requirements.txt`, pinned): `openai`, `qdrant-client` (same version as the server), `pydantic`, `python-dotenv`, `numpy`, `fastapi`, `uvicorn`, `sqlglot`. The external tools use only the standard library (`urllib`). To rebuild the data (next section) install `requirements-pipelines.txt` instead: it adds `pyyaml`, `mwparserfromhell` and `tiktoken`.

## Rebuilding the data from a clean clone

The repository holds **only code**. Everything the application reads at runtime is generated and git-ignored (about 18 GB): the two Qdrant collections (`wikipedia_films_it_v3`, `wikipedia_series_it_v1`) and the SQLite database `cinema_db/data/cinema.v4.candidate6.sqlite3`. Without them `python app.py` stops at start with a message pointing here.

**[`docs/REBUILD.md`](docs/REBUILD.md) is the one document to follow**: six stages in order (environment, films, series, MovieLens, `cinema_db`, run), each with its commands, time, cost and a checkpoint with the expected numbers. `python scripts/rebuild_status.py` is a read-only report of which stages are done and which command comes next; it never calls an API.

- **What you need:** Python 3.11, about 30 GB of disk, an OpenAI key, internet access, about 10–12 hours of mostly unattended machine time, and about **8 USD** of embeddings (films about 3.1, series about 4.8). The two paid steps refuse to start unless you authorise them in the shell for that one command (`FILMS_EMBED_AUTHORIZED=yes`, `SERIES_EMBED_AUTHORIZED=yes`).
- **What you get:** an *equivalent* result, not the same bytes. The it.wikipedia dump of the original build will disappear from Wikimedia, Wikidata keeps changing and IMDb republishes its datasets daily, so counts agree within about 1–2% and content digests differ. MovieLens is static: its tables come out identical.
- **Why the data is not in git:** 18 GB cannot live in a repository, the IMDb and MovieLens licences forbid redistributing their data, and the sources are not reproducible byte for byte anyway.

## Run

```bash
python app.py          # terminal chat (exit / quit to leave)
```

If Qdrant is down, a collection is missing, or the database file is missing, `app.py` stops with one line telling you what to start or build. The web server is described in "HTTP / SSE server".

**One turn:**

1. The domain classifier (`query_classifier/`, `gpt-4o-mini`) looks at the last message and the last exchange of the history. A non-cinema message gets a one-line refusal in its language, with no tool and no story. The classifier also returns the **language of the turn**: only the last message counts, so the user can switch language at any point.
2. The orchestrator (`orchestrator.py`), in one LLM call, rewrites the question as a standalone query from the history, picks the first tool and lists the parts of the request. A composite request ("a film and an interview with the director") runs several tools in the same turn, each one with the data of the previous ones, up to `max_tool_calls_per_turn` (10). A question about a film or series that the request and the history do not identify gets a clarifying question instead of a tool call.
3. A tool can offer more (`follow_up`: what it read and what it left out); the orchestrator then asks the planner whether the data is enough. Other per-turn limits: 12 planner calls, 180 seconds of tool loop, 200,000 planner tokens; when one is reached the turn answers with what it has.
4. Every step is narrated while it happens: a few plain sentences (what is searched and where, outcome, seconds, fallbacks, parts not searched), then the detail block of each tool.
5. The final answer is **one streaming LLM call**, written only from the tool results, in the language of the last message, with the rules of the tools used. Tools never name their sources in the text: the interface shows them with links and licences.
6. When the history reaches `memory_window_size` (12) messages it is compacted into a summary that **replaces** it (not appended), and a short notice is shown.

The planner's own settings per turn: `k_finale`, the number of films the user asked for (1–10, default 3 for films, 5 for series).

## Project layout

```text
/
├── app.py              # CONFIG, build_app, handle_query (no printing) and the terminal chat
├── orchestrator.py     # LLMOrchestrator: planning, multi-tool loop, final answer
├── planner_rules_v4.py # planner routing rules of the integrated architecture (cinema_sql + the two RAGs)
├── turn.py             # channel-neutral TurnResult / TraceStep / TurnObserver
├── answer_stream.py    # decodes the streamed `answer` field out of a chunked JSON
├── conversation.py     # compaction of the conversation history
├── query_classifier/   # domain (cinema or not, anti jailbreak) and language of the turn
├── preferences/        # user settings applied per turn (they prevail over the request); web channel only
├── tool/               # ONLY the tools the agent can call (app.py is the only wiring point), one package per tool
│   ├── rag/                # two tools: film/ = rag_search, series/ = series_rag_search, shared/ = what both use
│   ├── cinema_db/          # cinema_sql: read-only SQL on the local cinema database (MovieLens included), 16 operations
│   ├── tmdb/               # tmdb_search
│   ├── youtube/            # youtube_search
│   ├── wikipedia/          # wikipedia_search
│   ├── omdb/               # omdb_search
│   ├── tvmaze/             # tvmaze_search
│   └── wikidata/           # wikidata_search
│       # the six tools with network access have http.py as their single I/O module; tmdb, omdb, wikidata and wikipedia also have an optional harness/ live check (never imported at runtime)
├── cinema_db/          # data side of the cinema database: schema, offline build, audit/enrich/verify harness; data/ is not versioned
├── movie_db/           # MovieLens as a BUILD INPUT of cinema_db (not a tool): schema.py, harness/evaluation/ (application-level evaluations), data/ (CSV + SQLite, not versioned)
├── pipelines/          # offline data pipelines (wikipedia_films, wikipedia_series): never imported by the app
├── presenters/         # the only output layer: present(turn, channel)
│   ├── channel.py      # OutputChannel (terminal | web)
│   ├── story_view.py   # the turn story: a few plain sentences (what, where, how it went), it/en/de
│   ├── *_view.py       # channel-neutral views of the tool steps (rag, series, cinema, api = TMDb, youtube, wikipedia, omdb, tvmaze, wikidata) and calls_view.py (HTTP calls)
│   ├── terminal/       # box.py, session.py, blocks.py, renderer.py (TerminalObserver, STEP_RENDERERS) + one folder per tool
│   └── web/            # observer.py (WebObserver, live events), payload.py (to_payload, STEP_SERIALIZERS) + one folder per tool
├── web_api/            # HTTP/SSE server (FastAPI): conversations, streamed answer, web_lists; see contracts/
├── web_lists/          # web channel only: the lists of films/videos returned with the final answer
├── scripts/            # start_qdrant.sh, start_backend.sh, start_integrated.sh, status_services.sh, stop_services.sh, backup_qdrant_storage.py, rebuild_status.py
├── docs/               # REBUILD.md (how to rebuild every generated file), docs/cinema_db/ (plan, progress, NEXT_SESSION, schema maps, checklists), frontend handoff notes
├── tests/              # offline tests (+ test_tool_package.py: layout of tool/ and import rules)
├── requirements.txt            # what the application needs
├── requirements-pipelines.txt  # + what rebuilding the data needs (docs/REBUILD.md)
├── dbVettoriale/       # local Qdrant storage (not versioned)
├── bin/                # local binaries, e.g. the Qdrant server (not versioned)
└── mappa.html          # interactive project map (open it in a browser)
```

`tool/` holds only the tools the agent can call; a new tool goes in `tool/<name>/`, never in the root. Tools do not import each other, nor presenters or channels (`tests/test_tool_package.py` checks it). All parameters live in `CONFIG` in `app.py`; overrides go through `build_runtime_config(overrides)`. The public runtime API is `CONFIG`, `build_runtime_config`, `build_app` and `handle_query`, which runs one turn without printing and returns a `TurnResult`: the channel (`presenters/`) decides how to show it.

## The vector index (Qdrant)

A semantic search matches meaning, not words. Every film (and every series, season, episode and TV film) is stored as a 1,536-number vector (`text-embedding-3-large`, cosine similarity). Qdrant is the only vector store, a server at `http://127.0.0.1:6333` over `dbVettoriale/qdrant_openai/storage`. The two RAGs **only read** it; the collections are built offline by `pipelines/`:

- `wikipedia_films_it_v3`: 41,138 points, one per film, with the plot of Italian Wikipedia.
- `wikipedia_series_it_v1`: 101,706 points: 11,478 series, 9,971 seasons, 78,705 episodes with plot, 1,552 TV films.

Settings: `CONFIG["rag"]["vectorstore"]` and `CONFIG["series_rag"]`. Older collections (`netflix_scout`, `wikipedia_films_it`, `wikipedia_films_it_v2`) may still sit in the storage as unused data. A verified copy of the storage (server stopped, new destination) is made with `python scripts/backup_qdrant_storage.py backup --storage dbVettoriale/qdrant_openai/storage --dest NEW_FOLDER`.

## Film RAG (`rag_search`)

`RagTool` (`tool/rag/film/tool.py`) follows the `Tool` Protocol of `orchestrator.py`; its input schema comes from the Pydantic model `FilmIndexToolInput` (`query` and `k_finale`). The planner passes the **whole request** in `query`, positive and negative parts together. The retriever (`tool/rag/film/retrieval/`) is one dense search over one collection: no RRF, no fusion, no fallback to another index.

1. **Parser** (`parser.py`, one call to `gpt-5.6-luna`): the request becomes `Signals`: the wanted description (Italian and English), cited films, films and franchises to exclude, narrative traits to avoid written positively, genres, formats, year range, countries, directors, actors, rare plot words, and whether the request contradicts itself. If the parser fails the plain request is searched and the answer says so.
2. **Search** (`search.py`, `index.py`): positive filters (year, country, director, actor, rare plot words) run inside Qdrant; the query vector is the centroid of the wanted description and the cited films; the wide pool (**at most 50** candidates) loses the cited films, the franchises (by id and by name), the avoided genres (never a genre that is also wanted or that labels more than 8% of the catalogue) and the avoided formats; the traits to avoid are penalised: `cos(r, wanted) - 0.5 * max cos(r, trait)`. A film cited as a model that is not in the catalogue is described to the embedder with a short summary written by the parser; nothing is written to Qdrant.
3. **Reorder** (`service.py`, the only module that talks to OpenAI): the best 40 are reordered by `gpt-5.6-sol` without reasoning, reading up to 1,500 characters of each plot (about 3 s; if it fails the penalty order stays and a note says so).
4. **Result**: titles, original titles, year, director, cast, countries, duration and the notes about contradictions, empty filters and failures reach the answer; ids and URLs do not.
5. **Poster and TMDb id**: `tool/tmdb/enrich.py` completes only the films the RAG returned with one `/find` by IMDb id each (never a search by title, never the pool, nothing written). A film without IMDb id is skipped. The same enricher serves the series RAG.

The step is shown in three phases: `retrieval` (the wide pool with similarity), `rerank` (the whole pool as reordered, with the engine that decided) and `selection` (the films chosen). Known limits: `franchise_id` exists for about 10% of the films, `genres` is free text, contradiction detection is stochastic, plots are less complete after 2019.

## Series RAG (`series_rag_search`)

`tool/rag/series/` has the same shape on `wikipedia_series_it_v1`: one dense retriever with a mandatory **level** (series, season, episode, TV film), `SeriesRagToolInput` (`query`, `k_final`) and the same three phases. The parser extracts the level, a named series (resolved to a `series_id` that constrains seasons and episodes), season and episode numbers, filters and exclusions; listing the children of a series is done by numbering, without vectors. Details:

- A title that is not in the catalogue gives zero results (`series_not_in_index`), never a guess.
- Pages that mix manga and anime (`default_search_eligible = false`) are hidden from searches by description and reachable by exact title.
- Reorder: 40 candidates, 1,000 characters of plot, `gpt-5.6-sol`; wide pool at most 50.
- A search that finds nothing offers one step to `tmdb_search` or `tvmaze_search`, never a second try with this tool.
- No HTTP request to third parties. The sources are Italian Wikipedia and Wikidata (CC BY-SA 4.0, shown with link).

Limits: seasons often have only the introduction, episode numbering has gaps and title variants, franchises such as Star Trek resolve only on the exact title, homonyms (Lost) are resolved by TVmaze with a question to the user. Episode lists and numbering belong to `tvmaze_search`.

## Local cinema database (`cinema_sql`)

A SQLite database of films, series, seasons, episodes, people, credits, genres, identifiers, ratings, awards, companies and franchises. The agent reads it through `cinema_sql` (`tool/cinema_db/`), which uses no network and no LLM. The file is `cinema_db/data/cinema.v4.candidate6.sqlite3` (schema 4, git-ignored); its name and data digest are set in one place, `cinema_db/harness/candidate.py`, and the start checks that the file opens with its policy.

**Operations (16):** `find_work`, `find_person`, `work_card`, `filmography`, `cast`, `crew`, `collaborations`, `awards`, `series`, `companies`, `franchise`, `relations`, `ratings`, `movielens`, `provenance`, and `sql` (a free SELECT on the approved views). The model never writes SQL except in `sql`. Names are matched after normalisation (titles, originals, aliases), ids are reused when known, a homonym comes back as a list of alternatives and never as an answer, and every result carries notes on what the data cannot prove and the reliability of each field. An identity that is only probable or uncertain must be said so in the answer. At most 12 queries per turn.

**Security:** one `SELECT` only, approved views and columns only (the model reads the `v_*` views), the text that runs is the one regenerated from the validated AST (`sqlglot`), SQLite opened `mode=ro` and `immutable`, deny-by-default authorizer, limits on time, rows and size; FTS5 title search (words and prefixes, not semantic). `ATTACH` is forbidden.

**What it holds:** the Wikipedia and Wikidata catalogue, a layer of IMDb data (primary identifiers, type, year, runtime, ratings per source, billing order), identifiers, and every film, genre and tag of MovieLens. Nothing is invented: what the sources do not state stays empty. Known limits: incomplete catalogue, awards attached to a person only when the nominee is recorded, unreliable episode counts, a "franchise" that can be a list, remakes not distinguishable, release type by country not available.

### MovieLens

MovieLens 32M (87,585 films, 32 million ratings, 2 million tags; CSV in `movie_db/data/raw/`, SQLite in `movie_db/data/`, both git-ignored: the licence forbids redistribution) is **not a tool and nothing reads it at runtime**. It is an input of the offline build of `cinema_db`: `cinema_db/harness/build/movielens_layer.py` copies its films, genres and tags into the schema-4 file (tables `ml_movie`, `work_ml_genre`, `work_tag`; views `v_ml_movie`, `v_ml_genre`, `v_work_tag`), joining a film only through the IMDb id that MovieLens gives. At runtime the rankings, average ratings, rating counts, genre statistics and tags are the **`movielens` operation of `cinema_sql`** (`ml_mode`: `top_rated`, `most_rated`, `by_title`, `by_tag`, `genre_stats`). `movie_db/harness/ingestion/` builds `movie_db/data/movielens32m.sqlite3` from the CSV files (`python -m movie_db.harness.ingestion.build`, offline; the build of `cinema_db` reads that file); `movie_db/schema.py` keeps the MovieLens vocabularies and DDL; `movie_db/harness/evaluation/` holds the evaluations of the whole application. MovieLens has no cast, directors or critics' reviews; coverage: films up to 2022, ratings up to October 2023. `genre_stats` counts films only; `ratings` without `type` covers films and series.

### Building and checking the database (offline, no network, no credits)

The full sequence, with the acquisition steps it depends on (Wikidata, IMDb, MovieLens), is stage 4 of [`docs/REBUILD.md`](docs/REBUILD.md); these are the commands of the last steps:

```bash
python -m cinema_db.harness.build.imdb_layer --movielens --out NEW_PATH      # builds a schema-4 file; always a NEW path (needs the inputs of docs/REBUILD.md, stages 1-4)
python -m cinema_db.harness.build.verify_movielens --new NEW_PATH            # independent check against MovieLens and the base
python -m cinema_db.harness.schema.generate                                  # rewrites docs/cinema_db/schema.html, schema.mmd and tool/cinema_db/approved_views*.py
python -m cinema_db.harness.schema.generate --check                          # exit 1 if they are stale
python -m cinema_db.harness.tool_eval.run_benchmark                          # benchmark of cinema_sql on the real database (~10 s)
```

The project sits on a synced folder: after a large build compare `build_info.content_sha256` with the build report, because sync clients can create conflict copies (`… 2`). Open **`docs/cinema_db/schema.html`** in a browser for the interactive map of the schema (tables, columns, keys, indexes, checks, relations, public views); `schema.mmd` is the Mermaid ER diagram of the same schema. Plan, decisions, state and the resumption point: `docs/cinema_db/PLAN.md`, `PROGRESS.md`, `NEXT_SESSION.md`; start and rollback of the integrated runtime: `docs/cinema_db/INTEGRATED_LOCAL.md`.

## Data pipelines (offline, not imported by the app)

- `pipelines/wikipedia_films/` builds, verifies and evaluates the film collection from the Italian Wikipedia dump and Wikidata. Offline checks: `python -m pipelines.wikipedia_films.audit.build_v3 verify` and `python -m pipelines.wikipedia_films.indexing.v3 check` (read-only).
- `pipelines/wikipedia_series/` does the same for series, seasons, episodes and TV films (dump `itwiki-20261101` plus Wikidata). TV films never belong to a series. Checks: `python -m pipelines.wikipedia_series.build_clean verify` (byte-for-byte rebuild), `python -m pipelines.wikipedia_series.check_catalog`, `python -m pipelines.wikipedia_series.embed verify`, `python -m pipelines.wikipedia_series.index check` (every point against its record and vector, read-only), `python -m pytest pipelines/wikipedia_series/tests -q`. State, commands, hashes and costs: `pipelines/wikipedia_series/PROGRESS.md`.

The two pipelines never import each other, and the series retriever exists once, in `tool/rag/series/retrieval/`, which the pipeline's evaluation scripts import. `embed … run` is **paid** (OpenAI embeddings) and needs an explicit authorization variable.

## TMDb tool (`tmdb_search`)

Queries The Movie Database API for up-to-date facts: cast and crew, release dates, streaming providers, trailers, images, reviews, recommendations, TV series with seasons and episodes, people and filmographies, collections, companies, discover by filters, trending and charts, genres and certifications (17 typed operations, `tool/tmdb/models/operation_rules.py`). Account, session, write, list, `changes` and deprecated endpoints are not exposed.

The planner fills `arguments.requests` (1 to 4 operations) from the schema in the planning prompt; the model never builds URLs. Python validates every request before any call, resolves titles and names to ids (TMDb id → IMDb/TVDB/Wikidata via `/find` → search), maps each operation to a fixed endpoint and uses `append_to_response` for facets. A result is accepted for a title only if TMDb lists that title (translated or alternative titles of the same work, year ±1); otherwise it returns `unverified_match` with the closest results as unverified candidates. Discover returns only released titles unless the user asks for upcoming ones, drops undated titles when the list depends on dates, and applies the filters it actually used (`applied_filters`). TMDb votes are the audience's, never critics'.

`CONFIG["tmdb"]` has exactly three settings:

| Setting | Default | Meaning |
|---|---|---|
| `max_results` | 5 | items returned by searches, discover, trending, charts and related-title lists |
| `max_calls_per_turn` | 10 | HTTP attempts per turn: the only call limit (`tool/tmdb/budget.py`) |
| `cache_ttl` | 3600 | seconds a response is reused across turns (0 = per-turn memo only) |

Cache and memo hits cost nothing; every attempt sent counts, also when it fails; a 429 pauses calls for `Retry-After` without retries; failures become partial results, never a broken turn. The data passed to the LLM is bounded (`tool/tmdb/prompt_budget.py`: identity and essentials always kept, long lists capped, omissions listed in `metadata.tmdb.omitted`). Data is requested in the turn language (`it-IT`, `en-US` or `de-DE`, translations appended as fallback; providers for region `IT`). A request that finds nothing offers one step to another tool (`not_found`, `unverified_match`, `empty`).

The step `tmdb_calls` lists every request actually sent, method and full URL, with only the key masked. Streaming data is provided by JustWatch and the interfaces show the credit whenever provider data is used. Optional live check (3 real calls): `python -m tool.tmdb.harness.live_smoke --live`.

**Terms:** TMDb's terms forbid use with AI applications; this project is used personally, as a portfolio. TMDb attribution (logo, and the notice that the product uses the TMDB API but is not endorsed or certified by TMDB) belongs in the web frontend's About section.

## YouTube tool (`youtube_search`)

Searches YouTube for videos about one identified film: interviews with the director (`director_interview`) or the cast (`cast_interview`), making-of, behind the scenes, featurettes and the authors' commentary. Trailers stay with `tmdb_search` unless the user asks for YouTube.

The planner fills `title` and `kinds` (1–3, most important first) and, only with values written in the request or the conversation, `year`, `director`, `cast` (up to 5 names) and `alternative_titles` (up to 3). Python builds each search from constant fragments; for a one-word title with a known person the person is required. `CONFIG["you_tube"]`: `max_results` 3 (videos per kind) and `max_searches_per_turn` 2.

**Quota:** `search.list` has its own bucket of **100 calls a day** per Google Cloud project (1 unit each), shared with every other client of the project; `videos.list` uses the 10,000-unit bucket. With the defaults a turn spends at most 2 searches and 1 `/videos` call. There is no local counter: after an observed `quotaExceeded` the tool pauses that bucket until midnight Pacific Time, in memory only. No cache across turns.

**Relevance:** the snippet title only drops reactions, parodies, fan-made videos, concept trailers and conflicting years; everything else is judged on the full `/videos` data. A video is dropped only on strong evidence (film and people not named, another declared format, unconfirmed homonym, self-declared Short, no longer available), otherwise it is kept in API order and labelled `confirmed` or `to_verify`. The kind is confirmed only by a word of the kind in the video title; a one-word title with no year or person to check is kept as to verify only with film context. The answer lists confirmed videos first and the others under "Da verificare". The step `youtube_calls` shows every request, the videos exactly as returned, the drops per reason and the kinds not searched.

**Policy:** this application uses YouTube API Services and shows YouTube as the source of every video result. The Developer Policies (III.A.2) require the application's own privacy policy, which this personal project does not have.

## Wikipedia tool (`wikipedia_search`)

Reads Wikipedia (MediaWiki Action API, no key) for encyclopedic information TMDb does not have: in-depth biographies and careers, history and production of a film, movements, which director or actor made which segment of an anthology, episode structure, a film compared with its source novel, detailed plots. Cast, crew, release dates, short plots, streaming and ratings stay with TMDb.

- **One edition per run.** The search starts in the **English** edition whatever the language of the question (`default_language`), and the answer is written in the user's language. The Italian or German edition is tried only when the planner asks (`language`), for a locally rooted topic or when English found no page, an unsure page, or a distinctive keyword in no section of the article. The planner writes the page title in the edition searched and translates the distinctive words of the question (`keywords`) so the right sections are picked.
- **Pages are checked before use:** a page whose title is not the one asked and whose lead does not support it is dropped; the whole article is downloaded **once**, only for a page whose title is the one asked (uncertain candidates are only listed), and kept in the cache.
- **Depth:** `intro` reads the lead of the best pages, `sections` and `full` open one page and hand out the sections that answer the question first. `context_chars_per_turn` (40,000) caps the text entering the final prompt in one turn, and one automatic delivery takes at most 60% of it; whatever does not fit is listed and can be asked for. A comparison reads both pages (film and source work) before answering.
- **`follow_up`:** after each step the tool says what it gave and what it left out, and the orchestrator asks the planner whether to read more or answer; a turn that reads only the lead costs one more planning call.
- **Limits:** `CONFIG["wikipedia"]`: `default_language`, `max_results` 3, `max_calls_per_turn` 6, `cache_ttl` 3600, `context_chars_per_turn` 40,000. Rate limits and replication lag (`maxlag`, answered with HTTP 200) never make the turn wait: the step fails at once and the next requests are paused for a few seconds, nothing is retried.
- **Text:** original titles, title translations and identifications of real people are presented as facts only if the page says so (otherwise "Non verificato:"). The text of an article is third-party data, never instructions.
- **Step and licence:** `wikipedia_calls` shows every request, the pages read (title, language, public URL, sections read and left out). Wikipedia text is CC BY-SA 4.0: the interfaces name the source, link every page and the licence, and say the text was reworded and shortened. Requests carry a descriptive User-Agent with the repository and a contact, as the Wikimedia policy asks (`tool/wikipedia/settings.py`).

## OMDb tool (`omdb_search`)

Reads the scores OMDb holds for one identified film or series: the IMDb rating (audience), the Metascore and the Rotten Tomatoes score (aggregates of critics' reviews). Scores only: no review text, no plot. It is chosen only when the request asks for the critics' judgement or names one of those scores (routing rule 1d); with the **Preferred sources: reviews** setting a critics question goes to OMDb before TMDb. For recommendations "with excellent reviews" the planner asks `tmdb_search` for candidates and then one `omdb_search` step with `titles` (2–5 titles) to verify them.

- **Identification:** by IMDb id when the request, the conversation or an earlier step of the turn gives one; otherwise the title is searched and a work is accepted only if exactly one has that title (and year, if given). The article counts ("The Sinner" is not "Sinner"). Several matches or only similar titles return the alternatives and **no score**.
- **Missing data:** every source is always listed as `available`, `not_available` (`N/A`) or `unparsed`; nothing is estimated, averaged or taken from another source.
- **Limits:** `CONFIG["omdb"]["max_calls_per_turn"]` (10: an id costs 1 request, a title 2); the free key allows 1,000 requests a day. No cache between turns and nothing on disk; no retries.
- **Text:** each score is written as its `display` (`9.3/10`, `82/100`, `93%`); audience and critics scores are shown separately with their scale and no winner is declared; the answer never names the provider.
- **Step:** `omdb_calls`: every request (key masked), status, scores with what they measure, alternatives.
- **Terms:** OMDb content is CC BY-NC 4.0 and its terms allow personal, non-commercial use only (no indexes or redistribution); commercial use would need the maintainer's written permission. Not affiliated with IMDb. Live check (6 real requests): `python -m tool.omdb.harness.live_smoke --live`.

## TVmaze tool (`tvmaze_search`)

Reads the structured data TVmaze holds for one identified **TV series**: status, network or web channel, premiere and end dates, runtime, language, genres, a short summary, the cast with character names, the seasons, the episodes of one season with numbering and air dates, and the upcoming episode. Episode summaries are never read (spoilers). No key.

- **Routing** (rule 1e): TVmaze for seasons, episodes, numbering, air dates, next episode, cast and the plain facts of a series; always the owner of episode lists. TMDb keeps general descriptions, creators, streaming, trailers, reviews, recommendations; Wikipedia keeps history and production; films are never routed here. A source named by the user wins.
- **Fallback:** a series TVmaze does not know (it holds mostly original or English titles), a rate limit, a timeout or a network error make the tool offer ONE step to `tmdb_search`. A section that fails does not lose the rest. When TMDb and TVmaze disagree the answer reports TVmaze and says they differ.
- **Limits:** `CONFIG["tvmaze"]["max_calls_per_turn"]` (6): identifying a series costs 1 request, the card with cast or next episode, the seasons and the episodes one each. TVmaze documents at least 20 calls every 10 seconds per IP address; after an HTTP 429 nothing is sent for a few seconds, no retries, no cache.
- **Known limits:** two series with the same title ("Friends") give a question back to the user; a title with a qualifier ("The Office (US)") is not found, so the turn falls back to TMDb; specials are not counted in the seasons; episode titles come in TVmaze's original language.
- **Licence:** TVmaze data is CC BY-SA; the interface shows TVmaze as the source with the link to the series page and to the licence. Whether a model-generated text from this data is an adaptation covered by ShareAlike, and whether a link outside the text of the answer is enough, are **open questions**; check them before any public or commercial use.
- **Step:** `tvmaze_calls`: source and licence, every request, the series with its TVmaze link, what was read, alternatives.

## Wikidata tool (`wikidata_search`)

Reads **declared relations between works** for one film or series and tells works that share a title apart (Wikidata data is CC0, no key).

- **`resolve`** returns the works that fit a title with year, director and IMDb and TMDb ids. **`relations`** identifies the work and returns the works it is based on (a book, a comic, an earlier film), the works based on it (remakes, adaptations, inspired works), the previous and next work in its series and the other works of its franchise. Nothing about cast, plot, awards or scores (awards are incomplete on Wikidata).
- **Routing** (rule 1f): the source of a work, remakes and adaptations, order in a series, franchise membership; `resolve` only to tell homonyms apart or when an earlier step could not identify an ambiguous title, never as a preliminary step. TMDb keeps cast, plot, scores, streaming, filmographies and lists; Wikipedia keeps the prose on how an adaptation differs.
- **Controlled queries:** the SPARQL text is built from constant fragments; only ids that pass a strict pattern are written into it, and the user's title is only the search parameter of the entity search. Every query is bound to given items and limited to 500 rows. The model never writes SPARQL.
- **Identification and filters:** homonyms are found by exact label first (text search ranks by notoriety), a missing date or director never counts as a match, and a title shared by several works returns alternatives (up to 5, oldest first, the rest counted and the list flagged partial). Unreleased works and announced projects are dropped, rows of the same item are merged, groups are ordered and cut at 12 works.
- **Honesty about gaps:** the answer is told that the relations are those recorded, that "based on" does not tell a remake from an inspired work, that previous/next is the order in a series and not "sequel" or "prequel", and that an empty list does not prove there is nothing (one step to Wikipedia follows).
- **Limits:** `CONFIG["wikidata"]["max_calls_per_turn"]` (8): a title costs 1 request to identify (3 if it falls back to the text search; an IMDb or TMDb id 1), the relations 1, the franchise members 1. Timeout 15 s, no retries, a short pause after an HTTP 429, no cache between turns. Wikimedia asks for a descriptive User-Agent. The Query Service terms and rate limits have not been read in full.
- **Step:** `wikidata_calls`: source and licence, every request (SPARQL text included), the work with its Wikidata page, the related works with their pages, alternatives, what could not be read. Live check (3 runs): `python -m tool.wikidata.harness.live_smoke --live`.

## HTTP / SSE server (for a web frontend)

The Netflix-clone frontend (a separate project by Marco Milza) talks to NetflixScout only through this server. All FastAPI code lives in `web_api/`. Start it with `nf-backend`, or:

```bash
source .venv/bin/activate
uvicorn web_api.main:app --reload --host 127.0.0.1 --port 8000
```

Use **one process** (no `--workers`): conversations live in its memory. The API keys stay in the backend `.env`; the frontend sends none. The allowed origins (`WEB_API_CORS_ORIGINS`) default to `http://localhost:8080` and `http://localhost:5173`.

A frontend opens a conversation (`POST /conversations`), sends messages (`POST /conversations/{id}/messages`) and reads a Server-Sent Events stream: `turn_start`, `status`, `story`, `step` (the same data as the terminal, in JSON), `answer_delta` (the text as the model writes it), `answer_end`, `lists` (the structured lists of `web_lists`) and `done`. The turn runs in a thread owned by the server and the history is committed when it finishes, even if the client has gone; a busy conversation answers 409. There is no authentication or rate limit: the backend key and its budget are the only protection (portfolio project). The contracts, payloads, errors and environment variables are in `web_api/contracts/chat_stream.md` (conversations and events) and `web_api/contracts/settings.md` (user settings); the language rules for the frontend are in `docs/frontend_handoff_language.md`.

**`web_lists`** (web channel only): the same call that writes the final answer returns structured references to the films and videos it mentions. A reference is accepted only if its id is in the results of a tool of the turn, its quote is in the answer and names the resource; the details are then filled from the tool data, with no further model or network call.

## User settings prevail over the request

`GET /settings` returns the public definition of six per-turn settings (plot spoilers, response length, tone, approach, content type, preferred sources) from `preferences/fields.json`; the frontend sends the current values in the optional `preferences` field of each message. The backend validates every field on its own (an invalid one falls back to its default, the others are kept, the problem is only logged), and the instructions behind each choice stay private (`preferences/behavior.py`). The terminal has no settings and behaves as if none existed.

Every setting, **defaults included**, wins over an explicit request that contradicts it. The planner declares the conflict (`conflicts`) in the same call that picks the tool; the answer opens with a fixed sentence in the user's language (it/en/de, any other language reads English) that says there is a conflict and which setting prevails, then serves the part of the request that is compatible and never executes the other. `content_type` is also enforced on the tools by a deterministic guard (`preferences/policy.py`): with *series* the film RAG and the `movielens` operation cannot be used and the film operations of TMDb are removed; with *film* TVmaze, the series RAG and the TV operations are removed. For preferred sources a conflict is only an explicit request for a different source. Settings add no tool call, except the `interviews` source, which also searches YouTube for an identified film. Defaults: no spoilers, `medium` length, `technician` tone, alternatives comparison, films and series, official information. Known limit: with binding defaults many legitimate requests ("briefly", "just one") produce a conflict, and detecting it is the planner's judgement.

## Tests and evaluations

```bash
python -m pytest -q -m "not integration and not qdrant_server"   # offline, free, fast
python -m pytest -q                                              # also the tests that need the Qdrant server (they skip if it is down)
```

Offline tests mock OpenAI and every HTTP transport; new tests must not touch the network. With the server up, the tests marked `integration` or `qdrant_server` use the keys and spend credits.

**Live evaluations cost credits or consume quotas and run only with explicit permission:** `python -m movie_db.harness.evaluation.run_routing_eval --live [--tool NAME] [--integrated | --series-index]` (planner routing without running the tools), `run_preference_routing_eval`, `run_rag_semantic_smoke`, `run_series_e2e`, `run_classifier_eval` (all in `movie_db/harness/evaluation/`, with their offline `plan`/`validate`/`report` parts), the pipelines' evaluations under `pipelines/*/eval/`, and the optional live checks of each tool (`tool/*/harness/live_smoke.py`, `web_api/harness/live_stream_check.py`). `python -m movie_db.harness.evaluation.run_rag_infra_check` checks both RAGs on Qdrant with stored vectors, without any model call.

## Git notes

`dbVettoriale/`, `cinema_db/data/`, `movie_db/data/`, `bin/`, `logs/` and `pipelines/*/data/` are local artifacts and are ignored by Git, as is `.env`; only `.env.example` is versioned. Commit messages are short, in English, lowercase.
