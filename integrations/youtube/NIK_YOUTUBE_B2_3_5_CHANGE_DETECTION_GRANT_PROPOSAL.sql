-- B2.3.5 security extension ("Migration B"): incremental grant + RLS
-- policy extending the existing youtube_ingest role to
-- youtube_evidence.change_detection_events.
--
-- STATUS: PROPOSED / NOT APPLIED. Design and code review first (this
-- implementation gate), then this SQL artifact reviewed standalone,
-- then a separate explicit authorization to apply, then independent
-- read-only verification -- exactly the sequence B2.3.2/B2.3.3/B2.3.4
-- went through. This file has not itself been separately reviewed as a
-- standalone SQL artifact, and has not been submitted to
-- apply_migration.
--
-- Confirmed live during the readiness gate (2026-08-15): youtube_ingest
-- currently has zero grants and zero policies on change_detection_events
-- -- RLS is enabled with no policy (deny by default). This file exists
-- to close exactly that gap, nothing more.
--
-- Proposed to be applied AFTER the companion constraint migration
-- (NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_CONSTRAINT_PROPOSAL.sql,
-- "Migration A") -- design doc Decision 2 -- finalizing the table's
-- shape before granting access to it. Not a hard dependency; this
-- file's own grant/policy statements do not reference that migration's
-- constraint in any way.
--
-- Extends the role created by NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql
-- (applied as migration 20260814093130_b2_3_2_youtube_ingest_role_and_policies)
-- and already extended twice more, for video_inventory_snapshots and
-- channel_analytics_snapshots, by equivalently-shaped migrations (see
-- NIK_YOUTUBE_B2_3_3_VIDEO_INVENTORY_GRANT_PROPOSAL.sql and
-- NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_GRANT_PROPOSAL.sql for those
-- proposals' own committed text). None of those three prior files is
-- touched here -- this is a new, separate proposal.
--
-- Does NOT create a new role. youtube_ingest already exists. Does NOT
-- grant anything on channel_snapshots -- youtube_ingest already holds
-- SELECT there (granted at B2.3.2), which is all the resolution query
-- in src/ingestion/change_detection_ingest.py needs.

-- 1. Table grant. Necessary but not sufficient by itself -- RLS is
--    already enabled on this table (B2.3.1 migration) with zero
--    policies until the one below is added -- confirmed live during
--    the readiness gate. Same reasoning already used for
--    channel_snapshots/collection_runs/video_inventory_snapshots/
--    channel_analytics_snapshots.
grant select, insert on youtube_evidence.change_detection_events to youtube_ingest;

-- 2. Table-scoped policy. FOR ALL (not separate SELECT/INSERT
--    policies) is sufficient because youtube_evidence.forbid_mutation()'s
--    BEFORE UPDATE OR DELETE trigger already independently blocks
--    UPDATE/DELETE regardless of role, RLS, or grants -- FOR ALL here
--    does not open an UPDATE/DELETE path in practice. Same reasoning as
--    the four existing policies.
create policy youtube_ingest_all on youtube_evidence.change_detection_events
    for all
    to youtube_ingest
    using (true)
    with check (true);

-- Deliberately NOT included: a new CREATE ROLE (youtube_ingest already
-- exists), update/delete grants (forbid_mutation blocks both
-- regardless of grants), a redundant schema-level USAGE grant (already
-- granted at B2.3.2, schema-wide), and anything touching
-- channel_snapshots, video_inventory_snapshots, collection_runs, or
-- channel_analytics_snapshots -- out of scope for this file.
