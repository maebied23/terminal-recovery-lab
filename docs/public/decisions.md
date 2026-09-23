# Design decisions

Northstar focuses on one connected operational question: which moves, destinations and equipment bookings can protect departure commitments under constrained capacity? This scope determines the architecture. It is not a complete terminal operating system, berth planner or autonomous dispatcher.

## 1. Start with a decision, then model its evidence

A delayed container is not an isolated record. Its outbound visit links to a commitment; its final move may depend on relocating another container; both moves require suitable equipment and destination capacity. The interface follows that chain so a planner can distinguish a physical obstruction from an authority hold, an unavailable machine or an impossible cutoff.

A generic dashboard could display all those facts separately. The chosen approach instead preserves the selected departure and cargo across investigation, placement, scheduling and execution. The cost is a more explicit domain model and careful selection/history handling. The benefit is that the user can trace a proposed action to its supporting inputs.

See [the complete case](decision-case.md), `app/diagnosis.py`, `app/relationships.py` and `frontend/src/`.

## 2. PostgreSQL owns operational state and relationships

The application uses relational keys for operational identity and relationships, JSONB for flexible attributes and exact snapshots, and transactions for coordinated changes. A dependency graph does not require a separate graph database: `job_dependencies` is an edge table, and recursive SQL answers the bounded traversal questions needed here.

This keeps ingestion, approval, bookings and evidence within one transaction boundary. A separate graph store and event broker could support different workloads, but would introduce synchronization and recovery responsibilities that this single-process prototype does not justify. The tradeoff is write amplification from snapshot/projection persistence and limited evidence about larger workloads. PostgreSQL alone does not make the application a scalable multi-worker deployment.

See [data and SQL](data-and-sql.md), `app/store.py::persist` and migrations 001–011. The earlier SQLite prototype was retired from the active source tree; the current runtime has one documented storage path.

## 3. Separate physical identity, visits and commitments

A container identifies a physical object. A visit describes its journey in the modeled shift. A commitment describes the outbound service obligation. A work order identifies something that must be done, not the cargo itself. Dependency edges can connect work for different containers.

Putting all of this in one container status field would be simpler but would obscure which journey is late and why moving one object helps another. Explicit relationships support visit-level outcome counts and explain shared work without multiplying cargo in joins. The prototype is still a bounded shift model, not a validated global container lifecycle registry.

See `migrations/002_relationships.sql`, `003_datasets.sql` and `sql/diagnosis_dependencies.sql`.

## 4. Keep proposed placement, booking and custody distinct

Choosing a relocation destination changes instructions, including the affected later pickup. It does not reserve equipment or move cargo. Approving a schedule books named equipment intervals. Execution then changes physical custody through pickup, transfer and setdown.

If a receiving crane fails, the tractor can still hold the load while future bookings are released. Collapsing these facts into one status would incorrectly imply arrival or free the tractor for another load. PostgreSQL constraints and domain transitions protect the distinction; the UI exposes the current holder separately from future reservations.

This introduces more tables and transition rules. It also makes failures inspectable. Migration 009 defers equipment-custody uniqueness until transaction end so a valid release/acquire handover is not rejected because of row update order.

See `app/placement_store.py::approval`, `app/schedule_store.py::approval`, `app/move_execution.py` and migrations 008–009.

## 5. Use bounded optimization and independent physical replay

Baseline, deadline-first and constraint-based schedules provide explicit alternatives. CP-SAT searches a bounded pool of generated stage options, including resource and dispatch constraints. It is not proof of a globally optimal terminal plan.

Every candidate must also survive execution through the physical model. This separate check caught a concrete mismatch: non-overlapping stage intervals alone did not express the domain's requirement that the assigned resource bundle be available at initial dispatch. The planner was corrected rather than weakening replay.

The tradeoff is computation time and a limited option pool. In the published handling-calendar case, both alternatives served 13 cargo on time while baseline served 14. Keeping baseline visible is therefore part of the decision design, not just an evaluation convenience. Replay is a separate validation path within the same authored model; it is not external validation of terminal physics.

See `app/stage_planning.py::constraint_schedule`, `dispatch_conflict`, `replay`, and [measured results](validation.md).

## 6. Retain bad deliveries as evidence without accepting bad facts

The equipment adapter accepts one narrow observation contract. Identity mapping, source authority, sequence and observation time determine whether a receipt can change state. Duplicate delivery remains visible but does not repeat the equipment effect. A conflicting identity or event is not silently repaired into a plausible fact.

Receipt, reconciliation, interruption and persistence share one transaction. Acknowledgment follows commit. This supports retry after a lost response without claiming exactly-once delivery across a network. A separate event broker is unnecessary for this demonstrated request-driven boundary; high-volume independent producers would require a new capacity and recovery assessment.

See `app/integration.py::receive`, `app/feed.py` and [the integration contract](integration.md).

## 7. Treat the assistant as an evidence interface

The scheduler and operational guards determine feasible actions. The assistant exposes typed, read-only evidence tools; optional language-model use selects supported claims, and application code renders the facts. It cannot run arbitrary SQL, approve a plan or dispatch equipment.

This limits conversational freedom but preserves a clear authority boundary. The product remains usable without a model key. Offline routing/citation tests do not establish paid-provider answer quality; that has not been measured.

See `app/assistant.py::assistant`, `model_answer` and `tests/test_assistant.py`.

## 8. Preserve outcomes that challenge the implementation

The evaluation compares strategies on the same authored conditions, includes harmed departures and interruptions, and fingerprints the source used. Deterministic movement runs use one execution per family/strategy: repeating seeds would not create independent physical uncertainty evidence.

Averages alone could conceal a regression or a failed plan. Published per-case results make those limitations reviewable. They measure behavior under synthetic assumptions, not customer value. Code changes, including SQL formatting, alter source fingerprints; historical reports continue to identify the version that produced them.

See `app/evaluation.py`, `app/evaluation_store.py`, `sql/evaluation_service_impact.sql` and [validation](validation.md).
