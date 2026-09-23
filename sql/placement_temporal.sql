-- Grain: candidate/location/time boundary. Never multiply cargo by equipment rows.
-- Planning-only profile: a pickup creates conditional capacity, never an observed vacancy.
WITH rows AS (
 SELECT value AS r FROM jsonb_array_elements(%(rows)s::jsonb)
), moves AS (
 SELECT r->>'job_id' job_id, r->>'source_id' source_id, r->>'target_id' target_id,
 (r->>'end')::int arrival,
 (SELECT min((p->>'start')::int) FROM jsonb_array_elements(r->'stages') p
  WHERE p->>'kind'='pickup') pickup
 FROM rows
), deltas AS (
 SELECT l.id location_id, %(minute)s::int at_minute, count(c.id)::bigint delta
 FROM locations l LEFT JOIN containers c ON c.run_id=l.run_id AND c.location_id=l.id
 WHERE l.run_id=%(run)s AND l.kind='yard' GROUP BY l.id
 UNION ALL SELECT source_id,pickup,-1 FROM moves WHERE pickup IS NOT NULL AND pickup>%(minute)s
 UNION ALL SELECT target_id,arrival,1 FROM moves
), boundaries AS (
 SELECT location_id,at_minute,sum(delta) delta FROM deltas GROUP BY location_id,at_minute
), profile AS (
 SELECT location_id,at_minute,
 lead(at_minute,1,%(horizon)s::int) OVER(PARTITION BY location_id ORDER BY at_minute) until_minute,
 sum(delta) OVER(PARTITION BY location_id ORDER BY at_minute ROWS UNBOUNDED PRECEDING) occupied
 FROM boundaries
)
SELECT p.*,l.capacity,l.capacity-p.occupied free_slots
FROM profile p JOIN locations l ON l.run_id=%(run)s AND l.id=p.location_id
WHERE l.kind='yard' AND p.at_minute<%(horizon)s
ORDER BY p.location_id,p.at_minute;
