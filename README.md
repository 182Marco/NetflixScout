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
├── app.py              # public API + RAG Tool facade
├── buildSemanticDb.py  # reproducible semantic DB builder
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
```

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
2. `RAG_TOOL` (JSON schema generated from Pydantic via `rag.FromQueryEmbeddingToRes.tools.definisci_tool`)
3. `REGISTERED_TOOLS`
4. `execute_tool(name, arguments, config=RAG_CONFIG)`

This is designed so future tools can be added without refactoring the runtime core.

## Git Notes

`dataset/` and `dbVettoriale/` are local artifacts and are ignored by Git.
