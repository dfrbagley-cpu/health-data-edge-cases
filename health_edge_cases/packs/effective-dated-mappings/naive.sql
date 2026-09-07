-- Deliberately wrong: an inner join hides orphans and inflates counts for overlaps.
WITH joined AS (SELECT e.event_id,m.category FROM events e JOIN mappings m ON e.program=m.program AND e.service_on>=m.valid_from AND e.service_on<m.valid_to)
SELECT 'events' AS check_id, COUNT(*) AS value FROM joined
UNION ALL SELECT 'mapped_once', COUNT(*) FROM joined
UNION ALL SELECT 'unmapped', 0
UNION ALL SELECT 'ambiguous', 0
UNION ALL SELECT 'old_category', COUNT(*) FROM joined WHERE category='old'
UNION ALL SELECT 'new_category', COUNT(*) FROM joined WHERE category='new';
