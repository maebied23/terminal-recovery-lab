-- Local model rules are inspectable evidence, not certified terminal procedures.
INSERT INTO source_assertions(id,title,source,review_status,executable,body) VALUES
 ('R-POSITION','Reconcile instructions with observed inventory','Northstar local diagnosis contract v1','reviewed',true,'A queued pickup at a different position is expected only when an unfinished same-cargo ancestor delivers there. Otherwise flag a plan/state disagreement. A position observation does not complete work.'),
 ('R-RESOURCE','Capability, availability and use are separate','Northstar local dispatch contract v1','reviewed',true,'Reuse dispatch checks for compatibility, lifting limits, source authority, published shifts and simultaneous handling resources. A compatible alternative is not assigned or booked.'),
 ('R-SERVICE','Respect the service window','Northstar local dispatch contract v1','reviewed',true,'Outbound work must respect its cargo commitment arrival, cutoff and status. Discharge requires the source vessel alongside. Diagnosis does not authorize changes to external schedules.')
ON CONFLICT DO NOTHING;
INSERT INTO schema_version(version) VALUES(4) ON CONFLICT DO NOTHING;
