-- One row per destination, at the locked run revision. No cargo/resource fan-out.
-- UNION deduplicates converging dependency paths and terminates cycles.
WITH RECURSIVE root AS (
 SELECT * FROM move_jobs WHERE run_id=%(run)s AND id=%(job)s
), affected(id) AS (
 SELECT id FROM root
 UNION
 SELECT d.job_id FROM job_dependencies d JOIN affected a ON a.id=d.predecessor_id
 WHERE d.run_id=%(run)s
), facts AS (
 SELECT l.id AS destination, l.capacity,
   inventory.occupied, inventory.committed, traffic.incoming,
   l.capacity-inventory.occupied-traffic.incoming AS free_slots,
   abs((src.attributes->>'x')::double precision-(l.attributes->>'x')::double precision)
     +abs((src.attributes->>'y')::double precision-(l.attributes->>'y')::double precision) AS immediate_distance,
   coalesce(abs((exit.attributes->>'x')::double precision-(l.attributes->>'x')::double precision)
     +abs((exit.attributes->>'y')::double precision-(l.attributes->>'y')::double precision),0) AS onward_distance,
   ARRAY(SELECT a.id FROM affected a ORDER BY a.id) AS affected_jobs,
   ARRAY(SELECT DISTINCT c.commitment_id FROM affected a
     JOIN move_jobs j ON j.run_id=%(run)s AND j.id=a.id
     JOIN containers c ON c.run_id=j.run_id AND c.id=j.container_id
     WHERE c.commitment_id IS NOT NULL ORDER BY c.commitment_id) AS affected_departures,
   l.id=root.target_id AS prescribed
 FROM root
 JOIN locations src ON src.run_id=root.run_id AND src.id=root.source_id
 JOIN containers cargo ON cargo.run_id=root.run_id AND cargo.id=root.container_id
 LEFT JOIN commitments co ON co.run_id=cargo.run_id AND co.id=cargo.commitment_id
 LEFT JOIN locations exit ON exit.run_id=co.run_id AND exit.id=co.location_id
 JOIN locations l ON l.run_id=root.run_id AND l.kind='yard' AND l.id<>root.source_id
 CROSS JOIN LATERAL (
   SELECT count(*)::int AS occupied,
     count(*) FILTER (WHERE c.commitment_id IS NOT NULL)::int AS committed
   FROM containers c WHERE c.run_id=l.run_id AND c.location_id=l.id
 ) inventory
 CROSS JOIN LATERAL (
   SELECT count(*)::int AS incoming FROM move_jobs j
   WHERE j.run_id=l.run_id AND j.target_id=l.id
     AND j.status IN ('queued','running') AND j.id<>root.id
 ) traffic
), classified AS (
 SELECT *, CASE WHEN free_slots<1 THEN 'No uncommitted capacity'
   WHEN committed>0 THEN 'Would cover cargo with an outbound commitment'
   ELSE NULL END AS excluded_reason FROM facts
)
SELECT *, dense_rank() OVER (
 ORDER BY (excluded_reason IS NOT NULL), immediate_distance+onward_distance, occupied
) AS shortlist_rank
FROM classified ORDER BY shortlist_rank,destination;
