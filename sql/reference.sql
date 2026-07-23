-- Health Data Edge Cases reference implementation
--
-- The statements use SQL features shared by SQLite and DuckDB:
-- window functions, common table expressions, ISO-8601 text comparisons,
-- left joins, and conditional aggregation.

CREATE VIEW ranked_encounters AS
SELECT
    e.*,
    ROW_NUMBER() OVER (
        PARTITION BY e.source_event_id
        ORDER BY
            CAST(e.version AS INTEGER) DESC,
            e.updated_at DESC,
            e.encounter_row_id DESC
    ) AS version_rank
FROM encounters AS e;

CREATE VIEW current_encounters AS
SELECT *
FROM ranked_encounters
WHERE version_rank = 1;

-- In this suite, the current completed encounter is the evidence that service
-- occurred. Appointment status is retained as a separate quality signal.
CREATE VIEW qualifying_encounters AS
SELECT *
FROM current_encounters
WHERE LOWER(status) = 'completed';

-- The left join is intentional: missing mappings remain countable and visible.
CREATE VIEW qualifying_encounters_enriched AS
SELECT
    q.*,
    pm.reporting_program
FROM qualifying_encounters AS q
LEFT JOIN program_mappings AS pm
    ON q.program_id = pm.program_id;

CREATE VIEW first_qualifying_service AS
SELECT
    r.referral_id,
    MIN(q.occurred_at) AS first_service_at
FROM referrals AS r
JOIN qualifying_encounters AS q
    ON r.referral_id = q.referral_id
    AND q.referral_id <> ''
    AND q.occurred_at >= r.referred_at
GROUP BY r.referral_id;

CREATE VIEW actual_metrics AS
SELECT
    rp.period_id,
    'raw_completed_rows' AS metric_id,
    COUNT(e.encounter_row_id) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN encounters AS e
    ON LOWER(e.status) = 'completed'
    AND SUBSTR(e.occurred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
GROUP BY rp.period_id

UNION ALL

SELECT
    rp.period_id,
    'completed_service_events' AS metric_id,
    COUNT(q.source_event_id) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN qualifying_encounters AS q
    ON SUBSTR(q.occurred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
GROUP BY rp.period_id

UNION ALL

SELECT
    rp.period_id,
    'unique_patients_served' AS metric_id,
    COUNT(DISTINCT q.patient_id) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN qualifying_encounters AS q
    ON SUBSTR(q.occurred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
GROUP BY rp.period_id

UNION ALL

SELECT
    rp.period_id,
    'mapped_completed_events' AS metric_id,
    COUNT(
        CASE
            WHEN q.reporting_program IS NOT NULL
                AND q.reporting_program <> ''
            THEN 1
        END
    ) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN qualifying_encounters_enriched AS q
    ON SUBSTR(q.occurred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
GROUP BY rp.period_id

UNION ALL

SELECT
    rp.period_id,
    'unmapped_completed_events' AS metric_id,
    COUNT(
        CASE
            WHEN q.source_event_id IS NOT NULL
                AND (
                    q.reporting_program IS NULL
                    OR q.reporting_program = ''
                )
            THEN 1
        END
    ) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN qualifying_encounters_enriched AS q
    ON SUBSTR(q.occurred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
GROUP BY rp.period_id

UNION ALL

SELECT
    rp.period_id,
    'referrals_started' AS metric_id,
    COUNT(r.referral_id) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN referrals AS r
    ON SUBSTR(r.referred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
GROUP BY rp.period_id

UNION ALL

SELECT
    rp.period_id,
    'referrals_with_first_service' AS metric_id,
    COUNT(
        CASE
            WHEN fs.first_service_at >= r.referred_at
            THEN 1
        END
    ) AS actual_value
FROM reporting_periods AS rp
LEFT JOIN referrals AS r
    ON SUBSTR(r.referred_at, 1, 10) BETWEEN rp.start_date AND rp.end_date
LEFT JOIN first_qualifying_service AS fs
    ON r.referral_id = fs.referral_id
GROUP BY rp.period_id;

CREATE VIEW actual_quality AS
SELECT
    'source_events_with_multiple_versions' AS check_id,
    COUNT(*) AS actual_value
FROM (
    SELECT source_event_id
    FROM encounters
    GROUP BY source_event_id
    HAVING COUNT(*) > 1
)

UNION ALL

SELECT
    'current_voided_events' AS check_id,
    COUNT(*) AS actual_value
FROM current_encounters
WHERE LOWER(status) = 'voided'

UNION ALL

SELECT
    'unmapped_completed_encounters' AS check_id,
    COUNT(*) AS actual_value
FROM qualifying_encounters_enriched
WHERE reporting_program IS NULL
    OR reporting_program = ''

UNION ALL

SELECT
    'completed_encounter_cancelled_appointment' AS check_id,
    COUNT(DISTINCT q.source_event_id) AS actual_value
FROM qualifying_encounters AS q
JOIN appointments AS a
    ON q.appointment_id = a.appointment_id
WHERE q.appointment_id <> ''
    AND LOWER(a.status) IN ('cancelled', 'canceled')

UNION ALL

SELECT
    'completed_encounter_before_referral' AS check_id,
    COUNT(DISTINCT q.source_event_id) AS actual_value
FROM qualifying_encounters AS q
JOIN referrals AS r
    ON q.referral_id = r.referral_id
WHERE q.referral_id <> ''
    AND q.occurred_at < r.referred_at

UNION ALL

SELECT
    'completed_appointments_without_completed_encounter' AS check_id,
    COUNT(DISTINCT a.appointment_id) AS actual_value
FROM appointments AS a
LEFT JOIN qualifying_encounters AS q
    ON a.appointment_id = q.appointment_id
WHERE LOWER(a.status) = 'completed'
    AND q.source_event_id IS NULL;
