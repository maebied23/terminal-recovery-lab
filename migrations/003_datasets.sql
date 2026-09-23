-- Typed relationships, immutable input provenance and a receipt/application ledger.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE UNIQUE INDEX IF NOT EXISTS visit_identity_container ON cargo_visits(run_id,id,container_id);
ALTER TABLE move_jobs ADD COLUMN IF NOT EXISTS visit_id text;
UPDATE move_jobs j SET visit_id=c.visit_id FROM containers c
 WHERE j.run_id=c.run_id AND j.container_id=c.id AND j.visit_id IS NULL;
ALTER TABLE move_jobs ALTER COLUMN visit_id SET NOT NULL;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='job_visit_identity') THEN
  ALTER TABLE move_jobs ADD CONSTRAINT job_visit_identity
   FOREIGN KEY(run_id,visit_id,container_id) REFERENCES cargo_visits(run_id,id,container_id)
   DEFERRABLE INITIALLY DEFERRED;
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS jobs_visit ON move_jobs(run_id,visit_id);

CREATE TABLE IF NOT EXISTS dataset_imports(
 run_id text PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
 pack_id text NOT NULL, digest text NOT NULL, manifest jsonb NOT NULL,
 validation jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dataset_rows(
 run_id text REFERENCES dataset_imports(run_id) ON DELETE CASCADE,
 file_name text, row_number integer CHECK(row_number>0), raw jsonb NOT NULL,
 PRIMARY KEY(run_id,file_name,row_number));
CREATE TABLE IF NOT EXISTS equipment_windows(
 run_id text, equipment_id text, availability_span int4range NOT NULL,
 source text NOT NULL,
 FOREIGN KEY(run_id,equipment_id) REFERENCES equipment(run_id,id) ON DELETE CASCADE,
 CHECK(NOT isempty(availability_span) AND lower(availability_span)>=0 AND NOT upper_inf(availability_span)),
 EXCLUDE USING gist(run_id WITH =,equipment_id WITH =,availability_span WITH &&));

-- A source may deliver an event more than once, even with conflicting content.
-- Receipts retain each attempt. Canonical events deduplicate source/event IDs.
CREATE TABLE IF NOT EXISTS feed_receipts(
 id bigserial PRIMARY KEY, run_id text REFERENCES runs(id) ON DELETE CASCADE,
 ordinal integer NOT NULL, receive_minute integer NOT NULL CHECK(receive_minute>=0),
 envelope jsonb NOT NULL, status text NOT NULL DEFAULT 'pending'
 CHECK(status IN ('pending','applied','stale','duplicate','quarantined')),
 reason text, entity_id text, field text, observed_minute integer,
 applied_revision bigint, before_value jsonb, after_value jsonb,
 recorded_at timestamptz, UNIQUE(run_id,ordinal));
CREATE INDEX IF NOT EXISTS due_feed_receipts ON feed_receipts(run_id,receive_minute,ordinal) WHERE status='pending';
CREATE INDEX IF NOT EXISTS receipt_evidence ON feed_receipts(run_id,entity_id,applied_revision DESC);
CREATE TABLE IF NOT EXISTS feed_events(
 run_id text REFERENCES runs(id) ON DELETE CASCADE, source text, event_id text,
 canonical jsonb NOT NULL, first_receipt bigint REFERENCES feed_receipts(id) ON DELETE CASCADE,
 PRIMARY KEY(run_id,source,event_id));
CREATE TABLE IF NOT EXISTS source_identities(
 run_id text REFERENCES runs(id) ON DELETE CASCADE, source text, external_id text,
 kind text CHECK(kind IN ('equipment','container')), entity_id text NOT NULL,
 PRIMARY KEY(run_id,source,external_id));

-- One immutable decision revision is used by an entire read request.
-- Window function shows delivery lag without collapsing individual evidence rows.
CREATE OR REPLACE VIEW feed_evidence AS
 SELECT r.*,receive_minute-observed_minute AS delivery_lag_minutes,
 lag(after_value) OVER(PARTITION BY run_id,entity_id,field ORDER BY applied_revision,id) AS prior_received_value
 FROM feed_receipts r WHERE status<>'pending';
INSERT INTO schema_version(version) VALUES(3) ON CONFLICT DO NOTHING;
