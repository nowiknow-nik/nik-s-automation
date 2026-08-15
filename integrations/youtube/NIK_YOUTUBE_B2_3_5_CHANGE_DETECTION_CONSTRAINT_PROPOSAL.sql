-- B2.3.5 schema-structure migration ("Migration A"): makes
-- youtube_evidence.change_detection_events.source_file NOT NULL and
-- adds UNIQUE (source_file, metric) -- the idempotency key this table
-- has lacked since it was first created at B2.3.1.
--
-- STATUS: PROPOSED / NOT APPLIED. This is the idempotency model the
-- founder approved during the Change-Detection Readiness/Design Gate
-- (2026-08-15) and locked as a premise of
-- NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_INGESTION_DESIGN.md Sec 6 --
-- design and code review first (the B2.3.5 implementation gate this
-- file is a part of), then this SQL artifact reviewed standalone, then
-- a separate explicit authorization to apply, then independent
-- read-only verification -- the same sequence every prior B2.3.x
-- migration went through. This file has not itself been separately
-- reviewed as a standalone SQL artifact, and has not been submitted to
-- apply_migration.
--
-- Confirmed live during the readiness gate (2026-08-15):
-- change_detection_events currently holds zero rows, so this migration
-- is safe to apply cleanly -- there is no existing NULL source_file or
-- duplicate (source_file, metric) pair that could violate either new
-- constraint.
--
-- Kept as a separate migration from the grant/policy change
-- (NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_GRANT_PROPOSAL.sql, "Migration
-- B") -- design doc Decision 2: one clear thing per migration,
-- continuing every prior B2.3.x phase's discipline. Proposed order:
-- this file (A) before the grant/policy file (B) -- not a hard
-- dependency, just the cleaner sequence of finalizing the table's
-- shape before granting access to it.
--
-- Does NOT touch channel_snapshots, video_inventory_snapshots,
-- collection_runs, or channel_analytics_snapshots. Does NOT grant
-- anything or create any role/policy -- see the companion grant/policy
-- file for that.

-- 1. source_file becomes NOT NULL. Every real ingestion path already
--    supplies it -- map_change_detection_events() in
--    src/ingestion/mappings.py always sets it from the file being
--    ingested -- this closes off the only remaining way a row could be
--    inserted without it.
alter table youtube_evidence.change_detection_events
  alter column source_file set not null;

-- 2. UNIQUE (source_file, metric) -- the actual idempotency key. One
--    source file maps to N rows (one per changes[] entry, each a
--    distinct metric), so the natural conflict target is the pair, not
--    source_file alone -- source_file alone would incorrectly collide
--    across a single file's own multiple rows.
alter table youtube_evidence.change_detection_events
  add constraint change_detection_events_source_file_metric_key
  unique (source_file, metric);
