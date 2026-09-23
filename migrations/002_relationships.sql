-- Additive migration. Historical snapshots remain untouched.
ALTER TABLE job_dependencies ADD COLUMN IF NOT EXISTS details jsonb NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS dependency_successors ON job_dependencies(run_id,predecessor_id);
CREATE INDEX IF NOT EXISTS jobs_container ON move_jobs(run_id,container_id);
CREATE INDEX IF NOT EXISTS jobs_source ON move_jobs(run_id,source_id);
CREATE INDEX IF NOT EXISTS jobs_target ON move_jobs(run_id,target_id);
-- Physical identity is scoped to the fictional run; visits are separate records.
CREATE TABLE IF NOT EXISTS cargo_visits(
 run_id text, id text, container_id text NOT NULL, commitment_id text,
 PRIMARY KEY(run_id,id), FOREIGN KEY(run_id,container_id) REFERENCES containers(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,commitment_id) REFERENCES commitments(run_id,id));
INSERT INTO cargo_visits SELECT run_id,visit_id,id,commitment_id FROM containers ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS input_events(
 id bigserial PRIMARY KEY, run_id text REFERENCES runs(id) ON DELETE CASCADE,
 source text NOT NULL, source_event_id text NOT NULL, event_time integer NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('accepted','quarantined')), reason text,
 UNIQUE(run_id,source,source_event_id));
INSERT INTO schema_version(version) VALUES(2) ON CONFLICT DO NOTHING;
