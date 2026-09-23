#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LAB_ROOT"
./scripts/local-db.sh start
if [ ! -d frontend/dist ]; then (cd frontend && npm run build); fi
exec .venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8790 --timeout-graceful-shutdown 5
