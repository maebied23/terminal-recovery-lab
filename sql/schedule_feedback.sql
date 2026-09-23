-- One row per approved move, not one row per equipment booking. Aggregate first
-- to avoid duplicating cargo / completion outcomes across synchronized resources.
WITH all_bookings AS (
 SELECT plan_id,run_id,job_id,equipment_id,occupied,active FROM equipment_reservations
 UNION ALL SELECT plan_id,run_id,job_id,equipment_id,occupied,active FROM stage_reservations
), bookings AS (
 SELECT plan_id,run_id,job_id,min(lower(occupied)) AS planned_start,
        max(upper(occupied)) AS reserved_until,
        array_agg(DISTINCT equipment_id ORDER BY equipment_id) AS resources,bool_or(active) AS active
 FROM all_bookings WHERE run_id=%(run)s GROUP BY plan_id,run_id,job_id
), stages AS (
 SELECT plan_id,job_id,max(end_minute) AS planned_end
 FROM schedule_stages WHERE run_id=%(run)s GROUP BY plan_id,job_id
)
SELECT p.id AS plan_id,p.status AS plan_status,p.base_revision,p.approved_command,
       head.revision AS observed_revision,
       b.job_id,j.container_id,j.visit_id,v.commitment_id,j.status AS execution_status,
       b.planned_start,st.planned_end,b.reserved_until,b.resources,b.active,
       (j.attributes->>'started_at')::integer AS actual_start,
       (j.attributes->>'completed_at')::integer AS actual_end,
       (j.attributes->>'completed_at')::integer-st.planned_end AS completion_variance,
       co.cutoff,
       j.target_id=co.location_id AND j.attributes->>'kind'<>'rehandle' AS final_delivery,
       CASE WHEN j.status='completed' AND j.target_id=co.location_id AND j.attributes->>'kind'<>'rehandle'
            THEN (j.attributes->>'completed_at')::integer<=co.cutoff END AS final_delivery_by_cutoff
FROM bookings b JOIN runs head ON head.id=b.run_id
JOIN schedule_plans p ON (p.run_id,p.id)=(b.run_id,b.plan_id)
JOIN move_jobs j ON (j.run_id,j.id)=(b.run_id,b.job_id)
JOIN cargo_visits v ON (v.run_id,v.id)=(j.run_id,j.visit_id)
LEFT JOIN commitments co ON (co.run_id,co.id)=(v.run_id,v.commitment_id)
JOIN stages st ON (st.plan_id,st.job_id)=(b.plan_id,b.job_id)
ORDER BY p.created_at DESC,b.planned_start,b.job_id;
