#!/bin/sh
# Shows which NetflixScout services are running (Qdrant 6333, backend 8000/8001, frontend 8080).
#
#   ./scripts/status_services.sh        exit 0 = nothing running (all stopped), exit 1 = something is still running
#   PORTS="6333 8000" ./scripts/status_services.sh   to check other ports
set -u
PORTS="${PORTS:-6333 8000 8001 8080}"
running=0
for p in $PORTS; do
  line=$(lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}')
  if [ -n "$line" ]; then echo "port $p: RUNNING  $line"; running=1; else echo "port $p: free"; fi
done
if [ "$running" -eq 0 ]; then echo "=> all stopped"; else echo "=> something is still running (nf-stop to stop it)"; fi
exit "$running"
