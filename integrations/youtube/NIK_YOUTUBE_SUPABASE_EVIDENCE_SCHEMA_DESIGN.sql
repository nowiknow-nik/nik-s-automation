-- =====================================================================
-- NIK YouTube Evidence Store — Proposed Schema (B2.3.1)
-- STATUS: APPLIED 2026-08-14 to wytwkhgkkvokgkbqwtxd as migration
-- 20260814045608_b2_3_1_youtube_evidence_foundation. Schema is live.
-- Companion to: NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 14
-- for full post-apply verification results.
-- Target: Supabase project "NIK Automation Project" (wytwkhgkkvokgkbqwtxd)
-- This file is now a historical record of what was executed, not a
-- pending proposal. Do not re-run -- objects already exist.
-- =====================================================================

create schema if not exists youtube_evidence;

comment on schema youtube_evidence is
  'YouTube evidence store (NIK B2.3). Holds OBSERVED/DERIVED evidence collected '
  'from the YouTube Data/Analytics APIs via integrations/youtube. Source of '
  'record, not the Knowledge Operating System (SI-003A/SI-006) -- see '
  'NIK_YOUTUBE_CAPABILITY_MAP.md Sec 9 (KOS Boundary).';

-- ---------------------------------------------------------------------
-- 1. collection_runs
-- ---------------------------------------------------------------------

create table youtube_evidence.collection_runs (
  collection_id            uuid primary key,
  schema_version           text not null,
  collection_type          text not null check (collection_type = 'youtube_full_collection'),
  started_at_utc           timestamptz not null,
  finished_at_utc          timestamptz not null,
  success                  boolean not null,
  components               jsonb not null,
  source_file              text,
  ingested_at_utc          timestamptz not null default now(),

  constraint collection_runs_finished_after_started
    check (finished_at_utc >= started_at_utc)
);

comment on table youtube_evidence.collection_runs is
  'One row per collector.py orchestration run (logs/collection_*.json). '
  'components preserves the full per-script execution record (stdout/stderr, '
  'timings, produced_snapshot_id) verbatim.';

create index collection_runs_started_at_idx
  on youtube_evidence.collection_runs (started_at_utc desc);

create index collection_runs_failed_idx
  on youtube_evidence.collection_runs (started_at_utc desc)
  where success = false;

-- ---------------------------------------------------------------------
-- 2. channel_snapshots
-- ---------------------------------------------------------------------

create table youtube_evidence.channel_snapshots (
  snapshot_id              uuid primary key,
  schema_version           text not null,
  snapshot_type            text not null check (snapshot_type = 'youtube_channel'),
  generated_at_utc         timestamptz not null,
  source                   text not null check (source = 'youtube_data_api'),
  api_version              text not null check (api_version = 'v3'),
  collection_id            uuid references youtube_evidence.collection_runs (collection_id),

  channel_id               text not null,
  title                    text,
  description              text,
  custom_url               text,
  published_at             timestamptz,
  country                  text,

  view_count               bigint not null,
  subscriber_count         bigint not null,
  video_count              bigint not null,
  hidden_subscriber_count  boolean not null,

  uploads_playlist_id      text,
  branding                 jsonb,

  retrieval_metadata       jsonb not null,
  raw_response             jsonb not null,

  source_file              text,
  ingested_at_utc          timestamptz not null default now(),

  constraint channel_snapshots_channel_time_uq
    unique (channel_id, generated_at_utc)
);

comment on table youtube_evidence.channel_snapshots is
  'One row per channel_snapshot.py run (data/snapshots/channel_*.json). '
  'Immutable once written -- see forbid_mutation trigger below.';

create index channel_snapshots_channel_time_idx
  on youtube_evidence.channel_snapshots (channel_id, generated_at_utc desc);

create index channel_snapshots_collection_idx
  on youtube_evidence.channel_snapshots (collection_id);

-- ---------------------------------------------------------------------
-- 3. video_inventory_snapshots
-- ---------------------------------------------------------------------

create table youtube_evidence.video_inventory_snapshots (
  snapshot_id              uuid primary key,
  schema_version           text not null,
  snapshot_type            text not null check (snapshot_type = 'youtube_video_inventory'),
  generated_at_utc         timestamptz not null,
  source                   text not null check (source = 'youtube_data_api'),
  api_version              text not null check (api_version = 'v3'),
  collection_id            uuid references youtube_evidence.collection_runs (collection_id),

  channel_id               text not null,
  uploads_playlist_id      text,
  video_count              integer not null,
  videos                   jsonb not null,

  retrieval_metadata       jsonb not null,

  source_file              text,
  ingested_at_utc          timestamptz not null default now(),

  constraint video_inventory_snapshots_channel_time_uq
    unique (channel_id, generated_at_utc)
);

comment on table youtube_evidence.video_inventory_snapshots is
  'One row per video_inventory.py run (data/snapshots/videos/videos_*.json). '
  'videos is the full per-video array, including the enrichment videos.list() '
  'raw item under video_details where present. Not normalized into a child '
  'table yet -- see design doc Sec 6.1.';

create index video_inventory_snapshots_channel_time_idx
  on youtube_evidence.video_inventory_snapshots (channel_id, generated_at_utc desc);

create index video_inventory_snapshots_collection_idx
  on youtube_evidence.video_inventory_snapshots (collection_id);

create index video_inventory_snapshots_videos_gin_idx
  on youtube_evidence.video_inventory_snapshots using gin (videos jsonb_path_ops);

-- ---------------------------------------------------------------------
-- 4. channel_analytics_snapshots
-- ---------------------------------------------------------------------

create table youtube_evidence.channel_analytics_snapshots (
  snapshot_id              uuid primary key,
  schema_version           text not null,
  snapshot_type            text not null check (snapshot_type = 'youtube_channel_analytics'),
  generated_at_utc         timestamptz not null,
  source                   text not null check (source = 'youtube_analytics_api'),
  api_version              text not null check (api_version = 'v2'),
  collection_id            uuid references youtube_evidence.collection_runs (collection_id),

  channel_id               text not null,
  reporting_start_date     date not null,
  reporting_end_date       date not null,
  metrics_requested        text[] not null,
  analytics                jsonb not null,

  retrieval_metadata       jsonb not null,

  source_file              text,
  ingested_at_utc          timestamptz not null default now(),

  constraint channel_analytics_snapshots_channel_time_uq
    unique (channel_id, generated_at_utc),

  constraint channel_analytics_snapshots_period_valid
    check (reporting_end_date >= reporting_start_date)
);

comment on table youtube_evidence.channel_analytics_snapshots is
  'One row per analytics_snapshot.py run (data/analytics/channel_analytics_*.json). '
  'Multiple rows legitimately share the same reporting period -- Analytics data can '
  'be revised after initial reporting, so repeat observations of one period are '
  'evidence, not duplicates. analytics already contains the full raw API response; '
  'no separate raw_response column, matching the source (design doc Sec 8.4).';

create index channel_analytics_snapshots_channel_time_idx
  on youtube_evidence.channel_analytics_snapshots (channel_id, generated_at_utc desc);

create index channel_analytics_snapshots_period_idx
  on youtube_evidence.channel_analytics_snapshots (channel_id, reporting_start_date, reporting_end_date);

create index channel_analytics_snapshots_collection_idx
  on youtube_evidence.channel_analytics_snapshots (collection_id);

-- ---------------------------------------------------------------------
-- 5. change_detection_events
-- ---------------------------------------------------------------------

create table youtube_evidence.change_detection_events (
  event_id                 uuid primary key default extensions.gen_random_uuid(),
  detection_run_id         uuid not null, -- intentionally no FK to collection_runs; see design doc Sec 6.2
  schema_version           text not null,
  generated_at_utc         timestamptz not null,

  entity_type              text not null,
  entity_id                text not null,
  metric                   text not null,
  previous_value           numeric,
  current_value            numeric,
  change_type              text not null check (change_type in ('UNCHANGED', 'CHANGED', 'UNAVAILABLE')),
  absolute_change          numeric,
  percentage_change        numeric,
  evidence_class           text not null check (evidence_class in ('OBSERVED', 'DERIVED', 'INTERPRETATION', 'ASSUMPTION')),

  previous_snapshot_id     uuid references youtube_evidence.channel_snapshots (snapshot_id),
  current_snapshot_id      uuid references youtube_evidence.channel_snapshots (snapshot_id),
  previous_snapshot_source jsonb not null,
  current_snapshot_source  jsonb not null,

  source_file              text,
  ingested_at_utc          timestamptz not null default now()
);

comment on table youtube_evidence.change_detection_events is
  'One row per metric compared by change_detection.py (data/snapshots/changes/change_*.json), '
  'not one row per file -- a single comparison run produces one row per metric and shares one '
  'detection_run_id. previous_snapshot_id/current_snapshot_id are resolved at ingestion time by '
  'matching *_snapshot_source.generated_at_utc against channel_snapshots.generated_at_utc -- the '
  'source file only records a filesystem path, preserved verbatim in *_snapshot_source for audit '
  'but never used as a live reference (design doc Sec 6.6). FK scoped to channel_snapshots only -- '
  'change_detection.py does not compare any other snapshot type today (design doc Sec 6.2).';

create index change_detection_events_entity_time_idx
  on youtube_evidence.change_detection_events (entity_type, entity_id, generated_at_utc desc);

create index change_detection_events_run_idx
  on youtube_evidence.change_detection_events (detection_run_id);

create index change_detection_events_prev_snap_idx
  on youtube_evidence.change_detection_events (previous_snapshot_id);

create index change_detection_events_curr_snap_idx
  on youtube_evidence.change_detection_events (current_snapshot_id);

-- ---------------------------------------------------------------------
-- 6. Immutability: append-only enforcement (design doc Sec 6.3)
-- ---------------------------------------------------------------------

create or replace function youtube_evidence.forbid_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception
    'youtube_evidence.% is append-only (NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md Sec 5): % is not permitted',
    TG_TABLE_NAME, TG_OP;
end;
$$;

create trigger collection_runs_forbid_update
  before update or delete on youtube_evidence.collection_runs
  for each row execute function youtube_evidence.forbid_mutation();

create trigger channel_snapshots_forbid_update
  before update or delete on youtube_evidence.channel_snapshots
  for each row execute function youtube_evidence.forbid_mutation();

create trigger video_inventory_snapshots_forbid_update
  before update or delete on youtube_evidence.video_inventory_snapshots
  for each row execute function youtube_evidence.forbid_mutation();

create trigger channel_analytics_snapshots_forbid_update
  before update or delete on youtube_evidence.channel_analytics_snapshots
  for each row execute function youtube_evidence.forbid_mutation();

create trigger change_detection_events_forbid_update
  before update or delete on youtube_evidence.change_detection_events
  for each row execute function youtube_evidence.forbid_mutation();

-- ---------------------------------------------------------------------
-- 7. RLS: enabled, deny-by-default (design doc Sec 6.4)
-- ---------------------------------------------------------------------

alter table youtube_evidence.collection_runs enable row level security;
alter table youtube_evidence.channel_snapshots enable row level security;
alter table youtube_evidence.video_inventory_snapshots enable row level security;
alter table youtube_evidence.channel_analytics_snapshots enable row level security;
alter table youtube_evidence.change_detection_events enable row level security;

-- No policies are created here. With RLS enabled and zero policies, only
-- service_role (which bypasses RLS) can read or write. anon and authenticated
-- are intentionally NOT granted schema usage below -- unlike Supabase's
-- "Using Custom Schemas" tutorial default, which grants both. The MCP read
-- layer's own role and SELECT-only policy are B2.3.5's decision (Sec 6.4/10),
-- not this one. This schema is also not added to Exposed Schemas here.

grant usage on schema youtube_evidence to service_role;
grant select, insert on all tables in schema youtube_evidence to service_role;
alter default privileges for role postgres in schema youtube_evidence
  grant select, insert on tables to service_role;

-- =====================================================================
-- END OF PROPOSED SCHEMA -- NOT EXECUTED
-- Resolved 2026-08-14: gen_random_uuid() (pgcrypto, installed in the
-- `extensions` schema, Sec 4 of the design doc) is explicitly qualified
-- as extensions.gen_random_uuid() above rather than left to default
-- search_path resolution, per founder instruction.
-- =====================================================================
