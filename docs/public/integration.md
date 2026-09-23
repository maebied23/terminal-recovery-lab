# Equipment observation integration

The optional adapter is an independent **synthetic equipment feed**, not a TOS connector. It changes equipment availability in the same PostgreSQL-backed operational model used by scheduling and the interface.

## Start

Import a dataset in Scenario lab. Copy the run ID from the URL. Generate a local secret (for example, Python's `secrets.token_urlsafe(32)`), then export `TERMINAL_FEED_TOKEN` and `TERMINAL_FEED_RUN` before starting the API. The default source is `fleet`; `TERMINAL_FEED_SOURCE` can narrow the configured source. No token belongs in browser code or a committed file.

Create an ignored local event file:

```json
{
  "schema_version": 1,
  "source": "fleet",
  "event_id": "equipment-example-1",
  "external_id": "crane-west-1",
  "kind": "equipment.status",
  "observed_at": "2026-09-20T08:00:00Z",
  "sequence": 1,
  "value": "failed"
}
```

Use the shift's timestamp, not today's wall clock. `observed_at` must be within the imported shift and no later than its current simulated minute. This deliberately connects a synthetic sender to a simulated clock.

```bash
python3 scripts/send_equipment.py --run YOUR_RUN_ID --event .local/event.json
```

## Contract

`POST /api/integrations/equipment?run=...` requires a bearer token scoped to one run/source. Only equipment status is accepted; no arbitrary object patches. Payloads are limited to 64 KiB. Unknown identities, stale facts and event conflicts cannot overwrite authoritative state.

One transaction locks the run, writes the receipt, reconciles authoritative identity/time/sequence, saves the new revision and historical events, then commits before acknowledging. The response distinguishes durable delivery from `applied`, `duplicate`, `stale` or `quarantined` application status. Structural validation/authentication failures return HTTP errors before entering the operational ledger.

Exact retries retain a receipt but do not repeat the equipment change. A conflicting event ID is quarantined. A server failure before commit rolls back both receipt and state; retry the same event ID. A lost response after commit is safe to redeliver. This is at-least-once transport with deduplicated effects, not an exactly-once network guarantee.

Accepted observations invalidate active schedules immediately, pause automatic execution and release future reservations through the existing schedule persistence mechanism. Actual cargo custody remains intact. No automatic replan or crane control occurs.

## Inspect

Inputs shows receipt counts and last wall-clock receipt time. Equipment evidence links accepted observations to affected jobs and departures through `sql/input_impact.sql`. That query includes current assignments, in-flight assigned resources and active stage bookings, then follows prerequisite edges recursively.

Receipt silence does not mean equipment failed. The sender is request-driven; no heartbeat or guaranteed live connection is claimed. Older `/api/inputs` rehearsal records remain a separate, non-applying legacy interface.
