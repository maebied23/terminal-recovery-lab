CREATE TABLE IF NOT EXISTS evaluation_runs (
 id text PRIMARY KEY,run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 base_revision bigint NOT NULL, source_request text, suite text NOT NULL CHECK(suite IN ('development','holdout','case')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','cancelled','failed')),
 manifest jsonb NOT NULL, error text,created_at timestamptz NOT NULL DEFAULT now(),completed_at timestamptz,
 UNIQUE(run_id,id),FOREIGN KEY(run_id,source_request) REFERENCES schedule_requests(run_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS evaluation_one_pending ON evaluation_runs(run_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS evaluation_cases (
 evaluation_id text NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,case_id text NOT NULL,
 ordinal integer NOT NULL,scenario jsonb NOT NULL,snapshot jsonb NOT NULL,comparison jsonb,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
 attempts integer NOT NULL DEFAULT 0,lease_until timestamptz,result jsonb,error text,
 PRIMARY KEY(evaluation_id,case_id)
);
CREATE TABLE IF NOT EXISTS evaluation_trials (
 evaluation_id text NOT NULL,case_id text NOT NULL,seed integer NOT NULL,strategy text NOT NULL CHECK(strategy IN ('baseline','deadline','constraint')),
 validation text NOT NULL,execution_status text NOT NULL,metrics jsonb,predicted jsonb,
 changed_bookings integer NOT NULL DEFAULT 0,stream_digest text,details jsonb NOT NULL,
 PRIMARY KEY(evaluation_id,case_id,seed,strategy),
 FOREIGN KEY(evaluation_id,case_id) REFERENCES evaluation_cases(evaluation_id,case_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS evaluation_visit_outcomes (
 evaluation_id text NOT NULL,case_id text NOT NULL,seed integer NOT NULL,strategy text NOT NULL,
 visit_id text NOT NULL,container_id text NOT NULL,commitment_id text NOT NULL,cutoff integer NOT NULL,
 completion integer,on_time boolean NOT NULL,lateness integer NOT NULL CHECK(lateness>=0),
 PRIMARY KEY(evaluation_id,case_id,seed,strategy,visit_id),
 FOREIGN KEY(evaluation_id,case_id,seed,strategy) REFERENCES evaluation_trials(evaluation_id,case_id,seed,strategy) ON DELETE CASCADE
);
-- Evaluation visits belong to frozen scenario snapshots, NOT mutable live-run visits.
CREATE INDEX IF NOT EXISTS evaluation_history ON evaluation_runs(run_id,created_at DESC);
CREATE TABLE IF NOT EXISTS assistant_traces (
 id text PRIMARY KEY,run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 revision bigint NOT NULL,mode text NOT NULL,question text NOT NULL,answer jsonb NOT NULL,
 elapsed_ms integer NOT NULL,usage jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assistant_trace_history ON assistant_traces(run_id,created_at DESC);
INSERT INTO schema_version(version) VALUES(6) ON CONFLICT DO NOTHING;
