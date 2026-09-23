-- Alternatives do not reserve resources. Only an acknowledged approval activates bookings.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE IF NOT EXISTS schedule_requests (
 id text PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 base_revision bigint NOT NULL, snapshot jsonb NOT NULL, horizon integer NOT NULL CHECK(horizon BETWEEN 30 AND 240),
 focus_commitment text NOT NULL, status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
 attempts integer NOT NULL DEFAULT 0, lease_until timestamptz, result jsonb, error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(run_id,focus_commitment) REFERENCES commitments(run_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS schedule_one_pending ON schedule_requests(run_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS schedule_plans (
 id text PRIMARY KEY, request_id text NOT NULL REFERENCES schedule_requests(id) ON DELETE CASCADE,
 run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE, base_revision bigint NOT NULL,
 status text NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','approved','executing','interrupted','completed','withdrawn','superseded')),
 candidate jsonb NOT NULL, end_minute integer NOT NULL, approved_command text REFERENCES commands(id),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(run_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS schedule_one_active ON schedule_plans(run_id) WHERE status IN ('approved','executing');
CREATE TABLE IF NOT EXISTS schedule_stages (
 plan_id text NOT NULL, run_id text NOT NULL, job_id text NOT NULL, ordinal integer NOT NULL CHECK(ordinal>=0),
 label text NOT NULL, start_minute integer NOT NULL, end_minute integer NOT NULL CHECK(end_minute>start_minute),
 PRIMARY KEY(plan_id,job_id,ordinal),
 FOREIGN KEY(run_id,plan_id) REFERENCES schedule_plans(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,job_id) REFERENCES move_jobs(run_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS equipment_reservations (
 plan_id text NOT NULL, run_id text NOT NULL, job_id text NOT NULL, equipment_id text NOT NULL,
 occupied int4range NOT NULL CHECK(NOT isempty(occupied) AND NOT lower_inf(occupied) AND NOT upper_inf(occupied)),
 active boolean NOT NULL DEFAULT true, PRIMARY KEY(plan_id,job_id,equipment_id),
 FOREIGN KEY(run_id,plan_id) REFERENCES schedule_plans(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,job_id) REFERENCES move_jobs(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,equipment_id) REFERENCES equipment(run_id,id) ON DELETE CASCADE,
 EXCLUDE USING gist(run_id WITH =,equipment_id WITH =,occupied WITH &&) WHERE(active)
);
CREATE INDEX IF NOT EXISTS schedule_request_history ON schedule_requests(run_id,created_at DESC);
INSERT INTO schema_version(version) VALUES(5) ON CONFLICT DO NOTHING;
-- Keep request ownership consistent even if a future adapter bypasses Python.
CREATE UNIQUE INDEX IF NOT EXISTS schedule_request_identity ON schedule_requests(run_id,id);
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='schedule_plan_request_run' AND conrelid='schedule_plans'::regclass) THEN
  ALTER TABLE schedule_plans ADD CONSTRAINT schedule_plan_request_run
   FOREIGN KEY(run_id,request_id) REFERENCES schedule_requests(run_id,id) ON DELETE CASCADE;
 END IF;
END $$;
