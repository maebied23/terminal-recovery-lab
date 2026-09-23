-- External receipts share the authoritative feed ledger; distinguish transport provenance.
ALTER TABLE feed_receipts ADD COLUMN received_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE feed_receipts ADD COLUMN transport text NOT NULL DEFAULT 'dataset'
 CHECK(transport IN ('dataset','equipment-adapter'));
CREATE INDEX feed_transport_recent ON feed_receipts(run_id,transport,received_at DESC);
ALTER TABLE evaluation_runs DROP CONSTRAINT evaluation_runs_suite_check;
ALTER TABLE evaluation_runs ADD CONSTRAINT evaluation_runs_suite_check
 CHECK(suite IN ('development','holdout','case','movement'));
INSERT INTO schema_version(version) VALUES(11) ON CONFLICT DO NOTHING;
