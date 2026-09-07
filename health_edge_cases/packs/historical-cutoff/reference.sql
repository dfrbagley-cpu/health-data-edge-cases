-- Filter knowledge time BEFORE ranking versions. Cutoff includes the entire stated calendar day.
WITH at_cutoff AS (
 SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY CAST(version AS INTEGER) DESC) AS rank_value
 FROM events WHERE known_on <= '2026-08-31'
), latest AS (
 SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY CAST(version AS INTEGER) DESC) AS rank_value FROM events
)
SELECT 'known_at_cutoff' AS check_id, COUNT(*) AS value FROM at_cutoff WHERE rank_value=1 AND status='completed' AND service_on BETWEEN '2026-08-01' AND '2026-08-31'
UNION ALL SELECT 'latest_revised', COUNT(*) FROM latest WHERE rank_value=1 AND status='completed' AND service_on BETWEEN '2026-08-01' AND '2026-08-31'
UNION ALL SELECT 'late_arrivals', COUNT(*) FROM events WHERE version='1' AND known_on > '2026-08-31' AND service_on <= '2026-08-31'
UNION ALL SELECT 'post_cutoff_corrections', COUNT(*) FROM events WHERE CAST(version AS INTEGER)>1 AND known_on > '2026-08-31'
UNION ALL SELECT 'included_on_boundary', COUNT(*) FROM at_cutoff WHERE rank_value=1 AND known_on='2026-08-31' AND status='completed';
