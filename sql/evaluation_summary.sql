-- Match each strategy to the same case + execution seed. Never compare unpaired
-- averages or omit failed candidates from coverage. JSON stores evolving metrics;
-- trial identity and per-visit outcomes are relational and uniquely constrained.
WITH paired AS (
 SELECT t.*,b.metrics AS baseline_metrics,
   CASE WHEN t.metrics IS NOT NULL AND b.metrics IS NOT NULL
        THEN (t.metrics->>'on_time')::int-(b.metrics->>'on_time')::int END AS delta
 FROM evaluation_trials t LEFT JOIN evaluation_trials b
 ON (b.evaluation_id,b.case_id,b.seed,b.strategy)=(t.evaluation_id,t.case_id,t.seed,'baseline')
 WHERE t.evaluation_id=%(evaluation)s
)
SELECT strategy,count(*) AS attempted,count(metrics) AS executed,
 count(delta) AS paired,count(*) FILTER(WHERE delta>0) AS wins,
 count(*) FILTER(WHERE delta=0) AS ties,count(*) FILTER(WHERE delta<0) AS losses,
 count(*) FILTER(WHERE validation<>'passed') AS not_executable,
 count(*) FILTER(WHERE execution_status='interrupted') AS interrupted,
 round(avg((metrics->>'on_time')::numeric),2) AS mean_on_time,
 round(avg(delta),2) AS mean_delta,
 percentile_cont(0.1) WITHIN GROUP(ORDER BY (metrics->>'on_time')::float) AS p10_on_time,
 percentile_cont(0.9) WITHIN GROUP(ORDER BY (metrics->>'on_time')::float) AS p90_on_time,
 round(avg((metrics->>'lateness')::numeric),2) AS mean_lateness,
 round(avg((metrics->>'prediction_error')::numeric),2) AS mean_prediction_error,
 round(avg((metrics->>'resource_wait_task_minutes')::numeric),2) AS mean_resource_wait,
 round(avg(changed_bookings),2) AS mean_changed_bookings
FROM paired GROUP BY strategy ORDER BY strategy;
