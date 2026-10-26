# NetflixScout

This repository integrates the RAG modules into a reproducible local pipeline and a public runtime entrypoint.

## Project Layout

```text
/
├── dataset/            # local corpus input (not versioned)
├── dbVettoriale/       # local vector DB persistence (not versioned)
│   ├── openai/
│   └── local/
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
├── presenters/         # the only output layer: present(turn, channel)
│   ├── channel.py      # OutputChannel (terminal | web)
│   ├── story_view.py   # the turn story: a few plain sentences (what, where, how it went), it/en
│   ├── rag_view.py db_view.py api_view.py youtube_view.py wikipedia_view.py   # channel-neutral views of the tool steps
│   ├── terminal/       # box.py, session.py, blocks.py, renderer.py (TerminalObserver, STEP_RENDERERS)
│   │   └── rag/ db/ api/ youtube/ wikipedia/   # blocks.py + renderer.py per tool
│   └── web/            # observer.py (WebObserver, live events), payload.py (to_payload, STEP_SERIALIZERS)
│       └── rag/ db/ api/ youtube/ wikipedia/   # serializer.py per tool, same shared view as the terminal
├── web_api/            # HTTP/SSE server (FastAPI): conversations, streamed answer, web_lists; see FRONTEND_API.md
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
```

`YOUTUBE_API_KEY` is read only by `tool/youtube/auth.py`, on the first YouTube search; the base URL is
a constant (`https://www.googleapis.com/youtube/v3`), never read from the environment.

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
3. Cleans text with `tool.rag.EmbeddingProcess.clean` pipelines.
4. Chunks text with `tool.rag.EmbeddingProcess.chunk` semantic chunking (`chunk_semantic`).
5. Embeds chunks with `tool.rag.FromQueryEmbeddingToRes.embeddings`.
6. Indexes into Chroma via `tool.rag.FromQueryEmbeddingToRes.vectorstore` APIs.

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
2. The domain classifier blocks off-topic and jailbreak requests; otherwise the orchestrator (`orchestrator.py`) rewrites the query as standalone, picks a tool (`rag_search`, `movie_db_search`, `tmdb_search`, `youtube_search`, `wikipedia_search`) and may chain more tools in the same turn.
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
seasons and episodes, people and filmographies, collections, companies, discover by filters,
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

Each run adds one `tmdb_calls` step with only the endpoints called, key masked
(`Chiamato: https://api.themoviedb.org/3/movie/157336?api_key=***`; no credential at all with a
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

Each run adds one `youtube_calls` step: masked calls (`https://www.googleapis.com/youtube/v3/search?key=***`),
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

Each step adds a `wikipedia_calls` step: base URLs, the pages read (title, language, public URL,
sections read, sections left out), and the credit the licence requires. Wikipedia text is CC BY-SA
4.0: the terminal and the web name the source, link every page and the licence, and say the text
was reworded and shortened. The text of an article is third-party data and is never treated as
instructions. The web frontend must render the new step (`web_api/FRONTEND_API.md`).

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
contract, payloads, errors, CORS and environment variables are in `web_api/FRONTEND_API.md`. There is
no authentication: the backend key and its budget are the only protection (portfolio project).
