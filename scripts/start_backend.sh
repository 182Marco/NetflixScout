#!/bin/sh
# Starts the NetflixScout backend API (uvicorn, one worker) on 127.0.0.1:8000. Qdrant must already be running.
#
#   ./scripts/start_backend.sh        (Ctrl+C stops it; PORT=8001 ./scripts/start_backend.sh uses another port)
#
# Refuses to start if the port is already taken (a backend, or anything else, is listening there).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8000}"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use:" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2
  echo "Stop it first (scripts/stop_services.sh) or choose another port with PORT=...." >&2
  exit 1
fi
if ! curl -s -m 3 http://127.0.0.1:6333/collections >/dev/null 2>&1; then
  echo "Qdrant does not answer on 127.0.0.1:6333: start it first (scripts/start_qdrant.sh)." >&2
  exit 1
fi
# Pages allowed to call the API from the browser (CORS). The built-in defaults (localhost:8080 and :5173) stay in the
# list; 127.0.0.1 and port 8081 are added. A WEB_API_CORS_ORIGINS set by the caller wins and replaces this list.
export WEB_API_CORS_ORIGINS="${WEB_API_CORS_ORIGINS:-http://localhost:8080,http://localhost:5173,http://localhost:8081,http://127.0.0.1:8080,http://127.0.0.1:5173,http://127.0.0.1:8081}"
cd "$ROOT"
[ -x .venv/bin/uvicorn ] || { echo ".venv/bin/uvicorn not found: create the virtualenv (see README)." >&2; exit 1; }
exec .venv/bin/uvicorn web_api.main:app --host 127.0.0.1 --port "$PORT"
