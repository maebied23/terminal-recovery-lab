# Architecture

## State and decisions

The React interface reads FastAPI projections. PostgreSQL holds canonical operational entities, historical snapshots/events, commands, schedules and evaluation results. Server-sent invalidation and polling refresh views; browser animation is not the source of operational truth.

`app/domain.py` defines transitions and operational guards. `app/store.py` persists revisions and commands. `app/datasets.py` validates versioned input packs; `app/feed.py` reconciles observations while retaining rejected and stale deliveries as evidence.

`app/integration.py::receive` accepts narrowly scoped equipment observations through the same receipt ledger and reconciliation transaction. An accepted fact interrupts stale active schedules immediately; repeated transport delivery remains visible without duplicating the equipment effect.

A physical container has a visit describing its current journey. A visit may link to a departure commitment. Work orders connect the container and visit to source/destination locations; directed prerequisite edges connect work across containers. Availability describes when equipment may work, reservations describe approved future use, and custody describes what currently holds cargo. These concepts are deliberately separate.

## Placement and scheduling

`sql/placement_candidates.sql` traverses successor work, aggregates candidate constraints without multiplying rows through joins, and ranks bounded destinations. `sql/placement_temporal.sql` turns pickup/drop events into inventory intervals using signed changes and window functions. These profiles describe candidate execution, not guaranteed future vacancy.

`app/placement.py` and `app/placement_store.py` preserve alternatives and guard instruction changes by revision. Changing a destination does not move cargo or book equipment.

`app/scheduling.py` compares policies. For the connected movement model, `app/stage_planning.py` constructs staged candidates and independently replays them. CP-SAT checks both stage intervals and the availability of the assigned bundle at initial dispatch. It operates on a bounded option pool; a solver result can fail the physical replay and remain visible as a rejected alternative.

## Movement and persistence

`app/movement.py` resolves directed routes and travel assumptions. `app/move_execution.py` handles pickup, transfer and setdown. `app/stage_execution.py` dispatches approved staged work. `app/movement_store.py` projects custody and reservations into PostgreSQL. Migrations 008–010 add the movement model and its invariants, including deferred custody uniqueness.

Destination capacity and handling availability are conservative constraints. Receiving positions are simplified. A failed receiver can leave cargo on its tractor; reservations and current ownership must not be confused. Actual stage history remains evidence after a reservation is released.

## Evaluation and assistance

`app/evaluation.py` executes fixed-plan paired trials; `app/evaluation_store.py` persists leased work and results. SQL reports compare outcomes and expose harmed departures, incomplete work and regressions. Reports fingerprint application code, SQL, migrations, input/scenario files and dependency locks. A queued evaluation refuses execution if those sources change. The deterministic movement suite uses one execution per family/strategy. These synthetic tests are not independent terminal measurements.

`app/assistant.py` exposes typed, read-only evidence tools. An optional model selects canonical evidence claims; application code renders the facts. It cannot issue approvals, execute arbitrary SQL or replace the scheduler.

## Deployment boundary

Run one API process. PostgreSQL supports transactions, revision guards and durable work, but this application is not a validated multi-worker production deployment. Full snapshot/projection writes, retention, enterprise identity, live connectors, recovery exercises and load testing remain deployment considerations.
