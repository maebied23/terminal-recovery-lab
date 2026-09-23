-- Grain: one candidate/location/time boundary; resource joins must not multiply cargo.
-- Planning-only: a scheduled pickup creates conditional capacity, not observed vacancy.
WITH planned_moves AS (
    SELECT value AS move
    FROM jsonb_array_elements(%(rows)s::jsonb)
), move_times AS (
    -- Extract pickup and arrival from the candidate's physical stage schedule.
    SELECT
        move ->> 'job_id' AS job_id,
        move ->> 'source_id' AS source_id,
        move ->> 'target_id' AS target_id,
        (move ->> 'end')::int AS arrival_minute,
        (
            SELECT MIN((stage ->> 'start')::int)
            FROM jsonb_array_elements(move -> 'stages') AS stage
            WHERE stage ->> 'kind' = 'pickup'
        ) AS pickup_minute
    FROM planned_moves
), inventory_changes AS (
    -- Seed each yard with observed inventory, then apply candidate movement deltas.
    -- UNION ALL preserves simultaneous changes; the next CTE combines them.
    SELECT
        yard.id AS location_id,
        %(minute)s::int AS at_minute,
        COUNT(cargo.id)::bigint AS delta
    FROM locations AS yard
    LEFT JOIN containers AS cargo
        ON cargo.run_id = yard.run_id AND cargo.location_id = yard.id
    WHERE yard.run_id = %(run)s AND yard.kind = 'yard'
    GROUP BY yard.id

    UNION ALL

    SELECT source_id, pickup_minute, -1
    FROM move_times
    WHERE pickup_minute IS NOT NULL AND pickup_minute > %(minute)s

    UNION ALL

    SELECT target_id, arrival_minute, 1
    FROM move_times
), time_boundaries AS (
    -- One row per location/minute avoids arbitrary ordering of simultaneous events.
    SELECT location_id, at_minute, SUM(delta) AS delta
    FROM inventory_changes
    GROUP BY location_id, at_minute
), occupancy_profile AS (
    -- Running inventory holds until the next boundary, or the planning horizon.
    SELECT
        location_id,
        at_minute,
        LEAD(at_minute, 1, %(horizon)s::int) OVER (
            PARTITION BY location_id ORDER BY at_minute
        ) AS until_minute,
        SUM(delta) OVER (
            PARTITION BY location_id
            ORDER BY at_minute
            ROWS UNBOUNDED PRECEDING
        ) AS occupied
    FROM time_boundaries
)
SELECT
    profile.*,
    yard.capacity,
    yard.capacity - profile.occupied AS free_slots
FROM occupancy_profile AS profile
JOIN locations AS yard
    ON yard.run_id = %(run)s AND yard.id = profile.location_id
WHERE yard.kind = 'yard' AND profile.at_minute < %(horizon)s
ORDER BY profile.location_id, profile.at_minute;
