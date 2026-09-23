-- Additive: legacy snapshots/reservations retain their original model.
CREATE TABLE transport_nodes (
 run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE, id text NOT NULL,
 x double precision NOT NULL, y double precision NOT NULL,
 PRIMARY KEY(run_id,id)
);
CREATE TABLE transport_edges (
 run_id text NOT NULL, id text NOT NULL, source_id text NOT NULL, target_id text NOT NULL,
 metres double precision NOT NULL CHECK(metres>0), loaded_mpm double precision NOT NULL CHECK(loaded_mpm>0),
 empty_mpm double precision NOT NULL CHECK(empty_mpm>0), closed boolean NOT NULL,
 compatible jsonb NOT NULL, model_digest text NOT NULL,
 PRIMARY KEY(run_id,id),
 FOREIGN KEY(run_id,source_id) REFERENCES transport_nodes(run_id,id),
 FOREIGN KEY(run_id,target_id) REFERENCES transport_nodes(run_id,id)
);
CREATE INDEX transport_outgoing ON transport_edges(run_id,source_id);
CREATE TABLE stage_reservations (
 plan_id text NOT NULL, run_id text NOT NULL, job_id text NOT NULL, ordinal integer NOT NULL,
 equipment_id text NOT NULL, occupied int4range NOT NULL,
 active boolean NOT NULL DEFAULT true,
 PRIMARY KEY(plan_id,job_id,ordinal,equipment_id),
 FOREIGN KEY(plan_id,job_id,ordinal) REFERENCES schedule_stages(plan_id,job_id,ordinal) ON DELETE CASCADE,
 FOREIGN KEY(run_id,plan_id) REFERENCES schedule_plans(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,equipment_id) REFERENCES equipment(run_id,id) ON DELETE CASCADE,
 CHECK(NOT isempty(occupied) AND NOT lower_inf(occupied) AND NOT upper_inf(occupied)),
 EXCLUDE USING gist(run_id WITH =, equipment_id WITH =, occupied WITH &&) WHERE(active)
);
CREATE TABLE cargo_custody (
 run_id text NOT NULL, container_id text NOT NULL, location_id text, equipment_id text, job_id text,
 revision bigint NOT NULL,
 PRIMARY KEY(run_id,container_id),
 FOREIGN KEY(run_id,container_id) REFERENCES containers(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,location_id) REFERENCES locations(run_id,id),
 FOREIGN KEY(run_id,equipment_id) REFERENCES equipment(run_id,id),
 FOREIGN KEY(run_id,job_id) REFERENCES move_jobs(run_id,id),
 CHECK((location_id IS NOT NULL)::integer + (equipment_id IS NOT NULL)::integer = 1),
 CHECK(equipment_id IS NULL OR job_id IS NOT NULL)
);
CREATE UNIQUE INDEX one_load_per_equipment ON cargo_custody(run_id,equipment_id) WHERE equipment_id IS NOT NULL;
