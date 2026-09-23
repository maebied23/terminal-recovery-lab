# One decision, from inventory to outcome

This case uses the synthetic **Connected movement shift**. It demonstrates departure recovery across shared yard, transport and equipment constraints. Screenshots were captured from the application; the interruption example is a separate branch and follows Container 123, not Container 121.

## 1. Identify what prevents departure

A planner selects **North Rail → Container 121**. It is in A1, but Container 122 must move first. The required work is linked through a prerequisite edge, rather than inferred from similar names or merely drawn on the map.

![Numbered routes: first relocate Container 122, then retrieve Container 121](terminal-map.png)

**Read the map:** yellow route **1** is Container 122's instructed relocation from A1 to D4. Cyan route **2** is Container 121's outbound movement to North Rail. Stack counts provide location context. Dashed instructed routes are not evidence that either move has completed. D4 is the supplied instruction, not a destination the system has already proven optimal.

The decision is now concrete: can the obstruction be moved and the outbound container delivered before the cutoff, using equipment that other work also needs?

**Code and data:** `move_jobs` links containers to source/target locations; `job_dependencies` links the two jobs. [`sql/diagnosis_dependencies.sql`](../../sql/diagnosis_dependencies.sql) finds the prerequisite closure. [`app/diagnosis.py`](../../app/diagnosis.py) connects that scope to blockers, service obligations and input provenance.

## 2. Challenge the destination instruction

Open the relocation's destination comparison. An empty-looking slot alone is insufficient: incoming work may need it, placing cargo there may obstruct another departure, and the next retrieval may become more expensive.

SQL aggregates inventory, inbound demand and affected downstream work to shortlist locations. Candidate movement schedules then use route and equipment rules; physical replay checks whether they execute. Temporal SQL checks capacity across candidate pickup/arrival boundaries.

A planner can inspect alternatives and apply a supported instruction. This changes the relocation destination and the affected later pickup consistently. It does not move cargo or book machines. A revision guard rejects approval if the supporting state changed.

**Code:** [`sql/placement_candidates.sql`](../../sql/placement_candidates.sql), [`sql/placement_temporal.sql`](../../sql/placement_temporal.sql), [`app/placement.py`](../../app/placement.py), [`app/placement_store.py::approval`](../../app/placement_store.py).

## 3. Compare the whole schedule

Open **Compare & book**. Each strategy faces the same departure obligations; selecting North Rail in the interface does not justify hiding losses elsewhere.

![Baseline and two recovery strategies, with on-time cargo, lateness, changes and travel](schedule-comparison.png)

**Read the comparison:** in this captured reference case, baseline protects **16 of 24** outbound cargo; both alternatives protect **17**. Recovery also changes four assignments and increases modeled travel from **260 to 271 minutes**, while reducing modeled cargo-minutes beyond cutoff. The extra protected cargo is therefore a tradeoff, not a free improvement.

These are modeled totals across the terminal, not 24 containers on the selected train. Inspect the per-departure impact and equipment lanes before approving. A constraint solver's name is not evidence that its option is better: the published calendar case loses to baseline.

**Code:** [`app/scheduling.py`](../../app/scheduling.py) and [`app/stage_planning.py`](../../app/stage_planning.py) generate/check alternatives; [`app/schedule_store.py::approval`](../../app/schedule_store.py) validates and books the selected plan. The bounded option pool and independent replay are explained in [design decisions](decisions.md).

## 4. Distinguish bookings from execution

After approval, advance the simulated clock in **Execution**. Equipment lanes show reserved intervals. Actual stages show empty tractor repositioning, pickup, loaded transfer and setdown. An equipment booking is a future claim; the current holder is a physical fact within the simulation.

This distinction becomes visible in the separate receiver-failure branch:

![Container 123 remains on Terminal tractor 1 after Yard crane 1 becomes unavailable](interrupted-custody.png)

**Read the interruption:** Container 123 is held by **Terminal tractor 1**. Its intended destination is **North Rail**, but it has not arrived. **Yard crane 1** cannot receive it. The displayed stage times describe the original plan; they are not a promise of completion after the failure.

The accepted equipment observation interrupts the active plan and releases future bookings while retaining cargo custody. Repair alone does not approve or restart the old plan. Unknown completion of in-progress work can correctly prevent a new comparison from claiming a feasible result.

**Code:** [`app/integration.py::receive`](../../app/integration.py), [`app/schedule_execution.py::interrupt`](../../app/schedule_execution.py), [`app/move_execution.py`](../../app/move_execution.py), migrations [008](../../migrations/008_movement.sql) and [009](../../migrations/009_custody_commit.sql).

## 5. Inspect evidence and judge the outcome

The equipment receipt ledger distinguishes delivered, applied, duplicate, stale and quarantined observations. A repeated event does not perform the failure twice. Historical revisions preserve what the system knew; commands and execution events show what was requested and what happened.

Evaluation answers a different question: across the authored cases, did the strategies help? The connected suite contains eight families and three strategies. Each alternative had four wins, three ties and one loss. Disrupted plans remained interrupted. Those results do not establish real-terminal savings.

The read-only assistant can help retrieve supported evidence; it does not replace this chain with an unverified explanation or approve an action. See [validation](validation.md) and [the integration contract](integration.md).

## Reproduce the case

Follow [local setup](../../README.md#run-locally), then [the click-by-click walkthrough](walkthrough.md). Start with a fresh Connected movement shift and leave it paused while investigating. For the independent sender failure branch, use the scoped configuration and rehearsal script in [equipment integration](integration.md).

No installation is required to inspect the screenshots, SQL, source and published evaluation evidence above. The repository does not currently provide a hosted application.
