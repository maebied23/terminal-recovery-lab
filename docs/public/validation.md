# Validation evidence

This release separates implementation correctness, synthetic decision quality and deployment checks. None establishes real-terminal ROI, calibrated confidence or enterprise readiness.

## Correctness and recovery

- Baseline before delivery changes: 138 backend tests passed.
- Final regression: 145 backend tests passed, with two upstream TestClient deprecation warnings.
- Production frontend build passed.
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

Movement duration is deterministic. One seed per family yields 24 attempts; repeated seeds would not be independent physical uncertainty evidence. Earlier repeated-seed work was cancelled and retained as partial development evidence. The final result report is published alongside this document after completion.

Compare strategies within the same model. Do not compare legacy and staged execution as if changing physical assumptions improved the optimizer. Cases inspected during development are internal regression/validation evidence, not permanently untouched holdouts.

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
