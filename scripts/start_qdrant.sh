#!/bin/sh
# Starts the Qdrant server (official binary, version 1.20.0) on the project's index, listening only on 127.0.0.1:6333.
#
#   ./scripts/start_qdrant.sh        (from the repository root; Ctrl+C stops it)
#
# The binary is looked for, in order, at: $QDRANT_BIN, <repository>/bin/qdrant, `qdrant` in the PATH. To install it,
# download the official release for your system from https://github.com/qdrant/qdrant/releases/tag/v1.20.0, unpack
# it and put the `qdrant` file in <repository>/bin/ (that folder is not versioned).
# The index lives in dbVettoriale/qdrant_openai/storage (QDRANT_STORAGE overrides it). The server runs from a temporary
# folder, not from the repository, because it drops a marker file in its working directory.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "${QDRANT_BIN:-}" ]; then
  BIN="$QDRANT_BIN"
elif [ -x "$ROOT/bin/qdrant" ]; then
  BIN="$ROOT/bin/qdrant"
elif command -v qdrant >/dev/null 2>&1; then
  BIN="$(command -v qdrant)"
else
  echo "Qdrant binary not found. Download Qdrant 1.20.0 from https://github.com/qdrant/qdrant/releases/tag/v1.20.0," >&2
  echo "unpack it and put the 'qdrant' file in $ROOT/bin/ (or set QDRANT_BIN)." >&2
  exit 1
fi
[ -x "$BIN" ] || { echo "QDRANT_BIN=$BIN is not an executable file" >&2; exit 1; }
STORAGE="${QDRANT_STORAGE:-$ROOT/dbVettoriale/qdrant_openai/storage}"
[ -d "$STORAGE" ] || { echo "storage folder not found: $STORAGE" >&2; exit 1; }
WORK="$(mktemp -d)"
cd "$WORK"
export QDRANT__SERVICE__HOST=127.0.0.1
export QDRANT__STORAGE__STORAGE_PATH="$STORAGE"
export QDRANT__STORAGE__SNAPSHOTS_PATH="$WORK/snapshots"
export QDRANT__TELEMETRY_DISABLED=true
exec "$BIN"
