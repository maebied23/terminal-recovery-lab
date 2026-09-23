-- Aggregate receipts before any operational join: duplicate delivery is not extra work.
SELECT count(*) AS received,
 count(*) FILTER(WHERE status='applied') AS applied,
 count(*) FILTER(WHERE status='duplicate') AS duplicates,
 count(*) FILTER(WHERE status='stale') AS stale,
 count(*) FILTER(WHERE status='quarantined') AS quarantined,
 max(received_at) AS last_received_at,
 extract(epoch FROM now()-max(received_at))::int AS seconds_since_receipt
FROM feed_receipts WHERE run_id=%(run)s AND transport='equipment-adapter';
