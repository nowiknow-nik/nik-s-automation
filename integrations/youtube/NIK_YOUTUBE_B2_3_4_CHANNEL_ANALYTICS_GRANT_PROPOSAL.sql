-- B2.3.4 security extension: incremental grant + RLS policy extending
-- the existing youtube_ingest role to youtube_evidence.channel_analytics_snapshots.
--
-- STATUS: PROPOSED / NOT APPLIED. Founder-locked as Decision E ("use
-- the B2.3.3 migration/gating sequence") -- design and code review
-- first (this implementation gate), then this SQL artifact reviewed
-- standalone, then a separate explicit authorization to apply, then
-- independent read-only verification -- exactly the sequence B2.3.3
-- went through. This file is the drafted proposal text for that later
-- gate -- it has not itself been separately reviewed as a standalone
-- SQL artifact, and has not been submitted to apply_migration.
--
-- Confirmed directly against live Supabase (project wytwkhgkkvokgkbqwtxd)
-- during the B2.3.4 investigation gate, three independent ways
-- (table-scoped grants query, youtube_ingest's full cross-schema grant
-- list, and get_advisors): youtube_ingest currently has zero grants
-- and zero policies on channel_analytics_snapshots. This file exists
-- to close exactly that gap, nothing more.
--
-- Extends the role created by NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql
-- (applied as migration 20260814093130_b2_3_2_youtube_ingest_role_and_policies)
-- and already extended once more, for video_inventory_snapshots, by an
-- equivalently-shaped migration (20260814160151_b2_3_3_video_inventory_grant_and_policy,
-- applied; see NIK_YOUTUBE_B2_3_3_VIDEO_INVENTORY_GRANT_PROPOSAL.sql for
-- that proposal's own committed text). Neither prior file is touched
-- here -- this is a new, separate proposal, not an edit to either of
-- them.
--
-- Does NOT create a new role. youtube_ingest already exists.

-- 1. Table grant. Necessary but not sufficient by itself -- RLS is
--    already enabled on this table (B2.3.1 migration) with zero
--    policies until the one below is added -- confirmed live during
--    the B2.3.4 investigation (get_advisors flagged
--    rls_enabled_no_policy on this exact table). Same reasoning
--    already used for channel_snapshots/collection_runs/
--    video_inventory_snapshots.
grant select, insert on youtube_evidence.channel_analytics_snapshots to youtube_ingest;

-- 2. Table-scoped policy. FOR ALL (not separate SELECT/INSERT
--    policies) is sufficient because youtube_evidence.forbid_mutation()'s
--    BEFORE UPDATE OR DELETE trigger already independently blocks
--    UPDATE/DELETE regardless of role, RLS, or grants -- FOR ALL here
--    does not open an UPDATE/DELETE path in practice. Same reasoning
--    as the three existing policies.
create policy youtube_ingest_all on youtube_evidence.channel_analytics_snapshots
    for all
    to youtube_ingest
    using (true)
    with check (true);

-- Deliberately NOT included: a new CREATE ROLE (youtube_ingest already
-- exists), update/delete grants (forbid_mutation blocks both
-- regardless of grants), and anything touching channel_snapshots,
-- video_inventory_snapshots, collection_runs, or change_detection_events
-- -- out of scope for this file (B2.3.4 Decision B: analytics
-- ingestion only, change-detection deferred).
