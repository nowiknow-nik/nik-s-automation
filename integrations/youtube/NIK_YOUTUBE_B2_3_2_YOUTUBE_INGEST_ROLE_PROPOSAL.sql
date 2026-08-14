-- B2.3.2 security refinements: youtube_ingest role, table-scoped RLS
-- policies.
--
-- Role/grant/policy portion below is Step 2a of the B2.3.2 security
-- refinements, founder-approved for live execution against
-- wytwkhgkkvokgkbqwtxd -- see NIK_YOUTUBE_B2_3_2_INDEPENDENT_REVIEW_REPORT.md
-- Sec 9/10 and the Step 2a approval message. Applied via apply_migration
-- as migration b2_3_2_youtube_ingest_role_and_policies.
--
-- Supersedes the BYPASSRLS-based proposal originally in
-- NIK_YOUTUBE_B2_3_2_IMPLEMENTATION_REPORT.md Sec 0 (preserved there,
-- and in the independent review Sec 9, for the record of why it was
-- reconsidered): BYPASSRLS is a role-wide, database-wide attribute, so
-- its safety would depend entirely on every future GRANT to this role
-- staying narrow, with no additional checkpoint if that ever changed.
-- Table-scoped policies confine the privilege to exactly the two
-- tables below, regardless of what this role might be granted on
-- later.
--
-- Assumes RLS is already enabled with zero policies on both target
-- tables, per the applied B2.3.1 migration
-- (NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.sql Sec 7 -- "alter
-- table youtube_evidence.collection_runs enable row level security;"
-- and the same for channel_snapshots) -- re-confirmed true as of this
-- pass; re-confirm again before actually applying this file.
--
-- PASSWORD IS DELIBERATELY NOT SET BELOW. CREATE ROLE below grants
-- LOGIN but no password, which means the role cannot authenticate at
-- all (Supabase's direct Postgres connection has no trust-auth
-- fallback) until a password is set. Setting that password is a
-- separate, founder-controlled step, run directly against Supabase
-- (SQL editor or psql) -- never through Claude, never pasted into a
-- chat transcript:
--
--     alter role youtube_ingest with password '<a strong, randomly generated password>';
--
-- The resulting connection string (using the Session Pooler host, for
-- IPv4 -- see NIK_YOUTUBE_B2_3_2_IMPLEMENTATION_REPORT.md Sec 0) then
-- goes straight into credentials/do_not_open_claude_supabase.json by
-- hand, matching how credentials/do_not_open_claude.json already works
-- for the YouTube OAuth secret -- see db.py's module docstring for why
-- that file doesn't exist yet either.

-- 1. Role. Login-capable so the adapter can authenticate as it
--    directly, once a password exists (see above). Deliberately NOT:
--    superuser, createrole, createdb, bypassrls -- and, per the note
--    above, deliberately no password set here either.
create role youtube_ingest with login;

-- 2. Schema/table grants. Necessary but not sufficient by themselves --
--    RLS (already enabled, per above) still denies everything until
--    the policies below are added.
grant usage on schema youtube_evidence to youtube_ingest;
grant select, insert on youtube_evidence.channel_snapshots to youtube_ingest;
grant select, insert on youtube_evidence.collection_runs to youtube_ingest;

-- 3. Table-scoped policies. FOR ALL (not 4 separate SELECT/INSERT
--    policies) is sufficient because youtube_evidence.forbid_mutation()'s
--    BEFORE UPDATE OR DELETE trigger (B2.3.1 Sec 6.3) already
--    independently blocks UPDATE/DELETE regardless of role, RLS, or
--    grants -- so FOR ALL here does not actually open an UPDATE/DELETE
--    path in practice; the trigger is the backstop either way.
create policy youtube_ingest_all on youtube_evidence.collection_runs
    for all
    to youtube_ingest
    using (true)
    with check (true);

create policy youtube_ingest_all on youtube_evidence.channel_snapshots
    for all
    to youtube_ingest
    using (true)
    with check (true);

-- Deliberately NOT included anywhere above: BYPASSRLS, SUPERUSER,
-- CREATEROLE, CREATEDB, a password.
--
-- Deliberately NOT granted: update, delete (forbid_mutation blocks
-- both regardless of grants; granting them adds exposure without
-- adding any real capability), and no access at all to
-- video_inventory_snapshots, channel_analytics_snapshots, or
-- change_detection_events -- out of scope for B2.3.2. Extending this
-- role (or creating separate ones) for B2.3.3/B2.3.4 is a small,
-- separate, future decision -- not pre-empted here.
--
-- Password: generate with a password manager or `openssl rand -base64
-- 32`, applied with `alter role youtube_ingest with password '...';`
-- run directly by the founder (see note near the top of this file) --
-- never generated, held, or seen by Claude, and never typed into a
-- chat transcript.
