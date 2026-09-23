-- Immutable comparison evidence; approval is a separate outbox command.
CREATE TABLE placement_proposals (
 id text PRIMARY KEY,
 run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 job_id text NOT NULL,
 base_revision bigint NOT NULL,
 snapshot jsonb NOT NULL,
 result jsonb NOT NULL,
 approved_command text REFERENCES commands(id) ON DELETE SET NULL,
 approved_destination text,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(run_id,job_id) REFERENCES move_jobs(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,approved_destination) REFERENCES locations(run_id,id)
);
CREATE INDEX placement_history ON placement_proposals(run_id,job_id,created_at DESC);
INSERT INTO schema_version(version) VALUES(7);
