# Versioned operational input packs

The sixth pack is **`movement-shift` / Connected movement shift**. It uses the same base identities plus a checksummed `movement.json`: directed metric roads, explicit loaded/empty rates, handling profiles and tractor starting nodes. Import it as a new shift; the five original packs below remain unchanged. See [movement inputs and behavior](../docs/public/architecture.md) and [data dictionary](../docs/public/architecture.md). Road lengths/rates are authored synthetic assumptions, not measurements. `python -m scripts.dataset seal movement-shift` explicitly reseals edits; `scripts/generate_movement_pack.py` is an offline authoring helper that overwrites that pack and is never called at startup.

These are **synthetic, inspectable inputs**, generated offline in Python and imported into PostgreSQL. They are not real terminal records or independently collected training/evaluation data. Simulation still executes work; its starting facts now come from files rather than a runtime call to `seed_state`.

Start with the [application guide](../README.md).

## The five packs

| Directory | Change from baseline | What it tests |
|---|---|---|
| `baseline-shift` | None | Exact compatibility with the existing operational starting state: 144 containers and 37 moves |
| `normal-shift` | Cover cargo begins in A2; known access move removed; held cargo released | Whether improved access and release actually change feasibility |
| `equipment-outage` | Fleet reports Yard crane 1 failed at 08:10, repaired at 08:25 | Delivered observations affecting availability and work |
| `imperfect-information` | Eight deliveries: outage, duplicate, stale status, conflict, unknown identity, corrected position, invalid position, release | Reconciliation and knowledge available at a revision |
| `impossible-cutoff` | North Rail cutoff is 08:01; associated delivery deadlines follow | Honest failure under an infeasible deadline |

The baseline is not an ideal unconstrained shift. It intentionally contains the original covering-container prerequisite and hold. `normal-shift` removes those two known issues; it does not promise every departure succeeds.

## Files and relationships

All packs reference these shared baseline CSVs; variations live in each pack's `changes.json`. This prevents five slightly divergent copies of the same identities.

| CSV | Identity / important references | Operational meaning |
|---|---|---|
| `locations.csv` | `id`, kind, zone, capacity | Where work can happen; the current model treats each yard location as one vertical stack |
| `equipment.csv` | `id`, kind, zone, initial status | Handling capability, reach and starting availability |
| `containers.csv` | `id`, weight in tonnes | The physical asset |
| `visits.csv` | `id`, `container_id`, optional `commitment_id` | Why this cargo is here, its flow and release status |
| `inventory.csv` | One `container_id`, `location_id`, tier, source, observed time | Where the asset is believed to be at shift start |
| `commitments.csv` | `id`, `location_id`, arrival, cutoff, capacity | The service destination and obligation driving the decision |
| `work_orders.csv` | `id`, `container_id`, `visit_id`, source/target/equipment IDs | Planned work; durations and travel assumptions remain synthetic |
| `dependencies.csv` | `job_id`, `predecessor_id`, reason, kind, origin | Directed prerequisites and their explanation |
| `equipment_availability.csv` | `equipment_id`, start/end minute, source | Dispatch-permitted windows; **not equipment bookings** |
| `identities.csv` | `(source, external_id)` → internal entity | How an external system's identifier is resolved without guessing |

`manifest.json` declares schema version, generator, seed, units, UTC shift origin, source authority and SHA-256 file hashes. `events.jsonl` holds delivery envelopes. The importer retains original CSV row numbers and variations in PostgreSQL, alongside the exact manifest/digest used for that run.

The CSV tier is zero-based; the UI displays human-readable levels starting at one. Times in tabular plans are whole minutes from **08:00 UTC**. Event timestamps require a timezone. Availability uses `[start,end)`: minute 240 is outside a 0–240 window. An already-running lift can finish after the window; the window only restricts new dispatch.

## Validate or change an input

From the project directory:

```bash
.venv/bin/python -m scripts.dataset validate imperfect-information
```

To author a variation, edit that pack's `changes.json` or `events.jsonl`, then explicitly seal and validate it:

```bash
.venv/bin/python -m scripts.dataset seal imperfect-information
```

Refresh Scenario lab to preview and import the new version as a **new paused shift**. Existing runs retain their original inputs. A checksum mismatch prevents silent changes; a pack changed after preview must be reviewed again. Failed sealing restores the previous manifest, but leaves your edited input file available to correct.

Changes may update inventory, visits, work orders or commitments. Removing a work order removes its dependency edges. Identity changes are forbidden. This is a bounded authoring contract, not an arbitrary file upload tool. Editing a shared baseline CSV requires resealing every pack that references it. Prefer pack-local variations for experiments.

`scripts/generate_datasets.py` regenerates the supplied fixtures from the existing seed. **Running it overwrites manual dataset edits.** It is an authoring helper, not part of application startup or import. New pack IDs require registration in `app/datasets.py::PACKS`.

## Delivery and correction example

In the imperfect-information pack, the fleet's `crane-west-1` maps to Yard crane 1. A failure observed at 08:02 applies at 08:02. Its duplicate at 08:03 does not apply again. An older availability observation at 08:04 cannot restore the crane. Reusing the failure ID with different content is quarantined.

At 08:05, inventory reports that Container 122 was observed at **Yard A, stack 2, level 6** at 08:03. It was previously believed to cover Container 121 in A1. The correction changes position, retains both clocks and preserves the old snapshot. It does not complete or rewrite MV-013, the existing plan to relocate that container. A subsequent correction into an occupied tier is quarantined.

Individual position corrections require accessible top cargo and a valid top destination. Buried-cargo corrections need a coherent stack reconciliation, which is not implemented. Unknown identifiers remain quarantined; there is no automatic fuzzy matching.

The planner never receives future envelope contents through its state snapshot. The input inspection UI does disclose the synthetic scenario description and the number of scheduled deliveries; it is not a blinded evaluation interface.
