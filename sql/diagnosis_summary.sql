-- One row per cargo visit reaches this query. Multiple reasons never inflate totals.
WITH manifest AS (
 SELECT * FROM jsonb_to_recordset(%(rows)s::jsonb)
 AS r(commitment_id text,container_id text,readiness text,attention boolean)
)
SELECT co->>'id' AS commitment_id,(co->>'cutoff')::int AS cutoff,
 count(m.container_id)::int AS total,
 count(*) FILTER(WHERE readiness='Delivered on time')::int AS on_time,
 count(*) FILTER(WHERE readiness='Delivered late')::int AS late,
 count(*) FILTER(WHERE readiness='Next move ready')::int AS ready,
 count(*) FILTER(WHERE readiness='Work underway')::int AS underway,
 count(*) FILTER(WHERE readiness IN('Waiting / blocked','Work interrupted'))::int AS blocked,
 count(*) FILTER(WHERE readiness='Needs review')::int AS review,
 count(*) FILTER(WHERE readiness='Cutoff missed')::int AS missed,
 count(*) FILTER(WHERE attention)::int AS attention
FROM jsonb_array_elements(%(state)s::jsonb->'commitments') co
LEFT JOIN manifest m ON m.commitment_id=co->>'id'
GROUP BY co->>'id',co->>'cutoff'
ORDER BY (count(*) FILTER(WHERE attention)>0) DESC,(co->>'cutoff')::int,co->>'id';
