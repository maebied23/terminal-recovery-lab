# Northstar · Terminal Recovery Lab

A container-terminal decision workbench: identify cargo at risk of missing a departure, trace the work blocking it, compare feasible recovery schedules, book equipment, and inspect what actually happens.

**Python / FastAPI · PostgreSQL · React / TypeScript · OR-Tools CP-SAT**

All operational inputs are synthetic and inspectable. The application runs locally without Docker or an LLM API key.

## The decision loop

1. **Investigate:** select a departure and container. The map and dependency view connect its current position, covering cargo, required moves and equipment.
2. **Compare placement:** inspect alternative destinations for a queued relocation, including downstream work and capacity over time.
3. **Compare & book:** evaluate baseline, deadline-first and bounded constraint schedules. Inspect competing departures and named equipment reservations before approval.
4. **Execute:** advance the simulated clock and follow pickup, tractor transfer and setdown. Failures retain cargo custody instead of teleporting a load.
5. **Verify:** inspect input evidence, commands, historical revisions and paired evaluation results. Approval, execution and successful departure are separate facts.

## Capabilities

| Area | Implemented behavior |
|---|---|
| Data ingestion | Six versioned packs; checksummed CSV/JSON inputs; source identity mapping; duplicate, stale and conflicting observation handling |
| Operational model | Containers, visits, commitments, locations, prerequisite work, equipment availability, reservations and custody |
| SQL decision support | Recursive dependency traversal, correlated aggregates, window ranking and temporal occupancy calculations |
| Scheduling | Baseline and heuristic policies, bounded CP-SAT options, independent physical replay and explicit rejected alternatives |
| Movement | Directed metric routes, empty tractor repositioning, staged handovers and equipment failure/recovery |
| Controlled actions | Revision-bound approvals, durable command processing and persisted execution evidence |
| Evaluation | Paired synthetic execution trials, per-departure harm and failure reporting |
| Assistant | Read-only evidence tools; local fallback or optional OpenAI claim selection; no arbitrary SQL or action approval |

## Run locally

Prerequisites: **Python 3.11+, Node.js 22.12+ and PostgreSQL 17**. Use a dedicated project database.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
cd frontend
npm ci
npm run build
cd ..
PG_BIN=/path/to/postgresql/bin ./scripts/start.sh
```

`PG_BIN` is the directory containing `initdb`, `pg_ctl` and `psql`. Common Homebrew PostgreSQL 17 installations are detected automatically. The helper initializes its own local cluster on **55432** and saves generated credentials under ignored `.local/`.

Open **http://127.0.0.1:8790**. The shift starts paused. Stop the API with Ctrl+C; `./scripts/stop.sh` also stops the project database.

For an existing dedicated PostgreSQL database, export `DATABASE_URL`, then run:

```bash
.venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8790
```

Startup applies the migrations. Do not point this application or its integration tests at another application's database. For frontend development, run `npm run dev` in `frontend` with the backend running. API documentation is available at `/docs`.

## Try a complete case

In **Scenario lab**, import **Connected movement shift** to create a paused run with staged routing. In **Operations**, select **North Rail / Container 121**:

- Follow the prerequisite relocation of Container 122 on the map.
- Inspect required equipment and compare relocation destinations.
- Build schedules in **Compare & book**. A solver option can be rejected by physical replay; inspect the reason rather than assuming it is best.
- Approve a feasible schedule and advance one minute at a time in **Execution**.
- Inspect reservations, actual custody and the corresponding evidence.

Scenario controls require the locally generated administrator code (`cat .local/admin-code`). Branch a run before trying equipment failures or route closures. Older input packs intentionally retain the earlier whole-move execution model.

## Code map

| Directory | Purpose |
|---|---|
| `app/` | API, domain rules, ingestion, planning, execution, PostgreSQL adapters and assistant |
| `frontend/src/` | Connected case workspace, terminal map, schedule lanes, evidence and scenario interfaces |
| `migrations/` | Ordered PostgreSQL schema migrations |
| `sql/` | Operational diagnosis, placement, scheduling and evaluation queries |
| `datasets/` | Versioned synthetic input packs and shared source tables |
| `evaluation/` | Evaluation cases and scenario definitions |
| `tests/` | Domain, API, persistence, planning and reconciliation tests |
| `scripts/` | Local launch, dataset validation and evaluation tools |
| `terminal/`, `web/` | Preserved earlier SQLite prototype and its regression coverage; not the current application |

Read [architecture and boundaries](docs/public/architecture.md) and [dataset contracts](datasets/README.md).

## Verification

Stop the API before integration tests so its background workers do not compete with test workers. Keep the dedicated PostgreSQL cluster running.

```bash
./scripts/local-db.sh start
.venv/bin/python -m pytest tests -q --tb=short
.venv/bin/python -m scripts.dataset validate movement-shift
cd frontend
npm run build
```

The latest implementation checks included a 134-test full-suite checkpoint, followed by a 37-test movement/scheduling/placement regression run after further changes, a frontend production build and browser workflow checks. These are development checkpoints, not a production certification or a claim that the full suite was rerun for this documentation release.

Evaluation scripts write local reports. Before running them on a fresh checkout:

```bash
mkdir -p docs/evaluation docs/assistant docs/diagnosis
```

`audit_evaluation_sql.py` requires the holdout report generated by the evaluation script. Browser scripts under `frontend/scripts/` use Playwright and may create retained synthetic runs.

## Optional assistant

The evidence fallback works without credentials. For OpenAI, export `TERMINAL_ASSISTANT_PROVIDER=openai` and `OPENAI_API_KEY` locally before launch. See `.env.example`; the launch script does not automatically load `.env`. Provider quality has not been validated with live paid-model evaluation.

## Scope and limitations

This is an operational decision prototype, not a production terminal operating system. It has no live TOS/AIS integration or physical equipment writeback. Travel rates, equipment envelopes and handling times are authored assumptions. Evaluation measures synthetic behavior, not calibrated confidence or real-terminal ROI.

The deployment is a single API process with local background workers. Authentication is a local administrator mechanism, not enterprise identity. Scheduling searches a bounded option set; crane redeployment, general time-window routing and automatic replanning are not implemented. Dataset and historical evidence retention have not been validated at enterprise scale.
