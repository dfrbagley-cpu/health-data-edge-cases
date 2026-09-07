-- Dates are validated, fixed-width calendar dates in these bundled fixtures.
-- The referral cohort includes starts on or before cutoff. Future service is ongoing at cutoff.
SELECT 'cohort' AS check_id, COUNT(*) AS value FROM referrals WHERE referred_on <= cutoff
UNION ALL SELECT 'completed', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND first_service_on >= referred_on AND first_service_on <= cutoff
UNION ALL SELECT 'same_day', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND first_service_on = referred_on
UNION ALL SELECT 'ongoing', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND (first_service_on = '' OR first_service_on > cutoff)
UNION ALL SELECT 'invalid_sequence', COUNT(*) FROM referrals WHERE referred_on <= cutoff AND first_service_on <> '' AND first_service_on < referred_on;
