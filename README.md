# NetflixScout

This repository integrates the RAG modules into a reproducible local pipeline and a public runtime entrypoint.

## Start the services (two terminals, from the repository root)

NetflixScout needs two processes. Qdrant must be up before the application.

```bash
./scripts/start_qdrant.sh                                       # terminal 1: the Qdrant server (vector store)
source .venv/bin/activate && uvicorn web_api.main:app --host 127.0.0.1 --port 8000   # terminal 2: the backend API for the frontend
```

- `scripts/start_qdrant.sh` runs the official Qdrant 1.20.0 binary on `127.0.0.1:6333` over `dbVettoriale/qdrant_openai/storage`.
  It looks for the binary in `$QDRANT_BIN`, then `bin/qdrant` (not versioned), then the `PATH`; if none is found it says where to put
  it (official release: https://github.com/qdrant/qdrant/releases/tag/v1.20.0). Ready when `curl http://127.0.0.1:6333/collections` lists `netflix_scout`.
- The backend (`web_api/main.py`, one worker only) is ready when `curl http://127.0.0.1:8000/health` answers `{"status":"ok"}`. For the terminal chat use `python app.py`
  instead of the second command. If Qdrant is down both stop with one line: `Error: Cannot reach Qdrant at ...`.

## Project Layout

```text
/
├── dataset/            # local corpus input (not versioned)
├── dbVettoriale/       # local data (not versioned): qdrant_openai/storage is the Qdrant index
├── scripts/            # start_qdrant.sh
├── movie_db/           # MovieLens database side (the tool is in tool/movie_db/)
│   ├── config.py       # validated view of CONFIG["movie_db"]
│   ├── schema.py       # tables, columns, DDL (shared)
│   ├── harness/        # offline only: ingestion/, fixtures/, evaluation/
│   └── data/           # MovieLens CSV + SQLite DB (not versioned)
├── tool/               # orchestrator tools (app.py is the only wiring point)
│   ├── rag/                # RAG tool (rag_search)
│   │   ├── EmbeddingProcess/          # offline: loaders, clean, chunk, embed, index
│   │   └── FromQueryEmbeddingToRes/   # runtime: retrieval, rerank, RagTool, query_classifier/
│   ├── movie_db/           # MovieLens tool (movie_db_search): MovieDbTool, parser, read-only SQL (sql/)
│   ├── tmdb/               # TMDb API tool (tmdb_search)
│   │   ├── config.py       # validated view of CONFIG["tmdb"] (3 settings)
│   │   ├── tool.py         # TmdbTool: validate → run requests → pack context → trace
│   │   ├── http.py         # the only HTTP module: memo → cache → cooldown → budget → send
│   │   ├── models/         # enums, per-operation rules, tool input, normalized results
│   │   ├── operations/     # resolve, reference, movies, tv, people, collections, discovery, lists
│   │   ├── normalize/      # raw JSON → entities with capped facets
│   │   └── harness/        # optional live smoke check (never imported at runtime)
│   ├── wikipedia/          # Wikipedia (MediaWiki API) tool (wikipedia_search), in-process, no MCP, no key
│   │   ├── config.py       # validated view of CONFIG["wikipedia"] (4 settings)
│   │   ├── tool.py         # WikipediaTool: validate → lookup or whole article → sections within the budget → trace + follow_up
│   │   ├── http.py         # the only HTTP module: memo → turn failures → cache → pause → budget → send
│   │   ├── sections.py     # split an article by headings, pick the sections a question needs
│   │   ├── budget.py       # per-turn state: HTTP calls, context handed out, sections already delivered
│   │   └── harness/        # optional live smoke check (never imported at runtime)
│   └── youtube/            # YouTube Data API tool (youtube_search), in-process, no MCP
│       ├── config.py       # validated view of CONFIG["you_tube"] (2 settings)
│       ├── tool.py         # YoutubeTool: validate → search per kind → one /videos → filter → trace
│       ├── http.py         # the only HTTP module: run memo → quota latch → send (/search, /videos)
│       ├── quota.py        # in-memory pause per quota bucket after an observed quota error
│       ├── queries.py      # search queries from constant fragments
│       ├── relevance.py    # deterministic relevance filter and confirmed / to-verify label
│       └── models.py       # VideoKind, YoutubeToolInput, VideoHit, KindOutcome
│   └── omdb/               # OMDb tool (omdb_search): IMDb / Metascore / Rotten Tomatoes scores, in-process, no MCP
│       ├── tool.py         # OmdbTool: validate → identify the work → read the record → scores with a status
│       ├── http.py         # the only HTTP module: turn memo → turn budget → send
│       ├── identify.py     # which work a title search identifies (never by title alone when in doubt)
│       └── ratings.py      # scores: available / not_available (N/A) / unparsed
│   └── tvmaze/             # TVmaze tool (tvmaze_search): structured data of one TV series, in-process, no key, no MCP
│       ├── tool.py         # TvmazeTool: validate → identify the series → read card / seasons / episodes → data + follow_up
│       ├── http.py         # the only HTTP module: turn memo → rate-limit pause → turn budget → send
│       ├── session.py      # per-turn budget and memo, process-wide pause after an HTTP 429
│       ├── identify.py     # which series a title search identifies (never by title alone when in doubt)
│       └── normalize.py    # TVmaze JSON → the small dicts the model and the presenters read
│   └── wikidata/           # Wikidata tool (wikidata_search): identify a work among homonyms, read its declared relations, in-process, no key, no MCP
│       ├── tool.py         # WikidataTool: validate → identify the work → relations / franchise → data + follow_up
│       ├── queries.py      # constant SPARQL fragments; only validated ids are written into a query, never the user's words
│       ├── http.py         # the only HTTP module: turn memo → rate-limit pause → turn budget → send
│       ├── session.py      # per-turn budget and memo, process-wide pause after an HTTP 429
│       ├── identify.py     # which work a title or an external id identifies (never by title alone when in doubt)
│       └── normalize.py    # SPARQL rows → merged, filtered, ordered works (no duplicates, no unreleased)
├── presenters/         # the only output layer: present(turn, channel)
│   ├── channel.py      # OutputChannel (terminal | web)
│   ├── story_view.py   # the turn story: a few plain sentences (what, where, how it went), it/en
│   ├── rag_view.py db_view.py api_view.py youtube_view.py wikipedia_view.py omdb_view.py tvmaze_view.py wikidata_view.py   # channel-neutral views of the tool steps
│   ├── terminal/       # box.py, session.py, blocks.py, renderer.py (TerminalObserver, STEP_RENDERERS)
│   │   └── rag/ db/ api/ youtube/ wikipedia/ omdb/ tvmaze/ wikidata/   # blocks.py + renderer.py per tool
│   └── web/            # observer.py (WebObserver, live events), payload.py (to_payload, STEP_SERIALIZERS)
│       └── rag/ db/ api/ youtube/ wikipedia/ omdb/ tvmaze/ wikidata/   # serializer.py per tool, same shared view as the terminal
├── web_api/            # HTTP/SSE server (FastAPI): conversations, streamed answer, web_lists; see contracts/
├── web_lists/          # web channel only: the lists of films/videos returned with the final answer
├── app.py              # CONFIG, build_app, handle_query (no printing) and the terminal chat
├── orchestrator.py     # LLMOrchestrator: planning, multi-tool loop, final answer
├── turn.py             # channel-neutral TurnResult / TraceStep / TurnObserver
├── answer_stream.py    # decodes the streamed `answer` field out of a chunked JSON
├── data_coverage.py    # years covered by the local sources and the planner rule built from them
├── buildSemanticDb.py  # reproducible semantic DB builder (shim to tool/rag/EmbeddingProcess/)
├── buildMovieDb.py     # MovieLens SQLite builder (shim to movie_db/harness/ingestion/)
├── tests/              # offline tests (+ test_tool_package.py: layout of tool/); test_tool_contract.py is integration
└── mappa.html          # interactive project map (hand-written tree, open it in a browser)
```

`tool/` holds every orchestrator tool; the root `movie_db/` is the MovieLens **database** side (data, schema, ingestion,
evaluations), while the tool that queries it lives in `tool/movie_db/`. A new tool goes in `tool/<name>/`, never in the root.

Note: a legacy `datasets/` folder may exist in older clones, but the new build pipeline reads from `dataset/`.

## Prerequisites

1. Python 3.11+.
2. A virtual environment.
3. API keys in `.env`:

```env
OPENAI_API_KEY=...
COHERE_API_KEY=...
VUE_APP_TMDB_API_KEY=...        # TMDb v3 API key or v4 read access token
VUE_APP_TMDB_BASE_URL=https://api.themoviedb.org/3
YOUTUBE_API_KEY=...             # YouTube Data API v3 key (Google Cloud project)
OMDB_API_KEY=...                # OMDb key (free: 1,000 requests a day; non-commercial use)
```

`YOUTUBE_API_KEY` is read only by `tool/youtube/auth.py`, on the first YouTube search; the base URL is
a constant (`https://www.googleapis.com/youtube/v3`), never read from the environment.
`OMDB_API_KEY` is read only by `tool/omdb/auth.py`, on the first OMDb request; the base URL is a constant
(`https://www.omdbapi.com/`).

The TMDb key is read only by the Python backend (`tool/tmdb/auth.py`). The `VUE_APP_` prefix is
the Vue CLI convention for variables exposed to client bundles: never point a Vue frontend at
this `.env`, or rename the variables (one constant each in `tool/tmdb/auth.py`).

`COHERE_API_KEY` is required when `rerank_backend` is `cohere` (default in `app.py`).

## Install / Setup

From repository root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Download the Dataset

Download the CMU Movie Summary Corpus:

https://www.cs.cmu.edu/~ark/personas/

Place all corpus files inside `dataset/` (not `datasets/`), for example:

```text
dataset/
└── MovieSummaries/
    ├── character.metadata.tsv
    ├── movie.metadata.tsv
    ├── name.clusters.txt
    ├── plot_summaries.txt
    ├── README.txt
    └── tvtropes.clusters.txt
```

## The vector index (Qdrant)

Why a semantic search: recommendations must match meaning, not words. Every plot of the corpus is stored as a 1536-number vector
(`text-embedding-3-small`); a question is turned into a vector the same way and the closest plots are returned (cosine similarity),
optionally fused with keyword search (BM25, `hybrid`) and reranked (Cohere, or an LLM for "like X, not like Y" requests).
Qdrant is the only vector store: it holds the 42,522 points (vector + plot text + metadata) in `dbVettoriale/qdrant_openai/storage`
and finds neighbours with an HNSW index. Settings: `CONFIG["rag"]["vectorstore"]` (collection and server URL); the optional
variables `VECTORSTORE_QDRANT_MODE|URL|PATH` and `QDRANT_API_KEY` only say where the server is.

### Movies cited as references ("like X, not like Y")
A cited movie gets a real vector, not only a description written by the LLM: if the index has it, its stored vector is reused;
if not, its English plot is read from TMDb (identity verified by title and year), embedded once and kept in Qdrant as
`tmdb:movie:<id>` (or linked to the corpus point of the same work); a movie without a usable plot gets no vector and the trace says so.
The vectors steer the Qdrant search (`best_score`) only when at least one liked movie was resolved; otherwise the plain search runs.
The cited movies themselves never come back. Settings: `CONFIG["rag"]["reference"]`, `CONFIG["rag"]["signals"]`; traces in the
`retrieval` step. Measurements and limits: `docs/qdrant_migration/reference_embeddings_report.md`.

### Rebuild the index from the dataset
Creates a NEW collection (nothing is overwritten; it uses paid OpenAI embeddings). With the Qdrant server running:

```bash
python buildSemanticDb.py --collection netflix_scout_new          # then set CONFIG["rag"]["vectorstore"]["collection"]
python buildSemanticDb.py --qdrant-mode embedded --qdrant-path NEW_FOLDER   # alternative: a folder, no server
```

The build scans `dataset/`, cleans and chunks the text, embeds the chunks with `tool.rag.FromQueryEmbeddingToRes.embeddings`
and indexes them. It refuses an existing collection or a non-empty folder before calling the embedding API. See `docs/qdrant_migration/rebuild.md`.

Films cited by the user and missing from the index can also be added from any `tmdb_search` result (`CONFIG["catalog"]["enabled"]`, **off** by default and not calibrated); see `docs/qdrant_migration/catalog/README.md`.

## Verify Build

After build, verify:

1. The Qdrant server is running and `curl http://127.0.0.1:6333/collections` lists the collection.
2. After a rebuild, the build log shows the final chunk count and collection name.
3. Runtime check:

```bash
python app.py
```

If the collection is empty, `app.py` raises an explicit error telling you to run `python buildSemanticDb.py`.

When the collection is available, `app.py` starts an interactive terminal chat.

Conversation flow:

1. Type a query in terminal.
2. The domain classifier blocks off-topic and jailbreak requests; otherwise the orchestrator (`orchestrator.py`) rewrites the query as standalone, picks a tool (`rag_search`, `movie_db_search`, `tmdb_search`, `youtube_search`, `wikipedia_search`, `omdb_search`, `tvmaze_search`, `wikidata_search`) and may chain more tools in the same turn.
3. Each step is narrated while it happens, then the final answer is streamed (one LLM call, written only from the tool results).
4. Conversation history is updated and reused in the next turns.
5. Type `exit` or `quit` to close.

Automatic compaction:

1. After each completed answer, the history length is checked.
2. If it reaches `CONFIG["orchestrator"]["memory_window_size"]` messages (12), history is compacted and replaced (not appended).
3. A short user-friendly notice is printed in terminal.

## Retrieval Notes

1. An LLM parser turns the user query into English `QuerySignals`: `semantic_query`, `genres`, `excluded_genres`, and positive/negative signals plus hard exclusions. `rag_search` runs on the standalone query; the planner's `arguments.query` is only a hint for the parser.
2. The embedding is computed on `semantic_query` (falling back to the original query), never on a bag of keywords: the corpus is English plot summaries.
3. Chunks whose metadata `genres` match the requested genres get `retrieval.genre_boost` on a pool of `retrieval.fetch_k` candidates, before cutting to `k_largo`.
4. The reranker sees `Title (year)` and `Genres` before the plot, and is queried with `semantic_query` (falling back to the query) plus a "Must match:" list of the requested genres and positive signals (decade, country, setting) the sentence left out.
5. `excluded_genres` ("without science fiction") drop chunks by their `genres` metadata; `hard_exclusions` only filter titles. `pipeline.run_rag` gives each constraint a status per film (full report in the `rerank` trace step; the prompt gets one readable line per film and constraint in `metadata.constraints_summary`): `verified` (genres/year metadata), `probable` (key terms in the plot), `not_verifiable` (endings, tone, missing terms) or `contradicted`; plot constraints such as "no tragic ending" are never presented as verified.
6. The terminal shows the text used for the embedding and the requested genres above the K LARGO list.

## Public Runtime API

`app.py` is the integration layer. It exposes:

1. `CONFIG` and `build_runtime_config(overrides)` (deep merge of the overrides).
2. `build_app(overrides)`: builds the tools and the `LLMOrchestrator`.
3. `handle_query(...)`: runs one turn without printing and returns a `TurnResult`; the channel (`presenters/`) decides how to show it.

`run_rag` lives in `tool/rag/FromQueryEmbeddingToRes/pipeline.py` and returns only evidence (retrieve + rerank, no generation); the final answer is always written by the orchestrator.

`search_mode` is strictly validated to:

1. `semantic`
2. `hybrid`
3. `bm25`

The chosen mode is propagated to the runtime retrieval components (`rag` / `hybrid`) and does not rely on fake APIs.

In the chat, the orchestrator's planner sets two retrieval settings per turn: `k_finale`, the number of films the user asked for (clamped to `rag.retrieval.limits.k_finale`; null keeps the configured default), and `search_mode`, `hybrid` only when the request hinges on concrete words that must appear in the plot (a character name, a place, a rare term); `bm25` alone is not offered to the planner. In hybrid mode the keyword side searches with the English `semantic_query`. The other retrieval settings stay fixed in `CONFIG`.

## RAG Tool (`rag_search`)

`RagTool` (`tool/rag/FromQueryEmbeddingToRes/tool_interface.py`) follows the `Tool` Protocol of `orchestrator.py`; its input schema is generated from the Pydantic model `RagToolInput.model_json_schema()` (query and `k_finale`). `build_app` registers it together with the other tools and `CONFIG["orchestrator"]["allowed_tools"]` lists the names the planner may choose, so new tools are added without refactoring the runtime core.

## MovieLens DB Tool (`movie_db_search`)

A second orchestrator tool answers quantitative questions (rankings, average ratings, number of
ratings, movies by genre and year, user tags) from MovieLens 32M in a local SQLite database.
All parameters live in `CONFIG["movie_db"]` in `app.py` and go through `build_runtime_config(overrides)`;
`movie_db/config.py` validates them (`MovieDbConfig.model_json_schema()` is ready for a future web form).

### Setup after cloning

The CSV files (~950 MB) and the generated database (~1.3 GB) are not in the repository:
`movie_db/data/` is ignored by Git except for its `.gitkeep`. Every clone downloads and builds them once.

1. Download **MovieLens 32M** (`ml-32m.zip`, ~240 MB) from the GroupLens page
   https://grouplens.org/datasets/movielens/32m/ (direct link: https://files.grouplens.org/datasets/movielens/ml-32m.zip).
2. Unzip it into `movie_db/data/raw/`. The zip already contains the `ml-32m/` folder:

   ```bash
   mkdir -p movie_db/data/raw
   unzip ml-32m.zip -d movie_db/data/raw
   ```

   Expected layout (only the four CSV files are read):

   ```text
   movie_db/data/
   ├── .gitkeep
   ├── raw/ml-32m/{movies,ratings,tags,links}.csv  (+ README.txt, checksums.txt)
   └── movielens32m.sqlite3                        # created by the next step
   ```

3. Optional: check the files with `cd movie_db/data/raw/ml-32m && md5sum -c checksums.txt`
   (macOS: compare `md5 -r *.csv` with `checksums.txt`).
4. Build the SQLite database from the repo root (a few minutes; an existing DB is replaced only with `--force`):

   ```bash
   python buildMovieDb.py            # options: --source-dir DIR --db-path FILE --force
   ```

   The build makes no API calls, but it currently needs `OPENAI_API_KEY` set in `.env`: it reads
   `CONFIG` from `app.py`, whose imports create the OpenAI client. The same holds for the offline
   `run_eval` below.

Paths come from `CONFIG["movie_db"]["source_dir"]` and `["db_path"]`. With the tool enabled,
`python app.py` refuses to start until the database exists; set `CONFIG["movie_db"]["enabled"] = False`
to run the chat with the RAG tool only.

Read-only by construction, never by prompt:

1. The LLM parser only fills a `MovieDbQuery` (closed `MovieDbOperation` enum + typed fields, extra keys rejected); it never writes SQL.
2. SQL is built in `tool/movie_db/sql/queries.py` from constant fragments; values are bind parameters only.
3. The connection is `mode=ro` + `PRAGMA query_only`, with an SQLite authorizer that allows only SELECT on the known tables and whitelisted functions; `max_limit` and `timeout_ms` bound every call.

Each run adds one `db_query` trace step with only the SQL executed (`{sql, params}`), no rows:
the terminal prints it in `presenters/terminal/db/`, `presenters/web/db/` serializes it for the future API
(both read it through `presenters/db_view.py`).

### Evaluation

| Command | What it checks | API calls |
|---|---|---|
| `python -m movie_db.harness.evaluation.run_eval` | 6 cases: SQL, guard and results on the bundled mini dataset, scripted parser | none |
| `python -m movie_db.harness.evaluation.run_eval --live-parser` | same 6 cases with the real LLM parser | 6 × `gpt-5.6-luna` |
| `python -m movie_db.harness.evaluation.run_routing_eval --live` | 30 questions (6 DB, 5 RAG, 11 TMDb, 7 YouTube, 1 clarification; 5 are follow-ups): domain classifier + orchestrator planning only, no tool runs | 30 × `gpt-4o-mini` + 30 × `gpt-5.6-luna` |
| `python -m movie_db.harness.evaluation.run_routing_eval --live --tool tmdb_search` | only the 11 TMDb questions; the planned `requests` are also validated offline (operation, title, facets), the tool never runs | 11 × `gpt-4o-mini` + 11 × `gpt-5.6-luna` |
| `python -m movie_db.harness.evaluation.run_routing_eval --live --tool wikipedia_search` | only the 4 Wikipedia questions; the planned arguments are validated offline as `WikipediaToolInput` (topic, kind, depth, nothing invented); never run yet | 4 classifier + 4 planner |
| `python -m movie_db.harness.evaluation.run_routing_eval --live --tool youtube_search` | only the 7 YouTube questions; the planned arguments are also validated offline as `YoutubeToolInput` (title, kinds, and no year, director, cast or alternative title the conversation does not give), the tool never runs | 7 × `gpt-4o-mini` + 7 × `gpt-5.6-luna` |

The parser evaluation accepts `by_genre_year` in place of `top_rated` (and vice versa) only for a genre
without a year range, and only if the executed SQL and parameters are identical to the expected ones.
The routing evaluation records the planner's raw output, so a silent fallback to `rag_search`
(invalid JSON, unknown tool, low confidence) counts as a failure even when the tool is right.
Both live runs disable automatic retries. Cases live in `movie_db/harness/evaluation/cases.py` and
`routing_cases.py`.

MovieLens is licensed for non-commercial use without redistribution: never commit or serve `movie_db/data/`.

## TMDb Tool (`tmdb_search`)

A third orchestrator tool queries The Movie Database API for up-to-date facts: cast and crew,
release dates, streaming providers, trailers, images, reviews, recommendations, TV series with
seasons and episodes, people and filmographies, collections, companies, discover by filters (released titles only, unless the user explicitly asks for upcoming ones),
trending and charts, genres and certifications (17 typed operations, see
`tool/tmdb/models/operation_rules.py`). Account, session, write, list, `changes` and deprecated
endpoints are deliberately not exposed.

The planner fills `arguments.requests` (1 to 4 operations) from the tool schema shown in the
planning prompt; the model never builds URLs. Python validates every request before any call,
resolves titles and names to IDs (TMDb ID → IMDb/TVDB/Wikidata via `/find` → search), maps each
operation to a fixed endpoint and uses `append_to_response` (max 20) for facets.

Routing priority: any request for information on a film or series identified by its title goes to
`tmdb_search` ("tell me about Arrival", "who directed…", streaming, cast); ratings and rankings go
to `movie_db_search`; recommendations and plot/theme/mood searches go to `rag_search`, also when a
title is only a reference ("films like X"). When a specific film is meant but neither the question
nor the history identifies it ("who was in that Sorrentino film…"), the planner asks a clarifying
question instead: no tool and no TMDb call run in that turn.

After `rag_search`, `tool/tmdb/enrich.py` completes the movies the RAG selected (the final reranked
chunks, at most `CONFIG["orchestrator"]["rag_enrichment"]["max_candidates"]`, in RAG order) with
TMDb title, year, director, cast and overview. Metadata is attached only when the title equals the
TMDb title or original title (never by containment: "The Sinner" is not "The Sinners") and a known
year is confirmed within ±1, with a single such match; otherwise the candidate is marked
`unverified`/`not_found`/`skipped` and nothing is attributed. `tmdb_search` applies the same rule
to movies and series: without an exact title it accepts a result only if TMDb lists the
requested title among the translated or alternative titles of that same work (year ±1; e.g.
"Survival Island" → "Three", 2005), otherwise it returns `unverified_match` with the closest
results as unverified `candidates` instead of the most popular result. MovieLens rankings drop the
series TMDb recognizes (`/find` by IMDb id); titles it cannot settle stay, marked `work_type: unverified` with
`work_type_verified: false`, because the catalog has no reliable type. The RAG ranking is never changed, and the turn still makes at most one TMDb run.

`CONFIG["tmdb"]` has exactly three settings:

| Setting | Default | Meaning |
|---|---|---|
| `max_results` | 5 | items returned by searches, discover, trending, charts and related-title lists |
| `max_calls_per_turn` | 6 | HTTP attempts per turn: the only call limit, enforced in `tool/tmdb/budget.py` |
| `cache_ttl` | 3600 | seconds a response is reused across turns (0 = per-turn memo only) |

Cache and memo hits cost nothing; every attempt sent counts, also when it fails; a 429 pauses
calls for `Retry-After` without retries; failures become partial results, never a broken turn.
The data passed to the LLM is bounded (`tool/tmdb/prompt_budget.py`): identity and essentials are
always kept, long lists are capped and omissions are listed in `metadata.tmdb.omitted`. TMDb
data is requested in the turn language (`it-IT` for Italian questions, `en-US` otherwise) with
appended translations as fallback; the answer language is up to the LLM.

Each run adds one `tmdb_calls` step with every request actually sent, method and full URL, only the key masked
(`Chiamato: GET https://api.themoviedb.org/3/movie/157336?language=it-IT&api_key=***`; no credential at all with a
Bearer token), labels in Italian or English after the question, printed by `presenters/terminal/api/`.
`presenters/web/api/` serializes the same step for the future API (`presenters/web/payload.to_payload` builds the JSON-ready form of a turn, no route yet).

Optional live check of undocumented behaviours (3 real calls): `python -m tool.tmdb.harness.live_smoke --live`.

### Credits

TMDB logo: add one of the approved logos from https://www.themoviedb.org/about/logos-attribution
here (less prominent than the NetflixScout name, as the TMDb terms require). The terminal cannot
show images, so the logo lives in this README and, later, in the web frontend's About section.

Streaming availability data is provided by JustWatch: the terminal shows the credit in every
turn whose answer may use it.

## YouTube Tool (`youtube_search`)

A fourth orchestrator tool searches YouTube for videos about one identified film: interviews with
the director (`director_interview`) or the cast (`cast_interview`), making-of, behind the scenes and
featurettes, the authors' commentary. Trailers stay with `tmdb_search` (official links tied to the
TMDb ID) unless the user explicitly asks for YouTube or accepts the offer after TMDb found none. It
is an in-process tool that follows the internal `Tool` Protocol of `orchestrator.py`: there is no MCP
server or client, and no new dependency.

The planner fills `title` and `kinds` (1–3, most important first) and, only with values written in
the request or the conversation, `year`, `director`, `cast` (up to 5 names) and `alternative_titles`
(up to 3). Python validates the input before any call and builds each search from constant
fragments (title phrases in OR, kind words in OR, `-reaction -parody`); for a one-word title with a
known person the person is required. No `regionCode` or `relevanceLanguage` is sent.

`CONFIG["you_tube"]` has exactly two settings:

| Setting | Default | Meaning |
|---|---|---|
| `max_results` | 3 | videos returned per searched kind |
| `max_searches_per_turn` | 2 | `search.list` calls per turn (one per kind); later kinds are reported as not searched |

Quota: `search.list` has its own bucket of **100 calls a day** per Google Cloud project (1 unit each),
shared with every other client of the same project; `videos.list` uses the 10,000-unit bucket. With
the defaults a turn spends at most 2 searches and 1 `/videos` call, so roughly 50 YouTube turns a day
at most, fewer if anything else uses the project (a dedicated project is advisable). There is no
local counter: after an observed `quotaExceeded` the tool pauses that bucket until midnight Pacific
Time, in memory only. There is no cache across turns.

Relevance: the snippet title can only drop reactions, parodies, fan-made videos, concept trailers
and conflicting years; everything else is judged on the full `/videos` data. A video is dropped only on strong
evidence (film and people not named, another declared format such as a review or a full movie,
unconfirmed homonym, self-declared Short, no longer available), otherwise it is kept in API order
and labelled `confirmed` or `to_verify`. The kind is confirmed only by a word of the kind in the
video title (descriptions list credits such as "director" or "cast"), or, for an interview, when a
named person speaks in the title ("Celine Song talks …") and the description gives that same
person the requested role next to the name ("writer-director Celine Song"). A one-word title with no
year or person to check is kept, as to verify, only with film context: a film word in the title
or description (film, movie, película, IMDb, "directed by"...), the film title in quotes, or the
Latin film title inside a title in another script. Kind words and roles ("trailer", "making of",
"director", "cast") never count: "Parasite" or "Her" alone also match unrelated videos. The answer lists confirmed videos first and the others
under "Da verificare", and may suggest giving the film's year or its original title (never
proposing one).

Each run adds one `youtube_calls` step: every request sent, method and full URL (`GET https://www.googleapis.com/youtube/v3/search?part=snippet&q=...&key=***`),
the query of each kind with the drops per reason, kinds not searched and why, the videos with
titles and channels exactly as returned, and the dropped titles with their reason (`dropped`: not
printed, kept for tests and evaluations to spot false negatives). The terminal prints it in `presenters/terminal/youtube/`
(control characters removed from the printed copy only); `presenters/web/youtube/` serializes the same
shared view (`presenters/youtube_view.py`) for the web.

Verification status: the offline tests (`tests/test_youtube_*.py`) cover the tool without network.
A live E2E run of 20 questions (2026-10-23, before the relevance fixes) routed 20/20 to
`youtube_search` with 6 OK, 10 partial and 4 failed answers. Still pending: a live run after the
fixes, a live run of the YouTube routing cases (prepared offline, not run yet), a live smoke check (none exists yet), and live
confirmation of the query operator precedence and of the API error reasons.

## OMDb Tool (`omdb_search`)

A sixth orchestrator tool reads the scores OMDb holds for one identified film or series: the IMDb
rating (voted by the audience), the Metascore and the Rotten Tomatoes score (aggregates of
professional critics' reviews). Scores only: no review text, no plot. It runs in-process (standard
library `urllib`, no new dependency, no MCP) and is chosen only when the request asks for the critics'
judgement or names one of those scores (routing rule 1d); with the **Preferred sources: reviews**
setting a critics question goes to OMDb before TMDb. It is never called on every turn.

- **Identification**: by IMDb ID when the request, the conversation or an earlier step of the turn gives one;
  otherwise the title is searched and a work is accepted only if exactly one has that title (and year, if
  given). Several matches or only similar titles return the alternatives and **no score**.
- **Missing data**: every source is always listed as `available`, `not_available` (OMDb says `N/A` or has no
  value) or `unparsed`; nothing is estimated, averaged or taken from another source.
- **Limits**: `CONFIG["omdb"]["max_calls_per_turn"]` (10: an ID costs 1 request, a title 2; ten cover the five candidates verified for a "recommend films with excellent reviews" request); the free key allows
  1,000 requests a day. No cache between turns and nothing on disk: each turn asks OMDb again, a turn only
  avoids repeating the same request within itself. No retries.
- **Key**: `OMDB_API_KEY` in `.env`, read only by `tool/omdb/auth.py`; it never appears in code, logs, tests,
  trace or the frontend (every call is shown with method and full URL, e.g. `GET https://www.omdbapi.com/?i=tt0111161&r=json&apikey=***`).
- **Terms**: OMDb content is CC BY-NC 4.0 and its terms allow personal, non-commercial use only (no indexes or
  redistribution). Commercial use would need the maintainer's written permission. Not affiliated with IMDb.
- **Text**: the answer never names a source or provider (the interface shows it); a score's own name (Metascore, Rotten Tomatoes, IMDb rating) is
  used only as the name of that score. Each score is written as its `display` (`9.3/10`, `82/100`, `93%`), audience and critics scores are shown
  separately with their scale and no winner is declared between them.
- **Step**: `omdb_calls` (shared view `presenters/omdb_view.py`): source, every request sent (method and full URL, key masked), status, scores with what
  they measure, alternatives.
- **Checks**: `tests/test_omdb_*.py tests/test_http_call_trace.py tests/test_answer_provenance_rules.py` run offline. `python -m tool.omdb.harness.live_smoke --live` sends 6 real
  requests and prints only the shape of the answers (run on 2026-10-28). The live routing eval does not
  include OMDb cases yet.

## TVmaze Tool (`tvmaze_search`)

A seventh orchestrator tool reads the structured data TVmaze holds for one identified **TV series**:
status (running or ended), network or web channel, premiere and end dates, runtime, language, genres, a
short summary, the cast with character names, the seasons, the episodes of one season with numbering and
air dates, and the upcoming episode. No key, standard library `urllib`, no new dependency, no MCP.

- **Routing** (rule 1e, the only place that says it; rule 1 only points to it): TVmaze for seasons, episodes,
  numbering, air dates, next episode, cast and the plain facts of a series (running or ended, network, dates,
  genres). TMDb keeps general descriptions in Italian, creators, streaming, trailers, reviews, recommendations
  and lists; Wikipedia keeps history and production; films are never routed here. A source named by the
  user wins. The **Content type: series** setting treats an ambiguous title as the series and excludes the RAG
  and MovieLens for finding series, but does not force TVmaze: the intent of the question decides.
- **Missing data and fallback**: a series TVmaze does not know (it holds mostly original or English titles),
  a rate limit, a timeout or a network error make the tool offer ONE next step to `tmdb_search`; the planner
  never asks TVmaze twice. A section that fails (say the seasons) does not lose the rest. When both sources are
  in a turn and disagree on seasons, episodes, dates or cast the answer reports TVmaze and says they differ.
- **Limits**: `CONFIG["tvmaze"]["max_calls_per_turn"]` (6): identifying a series costs 1 request, the card with
  cast or next episode, the seasons and the episodes one each. TVmaze documents at least 20 calls every 10
  seconds per IP address. After an HTTP 429 nothing is sent for a few seconds (`Retry-After` if present, 1-60 s,
  otherwise 5 s) and there are no retries. Nothing is kept between turns or on disk (no cache): a turn
  only avoids repeating the same request within itself. Episode summaries are never read (spoilers).
- **Text**: the answer never names a source (the interface shows it) and does not invent episodes, dates or characters.
- **Step**: `tvmaze_calls` (shared view `presenters/tvmaze_view.py`): source and licence, every request sent
  (method and full URL), the series with the link to its TVmaze page, what was read, alternatives.
- **Licence and attribution**: TVmaze states that its data is licensed CC BY-SA and that the attribution
  can be satisfied by linking back to TVmaze. The interface shows TVmaze as the source with the link to the series page
  and to the CC BY-SA 4.0 licence. **Still open, not settled by this project**: whether a text generated by the model from this data is an
  adaptation covered by ShareAlike; whether the link in the interface, outside the text of the answer, is enough
  (the answer text never names sources); the effect of sending the data to an external model; the licence
  of images (not used) and of summaries; the exact wording of the TVmaze terms of use, which were not read in full. To be checked
  with the owner before any public or commercial use.
- **Checks**: `tests/test_tvmaze_*.py tests/test_http_call_trace.py` run offline. On 2026-10-29, with the owner's
  authorization, a live smoke test of the tool (5 requests) and 16 real questions through the whole flow were run: the 12
  questions on seasons, episodes, dates, cast, network and next episode went to TVmaze, the 4 boundary ones (plot, streaming,
  similar series, trailer) to TMDb; 13 answers were correct, 2 partial, 1 wrong. TVmaze was not compared with TMDb on
  the same questions, so its advantage over TMDb is not proven. `run_routing_eval --live` and an end-to-end run in the
  browser have **not** been run: they need an explicit authorization.
- **Known limits (observed live, not fixed)**: two series with the same title (“Friends”) give a question back to the user
  instead of an answer; a title with a qualifier (“The Office (US)”) is not found on TVmaze, so the turn falls back to TMDb
  with one more planning step; specials are not counted in the seasons (“Sherlock” shows 12 episodes, 13 with the special);
  episode titles come in TVmaze's original language (“Dark” in German) and the answer does not say so.

## Wikidata Tool (`wikidata_search`)

An eighth orchestrator tool reads **declared relations between works** from Wikidata, for one film or series,
and tells works that share a title apart:

- **What it gives**: `operation: resolve` returns the works that fit a title with year, director and IMDb and
  TMDb ids; `operation: relations` identifies the work and returns the works it is based on (a book, a comic, an
  earlier film), the works based on it (remakes, adaptations, inspired works), the previous and next work in its
  series and the other works of its franchise. Nothing about cast, plot, awards or scores: awards are
  incomplete on Wikidata (a film can have one Oscar nomination there and ten on Wikipedia), so they are not read.
- **Routing** (rule 1f, the only place that says it): Wikidata for the source of a work, remakes and adaptations,
  order in a series, franchise membership; `resolve` only when the request asks to tell homonyms apart or an
  earlier step could not identify an ambiguous title, never as a preliminary step of every search. TMDb keeps
  cast, plot, scores, streaming, filmographies and lists; Wikipedia (rule 1c) keeps the prose on how an adaptation
  differs. One fallback step to TMDb or Wikipedia when the work is not found, never a second try.
- **Controlled queries**: the SPARQL text is built from constant fragments; only ids that pass a strict pattern are
  written into it, the user's title is just the search parameter of the entity search. Every query is bound to
  given items and limited to 500 rows. The model never writes SPARQL.
- **Filters**: unreleased works and announced projects are dropped (and counted), rows of the same item are merged,
  items without a label or of another kind (albums, characters, tracks) are ignored, groups are ordered and cut at
  12 works. A missing date or director never counts as a match; a title shared by several works is returned as a
  list of alternatives, with no data attributed.
- **Honesty about gaps**: the answer is told that the relations are those recorded, that "based on" does not tell a
  remake from an inspired work, that previous/next is the order in a series and not "sequel" or "prequel", and
  that an empty list does not prove there is nothing. A work with no recorded relation leads to one step to
  Wikipedia.
- **Limits**: `CONFIG["wikidata"]["max_calls_per_turn"]` (8): a title costs 1 request to identify (all films and series with
  that exact label; 3 if it falls back to the text search; an IMDb or TMDb id 1), the relations 1, the franchise members 1. Timeout 15 s, no retries, a short pause after an HTTP 429,
  no cache between turns, no key. Wikimedia asks for a descriptive User-Agent.
- **Step**: `wikidata_calls` (shared view `presenters/wikidata_view.py`): source and licence, every request sent
  (method and full URL, SPARQL text included), the work with its Wikidata page, the related works with their pages,
  alternatives, what could not be read.
- **Licence**: Wikidata data is CC0 (official licensing page): no attribution is required, the interface names the
  source with a link anyway. The Query Service terms and rate limits were not read in full.
- **Checks**: `tests/test_wikidata_*.py tests/test_http_call_trace.py` run offline with a fake transport. The
  queries ran live on 2026-10-29 (`live_smoke`, 8 requests): they are accepted and the film, series and literary
  work classes work; the ids of the classes film project, video game and comic were not seen at work. Homonyms are
  found by exact label (the text search ranks by notoriety and hid a 1996 film behind a 2004 one) and a single fit in a
  cut list is never presented as certain. Alternatives are listed up to 5 (oldest first); the others are counted
  ("+N more not shown") and a list cut at its search limit is flagged partial, so a complete list is told apart from a partial one. The routing with a real LLM was not evaluated:
  `python -m movie_db.harness.evaluation.run_routing_eval --live --tool wikidata_search` (LLM credits) needs permission.

## Wikipedia Tool (`wikipedia_search`)

A fifth orchestrator tool reads Wikipedia (MediaWiki Action API, no key needed) for encyclopedic
information that TMDb does not have: in-depth biographies and careers, the history and production
of a film, cinema movements. Cast, crew, release dates, plots, streaming, ratings and short
biographies stay with TMDb; videos with YouTube.

The search starts in the **English** edition whatever the language of the question (it is the richest for
film topics; `default_language` in `CONFIG["wikipedia"]`), and the answer is still written in the user's
language. The Italian edition is never tried automatically: when English finds no page, the page is unsure, or a
keyword of the question is in no section of the English article, the tool says so and the planner decides on a
further step with `language: it` (same cache, same per-turn call and text budgets, no page downloaded twice).
The planner translates the distinctive words of the question into English (`keywords`) so the right sections
are picked from an English article.

The planner names the page with its title in the edition searched (the English title when it is known, never an
invented one), reads both the film and the source work for a comparison, and the answer must not present original
titles, title translations or identifications of real people as facts unless the page text says so (otherwise it
says the page does not report them, or flags the line "Non verificato:").

Pages are checked before they are used: a page whose title is not the one asked and whose lead does not
support it (for a film with a year, the year) is dropped, an article is downloaded only for a page whose title
is the one asked, and uncertain candidates are only listed. Keywords that name nothing specific (episodes,
actors, cast...) are ignored when deciding whether English lacks a detail. The routing rules send what TMDb does
not have to Wikipedia: which director or actor made which segment of an anthology, episode structure, a film
compared with its source novel, detailed plots; simple structured questions stay with TMDb.

How much text is read depends on the question and on what the first reading showed:
- `depth: intro` reads the lead of the best pages (one request); `sections` and `full` open ONE
  page, whose whole article is downloaded once and kept in the cache (`cache_ttl`), then split by
  headings; the sections that answer the question are handed out first.
- `context_chars_per_turn` (default 40,000) caps the text that enters the final prompt in one turn,
  not what can be fetched: whatever does not fit is listed (title and size) and can be asked for.
- After each step the tool describes what it gave and what it left out; if more could help, the
  orchestrator asks the planner whether to read another step (more sections of the page, another
  page, a new search) or to answer (`follow_up`, see `orchestrator.py`). A turn that reads only the
  lead therefore costs one more planning call.
- Rate limits and replication lag (`maxlag`, answered with HTTP 200) never make the turn wait: the
  step fails at once, the next requests are paused for a few seconds, nothing is retried.

Each step adds a `wikipedia_calls` step: every request sent (method and full URL), the pages read (title, language, public URL,
sections read, sections left out), and the credit the licence requires. Wikipedia text is CC BY-SA
4.0: the terminal and the web name the source, link every page and the licence, and say the text
was reworded and shortened. The text of an article is third-party data and is never treated as
instructions. The web frontend must render the new step (`web_api/contracts/chat_stream.md`).

Requests carry the User-Agent `NetflixScout/1.0 (https://github.com/182Marco/NetflixScout;
marcomilza@gmail.com) python-urllib`, as the Wikimedia policy asks. Offline tests:
`tests/test_wikipedia_*.py` and `tests/test_orchestrator_follow_up.py`. Not run yet:
`python -m tool.wikipedia.harness.live_smoke --live` (3 requests) and the Wikipedia routing cases
(`run_routing_eval --live --tool wikipedia_search`).

### Credits and policies

This application uses YouTube API Services: the terminal names YouTube as the source of every
video result.
The YouTube API Services Developer Policies (III.A.2) also require the application's own privacy
policy: not written yet for this personal project.

## Git Notes

`dataset/`, `dbVettoriale/` and `movie_db/data/` are local artifacts and are ignored by Git.

## HTTP / SSE server (for a web frontend)

The Netflix-clone frontend (a separate project by Marco Milza) talks to NetflixScout only through this
server: it works end to end, and it needs this command running. Start it from the repository root and
keep it running while the frontend is in use:

```bash
source .venv/bin/activate
uvicorn web_api.main:app --reload --host 127.0.0.1 --port 8000
```

Use ONE process (no `--workers`): conversations live in its memory. The frontend then reaches the API at
`http://127.0.0.1:8000`; the origins allowed by CORS (`WEB_API_CORS_ORIGINS`) default to
`http://localhost:8080` and `http://localhost:5173`, so serve the frontend from one of them or set the
variable in `.env`. The API keys stay in the backend `.env`; the frontend sends none.

All FastAPI code lives in `web_api/`. A frontend opens a conversation (`POST /conversations`), sends
messages (`POST /conversations/{id}/messages`) and reads a Server-Sent Events stream: live progress
(`story`, `step`), the answer text as the model writes it (`answer_delta`), then `answer_end`, the
`web_lists` structured lists (`lists`) and `done`. The terminal gets the same progressive text. The
contract, payloads, errors, CORS and environment variables are in `web_api/contracts/chat_stream.md`. There is
no authentication: the backend key and its budget are the only protection (portfolio project).

**User settings.** `GET /settings` returns the public definition of six per-turn settings (plot spoilers,
response length, tone, approach, content type, preferred sources) from `preferences/fields.json`; the
frontend sends the current values in the optional `preferences` field of each message. The backend validates
every field on its own (an invalid one falls back to its default, the others are kept, the problem is only
logged), the settings add no tool call except the `interviews` source, which also searches YouTube for an
identified film or series (defaults: no spoilers, `medium` length, `technician` tone,
alternatives comparison, films and series, official information; checked with 10 real turns on 2026-10-27),
and the instructions behind each choice stay private
(`preferences/behavior.py`). The terminal always behaves as before. Contract for the frontend:
`web_api/contracts/settings.md`.
