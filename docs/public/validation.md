# Validation evidence

This release separates implementation correctness, synthetic decision quality and deployment checks. None establishes real-terminal ROI, calibrated confidence or enterprise readiness.

## Correctness and recovery

- Baseline before delivery changes: 138 backend tests passed.
- Final regression: 145 backend tests passed, with two upstream TestClient deprecation warnings.
- Production frontend build passed.
- Hosted Linux CI passed dependency installation, all backend tests, frontend build and browser smoke for release `15eb4fb`. An earlier CI attempt found a schedule-view grid overflow; the parent tracks were corrected before the successful run.
- Connected browser route passed: placement, three strategies, booking, stage execution, failed receiver custody, route controls and 800-pixel layout; no page errors.
- Offline assistant routing/citation suite: 11/11 passed; no paid provider call.
- Source-only checkout: fresh Python dependency installation, `npm ci`, frontend build and PostgreSQL initialization passed.
- Previous release schema 10 → schema 11 upgrade preserved the original state snapshot.
- External sender rehearsal: approved work interrupted at minute 8; cargo remained on the tractor; repeated event classified duplicate.
- Actual API-process stop/restart preserved revision, minute, containers/custody, jobs and interrupted schedule.
- Backup/restore: all 38 public tables and 2,991 rows matched a consistent exported snapshot exactly, including the interrupted workflow.

Existing tests cover approval revision checks, idempotency, rollback/retry, booking exclusions, custody and physical replay. New tests cover concurrent deliveries, malformed/authentication/scope boundaries, stale/conflicting facts, pre-commit rollback, immediate interruption and connected equipment exposure. Restore is tested in a separate randomly named database, never over live records.

## Decision quality

The connected movement suite contains eight synthetic families: reference, retrieval obstruction, full destination, calendar constraints, distant tractors, route closure, receiver failure and impossible cutoff. Each compares baseline, deadline and bounded constraint strategies.

Movement duration is deterministic. One seed per family yields 24 attempts; repeated seeds would not be independent physical uncertainty evidence. Earlier repeated-seed work was cancelled and retained as partial development evidence. The final run completed all eight cases and all 24 attempts. [Machine-readable results and source fingerprints](validation-results.json).

Compare strategies within the same model. Do not compare legacy and staged execution as if changing physical assumptions improved the optimizer. Cases inspected during development are internal regression/validation evidence, not permanently untouched holdouts.

### Observed outcomes

Values below are total terminal cargo on time, not only North Rail.

| Scenario | Baseline | Deadline | Constraint |
|---|---:|---:|---:|
| Reference | 16 | 17 | 17 |
| Retrieval obstruction | 15 | 17 | 17 |
| Full destination | 15 | 17 | 17 |
| Handling calendar | 14 | 13 | 13 |
| Distant tractors | 15 | 16 | 16 |
| Route disruption | 1 | 1 | 1 |
| Receiver disruption | 1 | 1 | 1 |
| Impossible North Rail cutoff | 14 | 14 | 14 |

Each alternative had four wins, three ties and one loss against baseline. Both disruption families interrupted all strategies; subsequent repair did not silently restart the old plan. The impossible cutoff does not prevent unrelated services completing. No candidate was rejected by physical replay in this suite after correcting the dispatch-availability constraint.

The calendar loss remains a real limitation of the available policy/option pool, not a reason to remove the case. The interface compares baseline alongside alternatives so retaining assignments remains an available decision. CP-SAT searches a bounded pool and does not guarantee it beats the baseline or heuristic.

## Metrics

On-time cargo counts unique outbound visits. Lateness includes horizon-censored unfinished cargo. Paired deltas join case/seed/strategy to the same baseline; rejected candidates stay in coverage but cannot become successful executions. Per-departure harm accompanies totals. Prediction error compares planned on-time cargo against executed outcomes. Loaded/empty travel minutes count completed portions of movement stages, including an interrupted move's progress; legacy `travel` retains its older completed-move metric.

A bounded solver optimum is not global terminal optimality. An interrupted plan remains interrupted even if the failed equipment is later repaired: these tests do not evaluate automatic replanning.

## Bounded performance observations

On an Intel macOS development laptop, with background development activity:

| Database / workload | Requests | Readers | Median state read | P95 |
|---|---:|---:|---:|---:|
| 1 shift, 144 containers, 37 jobs | 30 | 1 | 58.7 ms | 237.5 ms |
| 11 shifts, 1,584 containers, 407 jobs | 60 | 4 | 94.5 ms | 152.3 ms |

Different contention prevents interpreting these as a controlled scaling curve. The larger test increases stored shifts, not the size of one scheduling problem. No enterprise throughput claim follows. `scripts/benchmark_reads.py` reports actual sizes and a query plan so the checks can be repeated.

Placement is considerably more expensive than reading state. The five-destination browser comparison took roughly 75 seconds on this laptop when run separately from evaluation. An initial browser check exceeded its 120-second wait while several CPU-heavy checks competed; that attempt was not counted as a pass. Run bulk evaluation separately from interactive demos. A dedicated planning worker or bounded cached comparison is a possible later performance improvement, not a delivered distributed architecture.

## Limits

No live TOS feed, physical equipment dispatch, real-provider assistant quality test, human operator study or hosted environment has been validated. The feed sender is synthetic. Session/proxy guards support a private reviewer deployment; enterprise identity and per-user authorization are outside this release. Screenshots and automated walkthroughs do not substitute for an unaided human usability review.

## Documentation and readability finishing pass

The finishing pass reformatted `diagnosis_dependencies.sql` and `placement_temporal.sql`, introduced descriptive internal names and explained their aggregation/recursion invariants. Returned fields and query behavior are unchanged. Direct old/new result comparisons matched in **181 checks across 30 saved runs**, including current/historical diagnosis, empty schedules, simultaneous changes and pickups at the current minute, inside a read-only transaction.

The current application regression suite passed **141 tests** (two upstream deprecation warnings). The difference from the original 145 is the retirement of four tests belonging solely to the unused SQLite prototype; no PostgreSQL application tests were removed. The obsolete `terminal/` and `web/` entry points are no longer part of the public working tree. The publication also adds a visual decision case, data/SQL guide, design rationale and real-data validation path.

The 24-attempt evaluation report and its original fingerprints are preserved unchanged. SQL formatting and the package-description edit change source hashes; the report is historical evidence for its recorded source, not a new evaluation of this commit. The finishing pass verifies regression behavior and query equivalence without presenting another run as fresh decision-quality evidence.
