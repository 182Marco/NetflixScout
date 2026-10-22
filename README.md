# NetflixScout

This repository integrates the RAG modules into a reproducible local pipeline and a public runtime entrypoint.

## Project Layout

```text
/
├── rag/
│   ├── EmbeddingProcess/
│   └── FromQueryEmbeddingToRes/
├── dataset/            # local corpus input (not versioned)
├── dbVettoriale/       # local vector DB persistence (not versioned)
│   ├── openai/
│   └── local/
├── movie_db/           # MovieLens SQL tool
│   ├── config.py       # validated view of CONFIG["movie_db"]
│   ├── schema.py       # tables, columns, DDL (shared)
│   ├── tool/           # runtime: MovieDbTool, parser, read-only SQL (tool/sql/)
│   ├── harness/        # offline only: ingestion/, fixtures/, evaluation/
│   └── data/           # MovieLens CSV + SQLite DB (not versioned)
├── tmdb/               # TMDb API tool (tmdb_search)
│   ├── config.py       # validated view of CONFIG["tmdb"] (3 settings)
│   ├── tool.py         # TmdbTool: validate → run requests → pack context → trace
│   ├── http.py         # the only HTTP module: memo → cache → cooldown → budget → send
│   ├── models/         # enums, per-operation rules, tool input, normalized results
│   ├── operations/     # resolve, reference, movies, tv, people, collections, discovery, lists
│   ├── normalize/      # raw JSON → entities with capped facets
│   ├── presenters/     # terminal/ and web/ output of the tmdb_calls step
│   └── harness/        # optional live smoke check (never imported at runtime)
├── app.py              # public API + RAG Tool facade
├── buildSemanticDb.py  # reproducible semantic DB builder
├── buildMovieDb.py     # MovieLens SQLite builder
└── ...
```

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
```

The TMDb key is read only by the Python backend (`tmdb/auth.py`). The `VUE_APP_` prefix is
the Vue CLI convention for variables exposed to client bundles: never point a Vue frontend at
this `.env`, or rename the variables (one constant each in `tmdb/auth.py`).

`COHERE_API_KEY` is required when `rerank_backend` is `cohere` (default in `app.py`).

## Install / Setup

From repository root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install openai python-dotenv pydantic chromadb numpy rank-bm25 cohere beautifulsoup4 markdown-it-py pypdf python-docx sentence-transformers
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

## Build dbVettoriale/

Single command (full rebuild from zero, OpenAI backend):

```bash
python buildSemanticDb.py --embedding-backend openai
```

For the local backend:

```bash
python buildSemanticDb.py --embedding-backend local
```

What the build does:

1. Deletes and recreates `dbVettoriale/<backend>/`.
2. Scans all files under `dataset/` in deterministic sorted order.
3. Cleans text with `rag.EmbeddingProcess.clean` pipelines.
4. Chunks text with `rag.EmbeddingProcess.chunk` semantic chunking (`chunk_semantic`).
5. Embeds chunks with `rag.FromQueryEmbeddingToRes.embeddings`.
6. Indexes into Chroma via `rag.FromQueryEmbeddingToRes.vectorstore` APIs.

## Verify Build

After build, verify:

1. `dbVettoriale/openai/` or `dbVettoriale/local/` exists.
2. The build log shows final chunk count and collection name.
3. Runtime check:

```bash
python app.py
```

If the collection is empty, `app.py` raises an explicit error telling you to run `python buildSemanticDb.py --embedding-backend <backend>`.

When the collection is available, `app.py` starts an interactive terminal chat.

Conversation flow:

1. Type a query in terminal.
2. The app runs retrieval + reranking + generation.
3. The answer is printed.
4. Conversation history is updated and reused in the next turns.
5. Type `exit` or `quit` to close.

Automatic compaction:

1. After each completed answer, input context tokens are checked.
2. If they are `>= 60000`, history is compacted and replaced (not appended).
3. A short user-friendly notice is printed in terminal.

## Retrieval Notes

1. An LLM parser turns the user query into English `QuerySignals`: `semantic_query`, `genres`, `excluded_genres`, and positive/negative signals plus hard exclusions. `rag_search` runs on the standalone query; the planner's `arguments.query` is only a hint for the parser.
2. The embedding is computed on `semantic_query` (falling back to the original query), never on a bag of keywords: the corpus is English plot summaries.
3. Chunks whose metadata `genres` match the requested genres get `retrieval.genre_boost` on a pool of `retrieval.fetch_k` candidates, before cutting to `k_largo`.
4. The reranker sees `Title (year)` and `Genres` before the plot, and is queried with `semantic_query` (falling back to the query) plus a "Must match:" list of the requested genres and positive signals (decade, country, setting) the sentence left out.
5. `excluded_genres` ("without science fiction") drop chunks by their `genres` metadata; `hard_exclusions` only filter titles. `pipeline.run_rag` gives each constraint a status per film (full report in the `rerank` trace step; the prompt gets one readable line per film and constraint in `metadata.constraints_summary`): `verified` (genres/year metadata), `probable` (key terms in the plot), `not_verifiable` (endings, tone, missing terms) or `contradicted`; plot constraints such as "no tragic ending" are never presented as verified.
6. The terminal shows the text used for the embedding and the requested genres above the K LARGO list.

## Public Runtime API

`app.py` is the stable integration layer. It exposes:

1. `RAG_CONFIG`.
2. `run_rag(config=RAG_CONFIG, query=QUERY, history=None)`.

`search_mode` is strictly validated to:

1. `semantic`
2. `hybrid`
3. `bm25`

The chosen mode is propagated to the runtime retrieval components (`rag` / `hybrid`) and does not rely on fake APIs.

## RAG Tool (OpenAI Function Calling Ready)

`app.py` also exposes a first tool-ready interface:

1. `RAG_TOOL_NAME`
2. `RAG_TOOL` (JSON schema generated from the Pydantic model `RagToolInput.model_json_schema()`)
3. `REGISTERED_TOOLS`
4. `execute_tool(name, arguments, config=RAG_CONFIG)`

This is designed so future tools can be added without refactoring the runtime core.

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
2. SQL is built in `movie_db/tool/sql/queries.py` from constant fragments; values are bind parameters only.
3. The connection is `mode=ro` + `PRAGMA query_only`, with an SQLite authorizer that allows only SELECT on the known tables and whitelisted functions; `max_limit` and `timeout_ms` bound every call.

Each run adds one `db_query` trace step with only the SQL executed (`{sql, params}`), no rows:
the terminal prints it in `presenters/terminal/movie_db/`, `presenters/web/movie_db/` serializes it for the future API.

### Evaluation

| Command | What it checks | API calls |
|---|---|---|
| `python -m movie_db.harness.evaluation.run_eval` | 6 cases: SQL, guard and results on the bundled mini dataset, scripted parser | none |
| `python -m movie_db.harness.evaluation.run_eval --live-parser` | same 6 cases with the real LLM parser | 6 × `gpt-5.6-luna` |
| `python -m movie_db.harness.evaluation.run_routing_eval --live` | 23 questions (6 DB, 5 RAG, 11 TMDb, 1 clarification; 4 are follow-ups): domain classifier + orchestrator planning only, no tool runs | 23 × `gpt-4o-mini` + 23 × `gpt-5.6-luna` |
| `python -m movie_db.harness.evaluation.run_routing_eval --live --tool tmdb_search` | only the 11 TMDb questions; the planned `requests` are also validated offline (operation, title, facets), the tool never runs | 11 × `gpt-4o-mini` + 11 × `gpt-5.6-luna` |

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
seasons and episodes, people and filmographies, collections, companies, discover by filters,
trending and charts, genres and certifications (17 typed operations, see
`tmdb/models/operation_rules.py`). Account, session, write, list, `changes` and deprecated
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

After `rag_search`, `tmdb/enrich.py` completes the movies the RAG selected (the final reranked
chunks, at most `CONFIG["orchestrator"]["rag_enrichment"]["max_candidates"]`, in RAG order) with
TMDb title, year, director, cast and overview. Metadata is attached only when the title equals the
TMDb title or original title (never by containment: "The Sinner" is not "The Sinners") and a known
year is confirmed within ±1, with a single such match; otherwise the candidate is marked
`unverified`/`not_found`/`skipped` and nothing is attributed. `tmdb_search` applies the same rule
to movies and series: without an exact title it accepts a result only if TMDb lists the
requested title among the translated or alternative titles of that same work (year ±1; e.g.
"Survival Island" → "Three", 2005), otherwise it returns `unverified_match` with the closest
results as unverified `candidates` instead of the most popular result. MovieLens rankings carry
`work_type_verified: false`: the catalog mixes films and TV series and has no reliable type. The RAG ranking is never changed, and the turn still makes at most one TMDb run.

`CONFIG["tmdb"]` has exactly three settings:

| Setting | Default | Meaning |
|---|---|---|
| `max_results` | 5 | items returned by searches, discover, trending, charts and related-title lists |
| `max_calls_per_turn` | 6 | HTTP attempts per turn: the only call limit, enforced in `tmdb/budget.py` |
| `cache_ttl` | 3600 | seconds a response is reused across turns (0 = per-turn memo only) |

Cache and memo hits cost nothing; every attempt sent counts, also when it fails; a 429 pauses
calls for `Retry-After` without retries; failures become partial results, never a broken turn.
The data passed to the LLM is bounded (`tmdb/prompt_budget.py`): identity and essentials are
always kept, long lists are capped and omissions are listed in `metadata.tmdb.omitted`. TMDb
data is requested in the turn language (`it-IT` for Italian questions, `en-US` otherwise) with
appended translations as fallback; the answer language is up to the LLM.

Each run adds one `tmdb_calls` step with only the endpoints called, key masked
(`Chiamato: https://api.themoviedb.org/3/movie/157336?api_key=***`; no credential at all with a
Bearer token), labels in Italian or English after the question. `tmdb/presenters/web/` serializes
the same step for the future API (`presenters/web/to_payload` is still not implemented).

Optional live check of undocumented behaviours (3 real calls): `python -m tmdb.harness.live_smoke --live`.

### Credits

This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise
approved by TMDB.

TMDB logo: add one of the approved logos from https://www.themoviedb.org/about/logos-attribution
here (less prominent than the NetflixScout name, as the TMDb terms require). The terminal cannot
show images, so the logo lives in this README and, later, in the web frontend's About section.

Streaming availability data is provided by JustWatch: the terminal shows the credit in every
turn whose answer may use it.

## Git Notes

`dataset/`, `dbVettoriale/` and `movie_db/data/` are local artifacts and are ignored by Git.
