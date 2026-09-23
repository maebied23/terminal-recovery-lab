-- Which active work and commitments depend on the selected entity?
-- UNION (not UNION ALL) deduplicates converging paths and terminates cycles.
-- This is exposure through actual assignments/use and precedence, not risk probability.
WITH RECURSIVE affected(id) AS (
 SELECT id FROM move_jobs
 WHERE run_id=%(run)s AND status<>'completed' AND (
  id=%(entity)s OR container_id=%(entity)s OR equipment_id=%(entity)s
  OR source_id=%(entity)s OR target_id=%(entity)s
  OR attributes->'resources' ? %(entity)s
  OR (status='running' AND attributes->'assigned_resources' ? %(entity)s)
  OR EXISTS (SELECT 1 FROM stage_reservations r WHERE r.run_id=move_jobs.run_id
    AND r.job_id=move_jobs.id AND r.equipment_id=%(entity)s AND r.active))
 UNION
 SELECT d.job_id FROM job_dependencies d JOIN affected a ON d.predecessor_id=a.id
 JOIN move_jobs j ON (j.run_id,j.id)=(d.run_id,d.job_id)
 WHERE d.run_id=%(run)s AND j.status<>'completed'
)
SELECT co.id AS commitment_id, co.cutoff,
 count(DISTINCT v.id)::int AS cargo_visits,
 count(DISTINCT j.id)::int AS moves,
 jsonb_agg(DISTINCT jsonb_build_object('job_id',j.id,'container_id',j.container_id,
  'visit_id',j.visit_id,'source_id',j.source_id,'target_id',j.target_id)) AS work
FROM affected a JOIN move_jobs j ON j.id=a.id AND j.run_id=%(run)s
JOIN cargo_visits v ON (v.run_id,v.id,v.container_id)=(j.run_id,j.visit_id,j.container_id)
JOIN commitments co ON (co.run_id,co.id)=(v.run_id,v.commitment_id)
GROUP BY co.id,co.cutoff ORDER BY co.cutoff,co.id;
