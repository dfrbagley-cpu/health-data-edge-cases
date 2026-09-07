-- Half-open intervals: valid_from <= service_on < valid_to.
-- Aggregate matches per event before counting; retain orphans and ambiguous matches.
WITH matches AS (
 SELECT e.event_id, COUNT(m.category) AS match_count, MIN(m.category) AS category
 FROM events e LEFT JOIN mappings m ON e.program=m.program AND e.service_on>=m.valid_from AND e.service_on<m.valid_to
 GROUP BY e.event_id
)
SELECT 'events' AS check_id, COUNT(*) AS value FROM matches
UNION ALL SELECT 'mapped_once', COUNT(*) FROM matches WHERE match_count=1
UNION ALL SELECT 'unmapped', COUNT(*) FROM matches WHERE match_count=0
UNION ALL SELECT 'ambiguous', COUNT(*) FROM matches WHERE match_count>1
UNION ALL SELECT 'old_category', COUNT(*) FROM matches WHERE match_count=1 AND category='old'
UNION ALL SELECT 'new_category', COUNT(*) FROM matches WHERE match_count=1 AND category='new';
