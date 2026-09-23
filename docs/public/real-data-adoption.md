# Moving from synthetic data to operational validation

Northstar demonstrates an implemented decision loop, not proven performance at a real terminal. Connecting a feed and establishing useful recommendations are separate tasks. The starting point is a terminal shift planner's authority and workflow: who chooses a relocation, who books equipment, and who confirms that work actually happened?

## Establish the decision boundary

Select one departure-recovery workflow with the operator. Document the current dispatch practice, exceptions and approval owner. Identify competing services that could be harmed by prioritizing the selected departure. The operating organization that owns those decisions may differ from the port authority, carrier or party paying delay costs; validate ownership rather than assuming a buyer.

## Minimum useful data

| Source records | Required meaning | Why it matters |
|---|---|---|
| Inventory and movement history | Container/visit identity, location, stack order, timestamps | Reconstruct access and actual movement |
| Work orders | Pickup, target, status, assignments and completion | Compare instructions with execution |
| Departure obligations | Cutoffs, service windows, release requirements | Define success consistently |
| Equipment and calendars | Capabilities, availability, outages and actual use | Check executable assignments |
| Yard and route rules | Capacity, reach, restrictions, handling and travel behavior | Replace authored physical assumptions |

External identifiers must map to stable internal objects. Agree on timezones, observation versus receipt time, corrections, source ownership and missing-data handling. Vessel position data alone cannot supply yard inventory, cargo release or equipment dispatch facts.

The delivered equipment endpoint is narrow and tied to a simulated shift clock. A real connector would need an agreed provider contract, identity mapping, wall-clock semantics, freshness policy and reconciliation against authoritative operations. Physical writeback would additionally require command acknowledgment, rejection handling and authority controls. Those are not delivered integrations.

## Validate in stages

1. **Historical reconstruction:** ingest anonymized records and reconcile inventory, jobs and completions. Investigate missing identities and contradictions before producing recommendations.
2. **Replay:** use only facts available at each historical decision time. Later corrections must not leak into earlier recommendations. Compare modeled execution against observed durations and constraints.
3. **Shadow recommendations:** let planners judge alternatives alongside normal operations, without dispatching them. Record unsupported assumptions, rejected advice and reasons.
4. **Supervised actions:** only after agreed acceptance gates, authorize a narrow writeback with traceable approval and external acknowledgment.

These are acceptance stages, not a promised pilot duration. Data access and operational review determine the schedule.

## Define success and stopping conditions

Measure unique visits served before cutoff, unserved cargo, lateness, rehandles, loaded/empty travel and harm to other departures. Also measure operational safety violations, data reconciliation failures, recommendation latency and whether planners can explain and execute a proposal.

Agree thresholds with the operator before judging results. Stop progression when inventory cannot be reconciled, a critical constraint is missing, recommendations violate practice, or required authorization is unclear. A favorable average does not compensate for unsafe or consistently harmful exceptions.

The current eight-family synthetic evaluation is internal evidence. A real study needs representative shifts and evaluation data kept separate from tuning. Historical comparison alone does not establish causality: dispatch choices and workload conditions can differ.

## Value without invented ROI

Use validated changes in service outcomes and customer-provided marginal costs. Identify who incurs each cost, account for implementation/operating effort, and avoid charging the same missed departure consequence to every linked delay metric. Present a range and assumptions before claiming savings.

The published reference case's 16 → 17 on-time cargo is a synthetic result. It is not a measured recovery rate or a monetary benefit. The handling-calendar loss is equally relevant to deciding where the approach is useful.

For technical delivery and recovery procedures, see [deployment](deployment.md). Hosting the synthetic workbench can make review easier; it does not validate terminal performance.
