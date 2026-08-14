-- B2.3.3 security extension: incremental grant + RLS policy extending
-- the existing youtube_ingest role to youtube_evidence.video_inventory_snapshots.
--
-- STATUS: PROPOSED / NOT APPLIED. Founder-approved in principle as an
-- architectural decision (B2.3.3 Decision 1, Decision 5). This file is
-- the drafted proposal text for that decision -- it has not itself
-- been separately reviewed as a standalone SQL artifact, and has not
-- been submitted to apply_migration.
--
-- Extends the role created by NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql
-- (already applied as migration b2_3_2_youtube_ingest_role_and_policies).
-- That file remains historical and untouched -- this is a new, separate
-- proposal (B2.3.3 Decision 5), not an edit to it.
--
-- Does NOT create a new role. youtube_ingest already exists.

-- 1. Table grant. Necessary but not sufficient by itself -- RLS is
--    already enabled on this table (B2.3.1 migration) with zero
--    policies until the one below is added. Same reasoning already
--    used for channel_snapshots/collection_runs.
grant select, insert on youtube_evidence.video_inventory_snapshots to youtube_ingest;

-- 2. Table-scoped policy. FOR ALL (not separate SELECT/INSERT
--    policies) is sufficient because youtube_evidence.forbid_mutation()'s
--    BEFORE UPDATE OR DELETE trigger already independently blocks
--    UPDATE/DELETE regardless of role, RLS, or grants -- FOR ALL here
--    does not open an UPDATE/DELETE path in practice. Same reasoning
--    as the two existing policies.
create policy youtube_ingest_all on youtube_evidence.video_inventory_snapshots
    for all
    to youtube_ingest
    using (true)
    with check (true);

-- Deliberately NOT included: a new CREATE ROLE (youtube_ingest already
-- exists -- Decision 1), update/delete grants (forbid_mutation blocks
-- both regardless of grants), and anything touching channel_snapshots,
-- collection_runs, channel_analytics_snapshots, or change_detection_events
-- -- out of scope for this file (Decision 5).
