-- Grain: one outbound visit, with deduplicated prerequisite jobs and evidence.
-- Current calls pair typed rows with the matching snapshot; historical calls use
-- snapshot entities throughout. The caller supplies that consistent state/revision.
WITH RECURSIVE jobs AS MATERIALIZED (
    SELECT
        id, container_id, visit_id, source_id, target_id,
        equipment_id, status, attributes
    FROM move_jobs
    WHERE run_id = %(run)s AND %(current)s

    UNION ALL

    SELECT
        job ->> 'id',
        job ->> 'container_id',
        COALESCE(job ->> 'visit_id', cargo ->> 'visit_id'),
        job ->> 'source_id',
        job ->> 'target_id',
        job ->> 'equipment_id',
        job ->> 'status',
        job
    FROM jsonb_array_elements(%(state)s::jsonb -> 'jobs') AS job
    JOIN jsonb_array_elements(%(state)s::jsonb -> 'containers') AS cargo
        ON cargo ->> 'id' = job ->> 'container_id'
    WHERE NOT %(current)s
), visits AS MATERIALIZED (
    SELECT id, container_id, commitment_id
    FROM cargo_visits
    WHERE run_id = %(run)s AND %(current)s

    UNION ALL

    SELECT cargo ->> 'visit_id', cargo ->> 'id', cargo ->> 'commitment_id'
    FROM jsonb_array_elements(%(state)s::jsonb -> 'containers') AS cargo
    WHERE NOT %(current)s
), dependencies AS MATERIALIZED (
    SELECT job_id, predecessor_id, details
    FROM job_dependencies
    WHERE run_id = %(run)s AND %(current)s

    UNION ALL

    SELECT
        job ->> 'id',
        predecessor,
        COALESCE(job -> 'dependency_details' -> predecessor, '{}'::jsonb)
    FROM jsonb_array_elements(%(state)s::jsonb -> 'jobs') AS job
    CROSS JOIN LATERAL jsonb_array_elements_text(job -> 'dependencies') AS predecessor
    WHERE NOT %(current)s
), dependency_closure(root_id, id) AS (
    -- Stable (root, ancestor) pairs collapse diamond paths and terminate cycles.
    -- Adding depth/path to this row would change those deduplication semantics.
    SELECT id, id FROM jobs

    UNION

    SELECT closure.root_id, dependency.predecessor_id
    FROM dependency_closure AS closure
    JOIN dependencies AS dependency ON dependency.job_id = closure.id
), final_jobs AS (
    -- Match each visit's outbound move to its commitment's destination.
    SELECT visit.id AS visit_id, job.id
    FROM visits AS visit
    JOIN jsonb_array_elements(%(state)s::jsonb -> 'commitments') AS commitment
        ON commitment ->> 'id' = visit.commitment_id
    JOIN jobs AS job
        ON job.visit_id = visit.id
        AND job.container_id = visit.container_id
        AND job.target_id = commitment ->> 'location_id'
    WHERE job.attributes ->> 'kind' <> 'rehandle'
), visit_work AS (
    SELECT DISTINCT final.visit_id, closure.id
    FROM final_jobs AS final
    JOIN dependency_closure AS closure ON closure.root_id = final.id
)
SELECT
    visit.id AS visit_id,
    visit.container_id,
    visit.commitment_id,
    ARRAY(
        SELECT id FROM final_jobs WHERE visit_id = visit.id ORDER BY id
    ) AS final_ids,
    ARRAY(
        SELECT id FROM visit_work WHERE visit_id = visit.id ORDER BY id
    ) AS job_ids,
    -- Aggregate independently: joining edges directly to cargo would multiply rows.
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'job_id', dependency.job_id,
            'predecessor_id', dependency.predecessor_id,
            'details', dependency.details
        ) ORDER BY dependency.job_id, dependency.predecessor_id)
        FROM dependencies AS dependency
        WHERE dependency.job_id IN (
            SELECT id FROM visit_work WHERE visit_id = visit.id
        )
    ), '[]') AS edges,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'job_id', job.id,
            'container_id', job.container_id,
            'planned_pickup', job.source_id,
            'observed_position', cargo ->> 'location_id'
        ) ORDER BY job.id)
        FROM visit_work AS work
        JOIN jobs AS job ON job.id = work.id
        JOIN jsonb_array_elements(%(state)s::jsonb -> 'containers') AS cargo
            ON cargo ->> 'id' = job.container_id
        WHERE work.visit_id = visit.id
            AND job.status = 'queued'
            AND cargo ->> 'location_id' IS DISTINCT FROM job.source_id
            -- An unfinished upstream transfer can legitimately supply this pickup.
            AND NOT EXISTS (
                SELECT 1
                FROM dependency_closure AS closure
                JOIN jobs AS predecessor ON predecessor.id = closure.id
                WHERE closure.root_id = job.id AND closure.id <> job.id
                    AND predecessor.container_id = job.container_id
                    AND predecessor.target_id = job.source_id
                    AND predecessor.status <> 'completed'
            )
    ), '[]') AS mismatches
FROM visits AS visit
WHERE visit.commitment_id IS NOT NULL
ORDER BY visit.commitment_id, visit.id;
