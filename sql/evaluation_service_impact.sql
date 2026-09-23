-- First count each frozen visit once, then pair service outcomes. A job-resource
-- join here would multiply cargo needing a supporting crane and a tractor.
WITH service AS (
 SELECT evaluation_id,case_id,seed,strategy,commitment_id,count(*) AS total,
 count(*) FILTER(WHERE on_time) AS on_time,sum(lateness) AS lateness
 FROM evaluation_visit_outcomes WHERE evaluation_id=%(evaluation)s
 GROUP BY evaluation_id,case_id,seed,strategy,commitment_id
), paired AS (
 SELECT t.*,t.on_time-b.on_time AS delta FROM service t LEFT JOIN service b
 ON (b.evaluation_id,b.case_id,b.seed,b.strategy,b.commitment_id)=
    (t.evaluation_id,t.case_id,t.seed,'baseline',t.commitment_id)
)
SELECT strategy,commitment_id,count(*) AS samples,round(avg(on_time),2) AS mean_on_time,
 round(avg(total),2) AS cargo_per_case,count(*) FILTER(WHERE on_time=total) AS complete_manifests,
 count(*) FILTER(WHERE delta<0) AS harmed_samples,round(avg(delta),2) AS mean_delta
FROM paired GROUP BY strategy,commitment_id ORDER BY commitment_id,strategy;
