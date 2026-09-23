#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$LAB_ROOT/.local/api.pid" ]; then
  LAB_PID="$(cat "$LAB_ROOT/.local/api.pid")"
  if ps -p "$LAB_PID" -o command= | grep -q 'uvicorn app.api:app'; then
    if lsof -a -p "$LAB_PID" -d cwd -Fn | grep -Fqx "n$LAB_ROOT"; then
      kill -TERM "$LAB_PID"
      for attempt in {1..150}; do
        if ! kill -0 "$LAB_PID" 2>/dev/null; then break; fi
        sleep 0.2
      done
      if kill -0 "$LAB_PID" 2>/dev/null; then
        echo 'API is still shutting down; database left running. Retry shortly.'
        exit 1
      fi
      echo 'Stopped the project API.'
    else echo 'PID does not belong to this project directory; refusing to stop it.'; exit 1; fi
  fi
fi
"$LAB_ROOT/scripts/local-db.sh" stop
