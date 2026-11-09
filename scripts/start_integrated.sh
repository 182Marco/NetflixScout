#!/bin/sh
# Integrated local configuration: cinema_sql on the schema-4 database (structured data + all MovieLens lists), the film RAG (rag_search) and the series RAG
# (series_rag_search), with movie_db_search NOT registered. Nothing in the code defaults changes: this script only sets the environment of ONE process.
#
#   ./scripts/start_integrated.sh --check      (offline: files, Qdrant, collections, the tools and rules the planner will have; no model call)
#   ./scripts/start_integrated.sh              (backend on http://127.0.0.1:8001; PORT=8000 to use the usual port after stopping the other backend)
#
# Start Qdrant first (./scripts/start_qdrant.sh, another terminal). Frontend: see docs/cinema_db/INTEGRATED_LOCAL.md.
# Rollback: stop this process and start the backend as before (uvicorn web_api.main:app ... without these variables): the runtime file and movie_db_search come back.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export CINEMA_DB_ENABLED=1
export CINEMA_DB_PATH="${CINEMA_DB_PATH:-cinema_db/data/cinema.v4.candidate6.sqlite3}"
export SERIES_RAG_ENABLED=1
PORT="${PORT:-8001}"
[ -f "$CINEMA_DB_PATH" ] || { echo "database not found: $CINEMA_DB_PATH (build it: python -m cinema_db.harness.build.imdb_layer --movielens --out PATH)" >&2; exit 1; }
[ -f .venv/bin/activate ] && . .venv/bin/activate
if [ "${1:-}" = "--check" ]; then
  exec python - <<'PY'
from app import build_ready_app_or_exit

app = build_ready_app_or_exit()
orchestrator = app["orchestrator"]
names = orchestrator._allowed_tool_names()
prompt = orchestrator._planning_instructions(names, "")
print("tools:", ", ".join(sorted(orchestrator.tools)))
print("movie_db_search registered:", "movie_db_search" in orchestrator.tools, "| named in the planner prompt:", "movie_db_search" in prompt)
print("planner prompt:", len(prompt), "characters; film RAG imdb_id hand-over:", app["config"]["rag"]["film_index"].get("expose_imdb_id"))
print("OK: Qdrant reachable, film and series collections present, database opens with its policy.")
PY
fi
exec uvicorn web_api.main:app --host 127.0.0.1 --port "$PORT"
