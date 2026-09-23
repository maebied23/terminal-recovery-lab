-- Which obligations depend on work booked on a failed resource?
-- Seed with ALL reserved roles (not just a job's primary assignment), then walk
-- dependent work across cargo visits. UNION deduplicates converging paths.
WITH RECURSIVE all_bookings AS (
 SELECT plan_id,run_id,job_id,equipment_id FROM equipment_reservations
 UNION ALL SELECT plan_id,run_id,job_id,equipment_id FROM stage_reservations
), affected(job_id) AS (
 SELECT r.job_id FROM all_bookings r
 WHERE r.run_id=%(run)s AND r.plan_id=%(plan)s AND r.equipment_id=%(equipment)s
 UNION
 SELECT d.job_id FROM job_dependencies d JOIN affected a ON a.job_id=d.predecessor_id
 WHERE d.run_id=%(run)s
)
SELECT v.id AS visit_id,v.container_id,v.commitment_id,co.cutoff,
       array_agg(j.id ORDER BY j.id) AS affected_work,
       bool_or(j.status='running') AS handling_underway,
       bool_or(j.status='queued') AS unfinished_work
FROM affected a JOIN move_jobs j ON j.run_id=%(run)s AND j.id=a.job_id
JOIN cargo_visits v ON (v.run_id,v.id)=(j.run_id,j.visit_id)
LEFT JOIN commitments co ON (co.run_id,co.id)=(v.run_id,v.commitment_id)
GROUP BY v.id,v.container_id,v.commitment_id,co.cutoff
ORDER BY co.cutoff NULLS LAST,v.container_id;
