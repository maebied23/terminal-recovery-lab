-- A tick may release one load and acquire another on the same machine. Enforce
-- exclusivity at transaction end, avoiding row-upsert-order artifacts.
DROP INDEX one_load_per_equipment;
ALTER TABLE cargo_custody ADD CONSTRAINT one_load_per_equipment
 UNIQUE(run_id,equipment_id) DEFERRABLE INITIALLY DEFERRED;
