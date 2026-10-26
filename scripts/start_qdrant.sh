#!/bin/sh
# Starts the Qdrant server (official binary, version 1.20.0) on the project's index, listening only on 127.0.0.1:6333.
#
#   QDRANT_BIN=/path/to/qdrant ./scripts/start_qdrant.sh        (run it from the repository root)
#
# QDRANT_BIN has no default on purpose: it is the path of the binary you downloaded (see docs/qdrant_migration/server.md).
# The server runs from a temporary folder, not from the repository, because it drops a marker file in its working directory.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${QDRANT_BIN:?set QDRANT_BIN to the path of the qdrant 1.20.0 binary (see docs/qdrant_migration/server.md)}"
[ -x "$QDRANT_BIN" ] || { echo "QDRANT_BIN=$QDRANT_BIN is not an executable file" >&2; exit 1; }
STORAGE="${QDRANT_STORAGE:-$ROOT/dbVettoriale/qdrant_openai/storage}"
[ -d "$STORAGE" ] || { echo "storage folder not found: $STORAGE" >&2; exit 1; }
WORK="$(mktemp -d)"
cd "$WORK"
export QDRANT__SERVICE__HOST=127.0.0.1
export QDRANT__STORAGE__STORAGE_PATH="$STORAGE"
export QDRANT__STORAGE__SNAPSHOTS_PATH="$WORK/snapshots"
export QDRANT__TELEMETRY_DISABLED=true
exec "$QDRANT_BIN"
