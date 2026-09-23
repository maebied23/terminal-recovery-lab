# Deployment and recovery

## Supported profile

One FastAPI process, its local background threads, PostgreSQL 17 and a built frontend. Use the README for local setup. No Kubernetes, broker or multi-process worker deployment is required or validated. Run migrations through application startup; applied migrations are immutable.

For a private reviewer demo, retain loopback binding and use an SSH tunnel or an authenticated TLS reverse proxy. Nonlocal Host values require an explicit `TERMINAL_ALLOWED_HOSTS` allowlist and `TERMINAL_PROXY_KEY`. The proxy must authenticate reviewers, strip any incoming `X-Terminal-Proxy` header and inject its configured secret upstream. Keep the backend port unreachable from the public network. Enable `TERMINAL_SECURE_COOKIE=1` behind HTTPS. All reviewers share the demo operator role; this is not enterprise per-user authorization.

Sessions expire after 24 hours and are intentionally process-local: restart requires logging in again. Mutation requests require same-origin/session/CSRF checks, except the separately authenticated, narrowly scoped equipment feed. Rate limiting and TLS belong at the authenticating proxy. Do not enable internet access by removing host protection. A hosted environment has not been provisioned as part of the repository.

## Health and logs

- `/api/live`: HTTP process responds.
- `/api/ready`: database reachable and command/planning worker progress recently recorded. The planner has a longer freshness budget because bounded planning is CPU-heavy.
- `/api/health`: database and configured assistant mode.

Readiness is a single-process watchdog, not a proof that every queued job will finish. Existing command/worker logs retain command/run identities; equipment receipts log run, receipt, revision and status without credentials or raw payloads. PostgreSQL queue states and receipt statuses remain inspectable evidence.

`TERMINAL_STATE_DIR` separates runtime administrator code/PID files for isolated review processes. It does not change `DATABASE_URL`. Keep state directories and backups out of Git.

## Backup and isolated restoration

Set `PG_BIN` to PostgreSQL 17 tools and `DATABASE_URL` to the intended project database (otherwise the local generated URL is used).

```bash
.venv/bin/python scripts/database_archive.py backup .local/review.dump
.venv/bin/python scripts/database_archive.py verify-restore .local/review.dump
```

The backup uses an exported PostgreSQL snapshot so its dump and verification hashes see the same committed state. A companion JSON holds row counts and order-independent content hashes for every public table. Restore verification creates a randomly named `terminal_restore_*` database, restores without object owners, compares all table contents and drops that isolated database. It never restores over an existing user database. The database role needs create-database permission for this verification.

This checks content recovery, not a zero-downtime failover SLA. Archives contain operational history. Protect file permissions, retain them privately and handle backup retention explicitly.

## Checks

`.github/workflows/verify.yml` provisions disposable PostgreSQL, runs backend tests, builds the frontend and runs a browser smoke route. Local equivalent: README tests, followed by `node scripts/release-smoke.mjs` from `frontend` with the API running. Browser outputs go to ignored `.local/release-browser`.

`scripts/benchmark_reads.py --run RUN --requests 30 --concurrency 1` records actual table counts, state-read latency distribution and a PostgreSQL query plan. Repeat with concurrency 4 to inspect contention. These bounded local reads do not measure production planner throughput or enterprise scale.
