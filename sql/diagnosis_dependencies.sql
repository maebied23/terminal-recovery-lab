-- Current typed relationships or the exact historical revision, never a mixture.
-- The UNION closure is keyed by root job + ancestor: diamonds do not multiply cargo.
WITH RECURSIVE
jobs AS MATERIALIZED (
 SELECT id,container_id,visit_id,source_id,target_id,equipment_id,status,attributes
 FROM move_jobs WHERE run_id=%(run)s AND %(current)s
 UNION ALL
 SELECT j->>'id',j->>'container_id',coalesce(j->>'visit_id',c->>'visit_id'),
 j->>'source_id',j->>'target_id',j->>'equipment_id',j->>'status',j
 FROM jsonb_array_elements(%(state)s::jsonb->'jobs') j
 JOIN jsonb_array_elements(%(state)s::jsonb->'containers') c ON c->>'id'=j->>'container_id'
 WHERE NOT %(current)s
), visits AS MATERIALIZED (
 SELECT id,container_id,commitment_id FROM cargo_visits WHERE run_id=%(run)s AND %(current)s
 UNION ALL
 SELECT c->>'visit_id',c->>'id',c->>'commitment_id'
 FROM jsonb_array_elements(%(state)s::jsonb->'containers') c WHERE NOT %(current)s
), deps AS MATERIALIZED (
 SELECT job_id,predecessor_id,details FROM job_dependencies WHERE run_id=%(run)s AND %(current)s
 UNION ALL
 SELECT j->>'id',d,coalesce(j->'dependency_details'->d,'{}'::jsonb)
 FROM jsonb_array_elements(%(state)s::jsonb->'jobs') j
 CROSS JOIN LATERAL jsonb_array_elements_text(j->'dependencies') d WHERE NOT %(current)s
), walk(root_id,id) AS (
 SELECT id,id FROM jobs
 UNION
 SELECT w.root_id,d.predecessor_id FROM walk w JOIN deps d ON d.job_id=w.id
), finals AS (
 SELECT v.id AS visit_id,j.id FROM visits v
 JOIN jsonb_array_elements(%(state)s::jsonb->'commitments') co ON co->>'id'=v.commitment_id
 JOIN jobs j ON j.visit_id=v.id AND j.container_id=v.container_id AND j.target_id=co->>'location_id'
 WHERE j.attributes->>'kind'<>'rehandle'
), membership AS (
 SELECT DISTINCT f.visit_id,w.id FROM finals f JOIN walk w ON w.root_id=f.id
)
SELECT v.id AS visit_id,v.container_id,v.commitment_id,
 ARRAY(SELECT id FROM finals WHERE visit_id=v.id ORDER BY id) AS final_ids,
 ARRAY(SELECT id FROM membership WHERE visit_id=v.id ORDER BY id) AS job_ids,
 coalesce((SELECT jsonb_agg(jsonb_build_object('job_id',d.job_id,'predecessor_id',d.predecessor_id,'details',d.details) ORDER BY d.job_id,d.predecessor_id)
 FROM deps d WHERE d.job_id IN(SELECT id FROM membership WHERE visit_id=v.id)), '[]') AS edges,
 coalesce((SELECT jsonb_agg(jsonb_build_object('job_id',j.id,'container_id',j.container_id,'planned_pickup',j.source_id,'observed_position',c->>'location_id') ORDER BY j.id)
 FROM membership m JOIN jobs j ON j.id=m.id
 JOIN jsonb_array_elements(%(state)s::jsonb->'containers') c ON c->>'id'=j.container_id
 WHERE m.visit_id=v.id AND j.status='queued' AND c->>'location_id' IS DISTINCT FROM j.source_id
 AND NOT EXISTS(SELECT 1 FROM walk w JOIN jobs p ON p.id=w.id WHERE w.root_id=j.id AND w.id<>j.id
  AND p.container_id=j.container_id AND p.target_id=j.source_id AND p.status<>'completed')), '[]') AS mismatches
FROM visits v WHERE v.commitment_id IS NOT NULL ORDER BY v.commitment_id,v.id;
