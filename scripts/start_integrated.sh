#!/bin/sh
# Integrated runtime (default since FASE 24): cinema_sql on the schema-4 database (candidate 6: structured data + all MovieLens lists), the film RAG (rag_search) and the
# series RAG (series_rag_search); there is no separate MovieLens tool. Both systems are ON by DEFAULT in app.py, so this script no longer forces anything: it only starts the
# backend, checks first, and lets the variables win:  CINEMA_DB_ENABLED=0 and/or SERIES_RAG_ENABLED=0 switch a system off, CINEMA_DB_PATH chooses another file.
#
#   ./scripts/start_integrated.sh --check      (read only: files, Qdrant collections, the tools and rules the planner will have, the database identity; no model call, starts nothing)
#   ./scripts/start_integrated.sh              (backend on http://127.0.0.1:8001; PORT=8000 to use the usual port after stopping the other backend)
#
# Start Qdrant first (./scripts/start_qdrant.sh, another terminal). Frontend: see docs/cinema_db/INTEGRATED_LOCAL.md.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8001}"
DB_PATH="${CINEMA_DB_PATH:-cinema_db/data/cinema.v4.candidate6.sqlite3}"
case "${CINEMA_DB_ENABLED:-1}" in 0|false|no|off|FALSE|NO|OFF) ;; *)
  [ -f "$DB_PATH" ] || { echo "database not found: $DB_PATH (build it: python -m cinema_db.harness.build.imdb_layer --movielens --out PATH)" >&2; exit 1; } ;;
esac
[ -f .venv/bin/activate ] && . .venv/bin/activate
if [ "${1:-}" = "--check" ]; then
  exec python - <<'PY'
from app import build_ready_app_or_exit

app = build_ready_app_or_exit()
orchestrator = app["orchestrator"]
names = orchestrator._allowed_tool_names()
prompt = orchestrator._planning_instructions(names, "")
print("tools:", ", ".join(sorted(orchestrator.tools)))
print("planner prompt:", len(prompt), "characters; film RAG imdb_id hand-over:", app["config"]["rag"]["film_index"].get("expose_imdb_id"))
if app["config"]["cinema_db"]["enabled"]:
    from cinema_db.harness import candidate

    identity = candidate.identify(app["config"]["cinema_db"]["db_path"], strict_name=False)  # build_info only: schema and data digest of the file in use
    print("database:", identity["path"], "| schema", identity["schema_version"], "| digest", identity["content_sha256"][:16] + "...")
print("cinema_sql:", "on" if "cinema_sql" in orchestrator.tools else "OFF", "| series_rag_search:", "on" if "series_rag_search" in orchestrator.tools else "OFF", "| rag_search:", "on" if "rag_search" in orchestrator.tools else "OFF")
print("OK: Qdrant reachable, film and series collections present, database opens with its policy.")
PY
fi
exec uvicorn web_api.main:app --host 127.0.0.1 --port "$PORT"
