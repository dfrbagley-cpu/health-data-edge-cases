-- Deliberately wrong: any non-empty service date is treated as completed, ignoring chronology and cutoff.
SELECT 'cohort' AS check_id, COUNT(*) AS value FROM referrals WHERE referred_on <= cutoff
UNION ALL SELECT 'completed', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND first_service_on <> ''
UNION ALL SELECT 'same_day', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND first_service_on = referred_on
UNION ALL SELECT 'ongoing', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND first_service_on = ''
UNION ALL SELECT 'invalid_sequence', 0;
