-- Intervals are recorded activity, NOT future bookings or predicted completions.
WITH work AS (
 SELECT j->>'id' AS job_id,j->>'container_id' AS container_id,equipment_id,
 (j->>'started_at')::int AS start_minute,
 coalesce((j->>'completed_at')::int,%(minute)s) AS end_minute,
 j->>'status' AS status
 FROM jsonb_array_elements(%(state)s::jsonb->'jobs') j
 CROSS JOIN LATERAL jsonb_array_elements_text(coalesce(j->'resources','[]')) equipment_id
 WHERE j->>'started_at' IS NOT NULL AND NOT (j ? 'stage_history')
 UNION ALL
 SELECT j->>'id',j->>'container_id',equipment_id,(h->>'start')::int,
 coalesce((h->>'end')::int,%(minute)s),j->>'status'
 FROM jsonb_array_elements(%(state)s::jsonb->'jobs') j
 CROSS JOIN LATERAL jsonb_array_elements(coalesce(j->'stage_history','[]')) h
 CROSS JOIN LATERAL jsonb_array_elements_text(h->'resources') equipment_id
), activity AS (
 SELECT *,lag(end_minute) OVER(PARTITION BY equipment_id ORDER BY start_minute,job_id) AS previous_end
 FROM work
)
SELECT e->>'id' AS equipment_id,e->>'status' AS status,e->>'job_id' AS active_job,
 coalesce((SELECT jsonb_agg(jsonb_build_object('start',a.start_minute,'end',a.end_minute,'job_id',a.job_id,
 'container_id',a.container_id,'status',a.status,'gap_before',CASE WHEN a.previous_end IS NULL THEN NULL ELSE a.start_minute-a.previous_end END)
 ORDER BY a.start_minute,a.job_id) FROM activity a WHERE a.equipment_id=e->>'id'),'[]') AS activity,
 coalesce((SELECT jsonb_agg(jsonb_build_object('start',(w->>'start_minute')::int,'end',(w->>'end_minute')::int,'source',w->>'source',
 'permits_dispatch',int4range((w->>'start_minute')::int,(w->>'end_minute')::int,'[)') @> %(minute)s::int)
 ORDER BY (w->>'start_minute')::int)
 FROM jsonb_array_elements(coalesce(%(state)s::jsonb->'availability','[]')) w WHERE w->>'equipment_id'=e->>'id'),'[]') AS windows
FROM jsonb_array_elements(%(state)s::jsonb->'equipment') e ORDER BY e->>'id';
