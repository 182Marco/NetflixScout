#!/bin/sh
# Stops every NetflixScout service that is listening: Qdrant (6333), the backend (8000 and 8001).
#
#   ./scripts/stop_services.sh        (add 8080 to the list with: PORTS="6333 8000 8001 8080" to stop the frontend too)
#
# Sends SIGTERM (clean shutdown, never kill -9: Qdrant must flush its storage) and waits up to 15 seconds.
set -u
PORTS="${PORTS:-6333 8000 8001}"
PIDS=""
for p in $PORTS; do
  for pid in $(lsof -nP -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null); do
    case " $PIDS " in *" $pid "*) ;; *) PIDS="$PIDS $pid"; echo "port $p -> pid $pid ($(ps -o command= -p "$pid" | cut -c1-70))";; esac
  done
done
[ -n "$PIDS" ] || { echo "Nothing is running on: $PORTS"; exit 0; }
kill $PIDS
i=0
while [ $i -lt 15 ]; do
  alive=""
  for pid in $PIDS; do kill -0 "$pid" 2>/dev/null && alive="$alive $pid"; done
  [ -z "$alive" ] && { echo "All stopped."; exit 0; }
  sleep 1; i=$((i+1))
done
echo "Still running after 15 s:$alive (not forced: check them with lsof, do not use kill -9 on Qdrant)" >&2
exit 1
