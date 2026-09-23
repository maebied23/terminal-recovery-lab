#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG_BIN="${PG_BIN:-$LAB_ROOT/.local/pg-dist/postgresql@17/17.10/bin}"
if [ ! -x "$PG_BIN/pg_ctl" ]; then
  if [ -x /usr/local/opt/postgresql@17/bin/pg_ctl ]; then PG_BIN=/usr/local/opt/postgresql@17/bin
  elif [ -x /opt/homebrew/opt/postgresql@17/bin/pg_ctl ]; then PG_BIN=/opt/homebrew/opt/postgresql@17/bin
  else echo 'Install PostgreSQL 17 and set PG_BIN to its bin directory.'; exit 1; fi
fi
mkdir -p "$LAB_ROOT/.local"
if [ "${1:-start}" = stop ]; then
  "$PG_BIN/pg_ctl" -D "$LAB_ROOT/.local/pg-data" stop -m fast
  exit
fi
if [ ! -e "$LAB_ROOT/.local/pg-data/PG_VERSION" ]; then
  python3 - "$LAB_ROOT" <<'PY'
import pathlib,secrets,sys
root=pathlib.Path(sys.argv[1])/'.local';password=secrets.token_urlsafe(24)
for name,text in [('db-password',password),('database-url',f'postgresql://terminal_lab:{password}@127.0.0.1:55432/terminal_lab')]:
 p=root/name;p.write_text(text);p.chmod(0o600)
PY
  "$PG_BIN/initdb" -D "$LAB_ROOT/.local/pg-data" -U terminal_lab -A scram-sha-256 --pwfile="$LAB_ROOT/.local/db-password" --locale=C -E UTF8 > "$LAB_ROOT/.local/initdb.log"
  cat >> "$LAB_ROOT/.local/pg-data/postgresql.conf" <<'CONF'
listen_addresses = '127.0.0.1'
port = 55432
unix_socket_directories = ''
shared_buffers = '64MB'
max_connections = 32
work_mem = '4MB'
cluster_name = 'northstar-lab'
CONF
fi
if ! "$PG_BIN/pg_ctl" -D "$LAB_ROOT/.local/pg-data" status >/dev/null 2>&1; then
 "$PG_BIN/pg_ctl" -D "$LAB_ROOT/.local/pg-data" -l "$LAB_ROOT/.local/postgres.log" start
fi
export PGPASSWORD="$(cat "$LAB_ROOT/.local/db-password")"
if ! "$PG_BIN/psql" -h 127.0.0.1 -p 55432 -U terminal_lab -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='terminal_lab'" | grep -q 1; then
 "$PG_BIN/createdb" -h 127.0.0.1 -p 55432 -U terminal_lab terminal_lab
fi
unset PGPASSWORD
printf '%s\n' 'Dedicated PostgreSQL ready on 127.0.0.1:55432.'
