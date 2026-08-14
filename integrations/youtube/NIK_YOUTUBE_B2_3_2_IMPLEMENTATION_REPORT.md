# NIK YouTube B2.3.2 — Implementation Report

**Version:** 1.2 — Step 2a (role/grants/policies) executed live 2026-08-14; see §11
**Status:** Adapter and tests written and verified locally (in Claude's own sandbox, against fixtures — never against the live Supabase database). **Zero writes performed against `wytwkhgkkvokgkbqwtxd`.**
**System:** NIK YouTube Integration
**Stage:** B2.3.2 — Channel Snapshot → Supabase Ingestion (Implementation Phase + Security Refinements)
**Date:** 2026-08-14

**Revision note (security refinements pass):** §0's role recommendation below was updated from `BYPASSRLS` to table-scoped RLS policies, and `db.py` gained a post-connect role-identity check — both per the independent review (`NIK_YOUTUBE_B2_3_2_INDEPENDENT_REVIEW_REPORT.md` §8/§9) and explicit founder direction. See §10 for exactly what changed in this pass. Sections 1–9 below otherwise describe the original implementation pass and are unchanged except where §0 is explicitly revised.

---

## 0. Dedicated-Role Investigation (required before implementation)

Per the approval message's item 3, this was resolved before any code was written.

**Feasibility — confirmed, not assumed.** A read-only query against the live project (the one live-database interaction in this pass — full text and result below) confirms the role that runs migrations has the privilege needed to create a new one:

```sql
select rolname, rolcanlogin, rolcreaterole, rolcreatedb, rolsuper, rolbypassrls
from pg_roles where rolname = current_user;
```
→ `{"rolname":"postgres","rolcanlogin":true,"rolcreaterole":true,"rolcreatedb":true,"rolsuper":false,"rolbypassrls":true}`

No blocker on that front. `postgres` is not itself a superuser (`rolsuper: false`) but does have `CREATEROLE`, which is all `CREATE ROLE` requires.

**A real complexity, surfaced rather than glossed over.** A plain `GRANT SELECT, INSERT` to a new role is **not sufficient by itself**. `youtube_evidence`'s tables have RLS enabled with zero policies (`NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` §6.4/§14) — in Postgres, that combination denies access to *every* role that doesn't bypass RLS, regardless of table-level grants. `service_role` and `postgres` both currently work only because both carry the `rolbypassrls` attribute (confirmed for `postgres` in the query above; documented for `service_role` in Supabase's own "Postgres Roles" doc, checked via `search_docs` this session). A new `youtube_ingest` role needs one of two things, not just a `GRANT`:

- `ALTER ROLE youtube_ingest BYPASSRLS` — preserves the "zero policies" invariant B2.3.1 already verified and reported; the role's actual reach is still limited to whatever tables it's separately granted.
- New RLS policies scoped to `youtube_ingest` — more granular/auditable, but changes the reported "0 rows in `pg_policies`" fact from B2.3.1's own verification, and is more new schema surface for a one-role, two-table need.

**Revised recommendation: table-scoped RLS policies, not `BYPASSRLS`.** *(Updated 2026-08-14, security refinements pass — see revision note above.)* The independent review (`NIK_YOUTUBE_B2_3_2_INDEPENDENT_REVIEW_REPORT.md` §9) correctly identified that `BYPASSRLS` is a role-wide, database-wide attribute, not a table-scoped one — its safety would depend entirely on every future `GRANT` to this role staying narrow, with no additional checkpoint if that ever changed. Table-scoped policies confine the privilege to exactly the two tables `youtube_ingest` needs, regardless of what it might be granted on later.

A single `FOR ALL` policy per table (rather than four granular `SELECT`/`INSERT` policies) is sufficient specifically because `youtube_evidence.forbid_mutation()`'s `BEFORE UPDATE OR DELETE` trigger (B2.3.1 §6.3) already independently blocks `UPDATE`/`DELETE` regardless of role, RLS, or grants — so `FOR ALL` doesn't actually open an `UPDATE`/`DELETE` path in practice; the trigger is the backstop either way.

**Exact privileges required — proposed, not executed. Full text now lives in `NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql`** (statically checked by `tests/test_role_proposal.py`, so an accidental future edit reintroducing `BYPASSRLS` or dropping a policy would fail the suite):

```sql
create role youtube_ingest with login password '<generated separately, never by Claude>';

grant usage on schema youtube_evidence to youtube_ingest;
grant select, insert on youtube_evidence.channel_snapshots to youtube_ingest;
grant select, insert on youtube_evidence.collection_runs to youtube_ingest;

create policy youtube_ingest_all on youtube_evidence.collection_runs
    for all to youtube_ingest using (true) with check (true);

create policy youtube_ingest_all on youtube_evidence.channel_snapshots
    for all to youtube_ingest using (true) with check (true);

-- Deliberately NOT included: BYPASSRLS, SUPERUSER, CREATEROLE, CREATEDB.
-- Deliberately NOT granted: update, delete (forbid_mutation blocks both
-- regardless; granting them adds nothing but exposure), and no access
-- to video_inventory_snapshots, channel_analytics_snapshots, or
-- change_detection_events -- out of scope for B2.3.2.
```

**Password:** not generated by this pass, and never will be by Claude — the same treatment as every other credential in this system. When this migration is actually approved and run, the password should be generated with a password manager or `openssl rand -base64 32`, and go straight into the credentials file below, never typed into a chat transcript.

*(The original `BYPASSRLS`-based proposal that stood here through the initial implementation pass is preserved verbatim in the independent review, §9, for the record of why it was reconsidered.)*

**This did not turn into a broader IAM project** — one role, two grants, one role attribute. Nothing about connection pooling, network rules, or other roles was touched or needed changing.

**Connection detail worth flagging, found via `search_docs`:** Supabase's direct connection (`db.[project-ref].supabase.co:5432`) is IPv6-only unless the project has the IPv4 add-on. For a persistent script on an ordinary (likely IPv4) network, the **Session Pooler** (`aws-[region].pooler.supabase.com:5432`) is what Supabase's own docs recommend instead — and its username format is `<role>.<project-ref>`, not the bare role name (e.g. `youtube_ingest.wytwkhgkkvokgkbqwtxd`, not `youtube_ingest`). This is a real detail worth getting right when the credentials file is actually filled in — it doesn't affect anything in this implementation, since `db.py` just takes a full connection string as-is.

## 1. Files Changed

All under `integrations/youtube/`. Nothing outside this folder was touched; no acquisition script was modified.

| File | Change |
|---|---|
| `src/ingestion/__init__.py` | New. Package docstring only. |
| `src/ingestion/errors.py` | New. `IngestRejected`, `IngestionNotConfigured`. |
| `src/ingestion/db.py` | New. Direct-Postgres connection helper — reads a local credential file, never falls back to a default. |
| `src/ingestion/mappings.py` | New. Pure validate/map functions for both `channel_snapshots` and `collection_runs`. No I/O. |
| `src/ingestion/channel_snapshot_ingest.py` | New. Orchestration: `ingest_channel_snapshot()`, `ensure_collection_run()`, `find_collection_log()`, and a `--dry-run`-by-default CLI. |
| `tests/test_ingestion_mappings.py` | New. 15 tests, Tier 0. |
| `tests/test_ingestion_channel_snapshot.py` | New. 14 tests, orchestration with a mocked connection. |
| `requirements.txt` | One line added: `psycopg2-binary==2.9.9`. Nothing else changed. |

No file under `credentials/` was created — `do_not_open_claude_supabase.json` does not exist yet, on purpose (§8 below).

## 2. Exact Field Mapping

Implemented exactly as specified in `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` §8.1 (`collection_runs`) and §8.2 (`channel_snapshots`) — `mappings.py`'s `map_channel_snapshot()` and `map_collection_run()` are close to a direct transcription of those two tables, column for column. Nothing diverged from the approved design; there was no field-mapping judgment call left to make at implementation time.

One implementation-level detail worth surfacing: `channel.published_at` (e.g. `"2026-08-09T03:33:12.388094Z"`) is rendered by YouTube's own API with a literal `Z` suffix, but this repo's venv is Python 3.10.12 (confirmed by reading it directly this session), where `datetime.fromisoformat()` doesn't accept a bare `Z` until 3.11. `mappings.py`'s validation normalizes `Z` → `+00:00` **only for the validity check** — the value actually written to the database is always the untouched original string, passed through to Postgres's own, more permissive `timestamptz` parser. Validation would otherwise have falsely rejected every real snapshot on this Python version.

## 3. Tests

29 tests, all passing (`pytest tests/ -v`, run in a sandbox with no Supabase credential present):

- **`test_ingestion_mappings.py` (15 tests, Tier 0 — no I/O, no network).** Uses the *actual* content of the three real files: the good `channel_20260812_192334.json`, and both legacy files, embedded verbatim as fixtures, not synthesized equivalents. Confirms the good file validates and maps field-for-field (including that `raw_response` and `retrieval_metadata` are passed through as the same object, not a copy, and that `pagination_completed: null` survives as `None`, not `False`); confirms both legacy files are rejected, by name, for every field they're actually missing; confirms UUID and literal-value checks reject bad input without false-rejecting good input (e.g. a genuinely-`None` `collection_id`, or a genuinely-`False` `success`).
- **`test_ingestion_channel_snapshot.py` (14 tests, orchestration).** Mocks the psycopg2 connection/cursor (no real database anywhere) to test control flow: dry run vs. real run, parent-before-child insert ordering, idempotent-duplicate skip, and rollback-on-failure.

## 4. Dry-Run Behavior

`dry_run=True` is the default in `ingest_channel_snapshot()`, and the CLI requires an explicit `--execute` flag to turn it off. Two dry-run modes exist:

- **No connection at all** (`conn=None`): validates and maps the file only; reports the `snapshot_id` and `collection_id` it *would* act on, with no duplicate/FK check possible.
- **A real connection, `dry_run=True`**: runs the actual `SELECT`-based duplicate and FK-existence checks, so the report is accurate against live state — but the code path that would call an `INSERT` is never reached.

Verified live, this session, against the real fixture — the CLI dry-run path (`python -m ingestion.channel_snapshot_ingest data/snapshots/channel_20260812_192334.json`, no `--execute`) correctly read the file, reported the real `snapshot_id` (`a9594393-7572-4597-bb05-76082a9c993d`) and `collection_id` (`98321ba3-6bf1-4e50-aa8b-8a223ccd4862`), and exited 0 having performed no database write of any kind (there is no Supabase credential in this sandbox, so none was possible even if the code were wrong).

## 5. Idempotency Behavior

`INSERT ... ON CONFLICT (id) DO NOTHING` for both tables — never `DO UPDATE`, which would hit the `forbid_mutation` trigger from `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` §6.3 and abort the whole statement. An application-level `SELECT`-based pre-check runs first, so a re-ingested file is reported as a clean "already present, 0 rows written" outcome rather than surfacing as any kind of error. `test_ingest_duplicate_snapshot_is_a_clean_skip_not_an_error` confirms both: no `INSERT` is ever issued, and the transaction still commits cleanly (a no-op skip is a success, not a failure).

## 6. Malformed / Legacy-File Behavior

`validate_channel_snapshot()` collects every problem before raising once — confirmed against the two real legacy files (`channel_20260812_171041.json`, `channel_20260812_173832.json`), each missing five required fields at once, each producing one `IngestRejected` naming all five by field name. Validation happens before any database call — `test_ingest_malformed_file_rejected_before_any_db_call` confirms `cursor.execute` is never called at all for a bad file, dry run or not. Per your explicit instruction and the design's §9 item 4, no code anywhere synthesizes a `snapshot_id` (or any other identity) for these two files — they remain permanently un-ingestible under this design, not a bug to route around.

## 7. FK / `collection_runs` Behavior

`ensure_collection_run()` implements design doc §6.2, option (a): if the parent already exists, it's a no-op; if not, it finds the matching `logs/collection_*.json` **by its actual `collection_id` field**, not by filename or timestamp guessing (`find_collection_log()` opens and checks each candidate); if no match exists at all, it raises `IngestRejected` rather than nulling out a real `collection_id` to dodge the foreign key. The parent insert and the child insert happen inside one transaction — `test_ingest_first_real_insert_inserts_parent_then_child_and_commits` confirms the parent statement is issued before the child statement, and `test_ingest_rolls_back_on_failure_after_parent_insert` confirms that if the child insert fails, the whole transaction rolls back rather than leaving an orphaned `collection_runs` row with no corresponding snapshot.

## 8. Credential Handling

`db.py` reads a connection string from `credentials/do_not_open_claude_supabase.json` — deliberately mirroring the exact "Claude does not open this" naming convention `auth.py` already uses for the YouTube OAuth client secret. **That file does not exist**, because the `youtube_ingest` role it would authenticate as hasn't been created (§0 — that's a separate, future, explicitly-approved step). `get_connection()` raises `IngestionNotConfigured` when it's missing, with no fallback to any broader-privilege credential. This was verified live, twice, this session: calling it directly raised the expected error with a clear message, and running the CLI with `--execute` (and no credentials file) crashed loudly with a traceback and exit code 1 — it did not silently no-op, and it did not fall back to some default connection.

## 9. Live Database Actions Performed

**Zero writes, zero migrations, zero rows inserted, zero roles created, zero policies added, zero schema changes, zero Data API exposure changes, zero MCP configuration, zero git operations.** `youtube_evidence` still has exactly 5 tables, 0 rows in each, 0 policies, and the migration history still shows only `20260814045608_b2_3_1_youtube_evidence_foundation`.

One read-only interaction did happen, disclosed in full in §0: a single `SELECT` against `pg_roles`, run to confirm role-creation feasibility before proposing the role SQL above, as your approval message asked for ("confirm the dedicated-role approach... before implementation"). It reads system catalog metadata about the current role; it does not touch, and could not touch, `youtube_evidence` or any of its data.

## 10. Security Refinements Pass (2026-08-14)

Scope: exactly the two corrections identified in the independent review (its §8 and §9/§10), and nothing else. No role created, no credentials touched, no Supabase connection made, no migration run, no snapshot inserted, no Data API exposure changed, no MCP configured, no YouTube acquisition script modified.

**Files changed:**

| File | Change |
|---|---|
| `src/ingestion/errors.py` | Added `IngestionRoleMismatch`. |
| `src/ingestion/db.py` | Added `EXPECTED_ROLE` constant and `_assert_expected_role()`; `get_connection()` now runs `select current_user;` immediately after connecting and fails closed (closing the connection, raising `IngestionRoleMismatch`) if the authenticated role isn't exactly `youtube_ingest`. |
| `NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql` | New. Canonical, not-yet-applied SQL for the revised role/policy design — see §0. |
| `tests/test_ingestion_db.py` | New. 8 tests for `get_connection()`: missing/incomplete credentials (including that `psycopg2.connect` is never even called when unconfigured), role-match success, role-mismatch failure (and that the connection is closed), the mismatch message names both roles, and that the check issues a `current_user` query. |
| `tests/test_role_proposal.py` | New. 8 static text checks against the SQL proposal file — confirms no `BYPASSRLS`/`SUPERUSER`/`CREATEROLE`/`CREATEDB`, exactly one role and exactly two table-scoped policies both scoped `TO youtube_ingest`, no `UPDATE`/`DELETE` grant, and no reference to any out-of-scope table in an executable statement. These check the proposal's *text*, not live Postgres behavior — the SQL is never executed by this suite or anywhere else in the repo. |
| `NIK_YOUTUBE_B2_3_2_IMPLEMENTATION_REPORT.md` | This file — §0 revised, this §10 added. |

No other file was touched. In particular, none of the 8 line-ending-drift files flagged in the independent review (its §1) were touched — they remain exactly as they were, unrelated to this pass.

**Tests:** full suite re-run after these changes — **45 passed** (the original 29, plus 8 new in `test_ingestion_db.py`, plus 8 new in `test_role_proposal.py`). No existing test was modified or removed.

**Live database actions performed: zero.** No connection to Supabase was made. No SQL from `NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql` was executed anywhere. `youtube_evidence` is unchanged from §9 above: still 5 tables, 0 rows, 0 policies, migration history still only `20260814045608_b2_3_1_youtube_evidence_foundation`.

---

## 11. Step 2a Execution (2026-08-14) — `youtube_ingest` Role, Grants, Policies

Approved scope: create `youtube_ingest` with `LOGIN` and no password, `GRANT USAGE` on `youtube_evidence`, `GRANT SELECT, INSERT` on `channel_snapshots` and `collection_runs`, and the two table-scoped `FOR ALL` policies from §0 / `NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql`. Nothing else.

**Pre-flight (read-only), confirmed before any write:** `youtube_ingest` did not already exist; `youtube_evidence` had 0 policies; migration history held only `20260814045608_b2_3_1_youtube_evidence_foundation`.

**Executed:** one migration, `20260814093130_b2_3_2_youtube_ingest_role_and_policies`, applied via `apply_migration` against `wytwkhgkkvokgkbqwtxd`. Contains exactly: `CREATE ROLE youtube_ingest WITH LOGIN` (no password clause), one `GRANT USAGE ON SCHEMA youtube_evidence`, two `GRANT SELECT, INSERT` (one per table), two `CREATE POLICY ... FOR ALL TO youtube_ingest USING (true) WITH CHECK (true)` (one per table). No other statement.

**Post-execution verification, all read-only:**

- `pg_roles`: `rolcanlogin=true`, `rolsuper=false`, `rolcreaterole=false`, `rolcreatedb=false`, `rolbypassrls=false` — matches every required condition exactly.
- `pg_policies`: exactly 2 rows — `youtube_ingest_all` on `channel_snapshots` and on `collection_runs`, both `roles={youtube_ingest}`, `cmd=ALL`, `qual=true`, `with_check=true`.
- `information_schema.role_table_grants`: exactly 4 rows — `SELECT`+`INSERT` on `channel_snapshots`, `SELECT`+`INSERT` on `collection_runs`. No `UPDATE`/`DELETE`, no other table.
- `pg_namespace.nspacl`: `youtube_evidence`'s ACL is now `{postgres=UC/postgres, service_role=U/postgres, youtube_ingest=U/postgres}` — confirms the migration added exactly one entry (`youtube_ingest=U`) and changed nothing else on that schema.
- One finding worth naming precisely rather than skipping past: `has_schema_privilege('youtube_ingest', 'public', 'USAGE')` also returns `true`. This is **not** something this migration granted — `public`'s ACL (`{pg_database_owner=UC/..., =U/pg_database_owner, postgres=U/..., anon=U/..., authenticated=U/..., service_role=U/...}`) shows USAGE on `public` already granted to the `PUBLIC` pseudo-role (the bare `=U` entry) for every role in the database, pre-existing since project creation. `youtube_ingest` does not appear in `public`'s ACL individually, and has no table-level grant on anything in `public` — this default doesn't grant access to any data.
- `list_migrations`: exactly 2 migrations total — the B2.3.1 one and this one. `list_tables`: `youtube_evidence` still has exactly 5 tables, all still `rls_enabled: true`, all still `0` rows — no data written, no other table touched.

**Not done, per the approved scope:** no password set or generated, no credentials file created, no `db.py`/ingestion code/tests touched, no data inserted, no Data API exposure change, no MCP configuration, no other table/role/policy touched.

**Local repo, updated before execution (per instruction):** `NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql` no longer has an inline password placeholder — it now reads `CREATE ROLE youtube_ingest WITH LOGIN;`, with the `ALTER ROLE ... WITH PASSWORD` step documented separately as founder-only. `tests/test_role_proposal.py` gained `test_does_not_set_a_password`. Full suite re-run after both the file update and the live execution: **46 passed** (the prior 45, plus this one new test).

---

**Stopping here at the review gate, per instruction.** The role, its grants, and its policies exist and are verified. `credentials/do_not_open_claude_supabase.json` still does not exist. Password provisioning and everything after it — credential creation, the first live ingestion, further ingestion phases, the AI access layer — remain separate, future, explicitly-gated steps.
