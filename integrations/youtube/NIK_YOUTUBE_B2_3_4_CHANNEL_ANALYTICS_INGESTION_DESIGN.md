# NIK YouTube B2.3.4 — Channel Analytics → Supabase Ingestion Design

**Version:** 1.0
**Status:** DESIGN FINALIZED AND IMPLEMENTED. Code written and tested in an isolated sandbox (133/133 passing). Present in the actual repository's working tree — all seven B2.3.4 artifacts, including this document, were transferred there as part of this implementation gate — but NOT staged, NOT committed, NOT pushed. NO Supabase migration applied. NO live ingestion has occurred. This document itself is being produced as part of the implementation gate, per Decision F, closing the documentation gap named in the B2.3.4 investigation report §0.3 (two prior design/review documents — `NIK_YOUTUBE_B2_3_3_VIDEO_INVENTORY_INGESTION_DESIGN.md` and `NIK_YOUTUBE_B2_3_2_INDEPENDENT_REVIEW_REPORT.md` — are cited by name in live code/SQL comments but do not exist anywhere in the repository; this file is the corrective precedent, not a repeat of it).
**System:** NIK YouTube Integration
**Stage:** B2.3.4 — Channel Analytics → Supabase Ingestion
**Date:** 2026-08-15

**Six founder decisions this design implements, locked exactly as recommended:**

| # | Decision | Locked as |
|---|---|---|
| A | SI-006 naming | The B2.3.x YouTube evidence roadmap/design docs are the authority — no SI-006 document defines B2.3.4. (SI-006 itself is a separate, not-yet-started, company-wide initiative, confirmed via full-repository search — see §2.) |
| B | B2.3.4 scope | Channel-analytics ingestion only. `change_detection_events` ingestion deferred to a separate future phase. |
| C | `analytics` validation | Minimal/tolerant — present and a `dict`. No structural validation of `rows`/`columnHeaders`, and no cross-check against `metrics_requested`. |
| D | Legacy fixtures | The two real legacy fixtures, missing four required fields at once, are rejected by ordinary validation, not special-cased. |
| E | Migration | Same B2.3.3 multi-gate sequence — proposal text now, standalone SQL review later, explicit apply authorization later, independent verification later. Nothing applied in this pass. |
| F | Documentation | A real design artifact — this document — is committed alongside the six code/test/SQL files, counted as a separate, seventh artifact. |

---

## 1. Purpose

B2.3.1 built the live `youtube_evidence` schema, including `channel_analytics_snapshots` — fully specified, RLS-enabled, zero rows, since the original migration. B2.3.2 and B2.3.3 each closed the ingestion gap for one of the other three snapshot tables (`channel_snapshots`, `video_inventory_snapshots`). This document designs — and, per the founder's explicit implementation authorization, also builds and tests — the fourth and final currently-live adapter:

```
analytics_snapshot.py                      collector.py
       │                                         │
       │ data/analytics/channel_analytics_<ts>.json   │ logs/collection_<ts>.json
       ▼                                         ▼
        \_____________  B2.3.4 ingestion adapter  _____________/
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                            ▼
   youtube_evidence.collection_runs   youtube_evidence.channel_analytics_snapshots
      (parent row, only if missing,       (this design's actual subject)
       reusing collection_runs.py
       unchanged — §7)
```

`change_detection_events` ingestion is explicitly out of scope (Decision B) — one source passage in the existing docs ties change-detection's snapshot-ID resolution to "future B2.3.4," but `change_detection.py` itself was mid-edit, outside this ingestion project, at the time this scope was locked. Deferring it to its own later phase, rather than silently bundling it in, was the founder's explicit call, not an inferred one.

## 2. Scope and Non-Goals

**In scope:** the ingestion path for `analytics_snapshot.py`'s JSON output into `youtube_evidence.channel_analytics_snapshots`, including the same minimal `collection_runs` parent handling B2.3.2/B2.3.3 already use.

**Explicitly out of scope, per the locked decisions and direct instruction:**
- Modifying `analytics_snapshot.py`, `collector.py`, or any other acquisition script. Nothing found in this investigation motivates touching it — it already works and is already tested.
- `quota_ledger.py` or any quota-governance enforcement (§8). Ingestion reads JSON files already on disk; it makes no YouTube API calls.
- `change_detection.py` or `change_detection_events` ingestion (Decision B) — a separate future phase.
- The Supabase schema itself. No `ALTER TABLE`, no new column, no new table — `channel_analytics_snapshots` already exists, fully built, since the B2.3.1 migration.
- MCP configuration (B2.3.5) — untouched.
- Any structural validation of `analytics`'s internal shape beyond "present and a dict" (Decision C).
- Applying the grant/policy migration (§8), live ingestion, idempotency testing against the live database, staging, committing, or pushing. All of these remain later, separately-gated steps (§11).
- "SI-006" as an authority for this design. A full-repository search (this investigation) confirmed SI-006 refers to a separate, not-yet-started, company-wide "Knowledge Operating System" initiative (per `Deep_Documentation/00_Index.md`), explicitly walled off from the YouTube evidence pipeline by the B2.3.2 design doc's own "Independence from SI-006/KOS" section (§6.8 there). The actual authority for this design is the B2.3.x roadmap's own documents: `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` and this file (Decision A).

## 3. Live schema — `youtube_evidence.channel_analytics_snapshots`

**PROVEN — live Supabase evidence** (queried directly against project `wytwkhgkkvokgkbqwtxd`, read-only, during the B2.3.4 investigation gate). This table already exists, fully built, since the original B2.3.1 migration — nothing here is designed from scratch.

**Columns (15):** `snapshot_id uuid` PK, `schema_version text NOT NULL`, `snapshot_type text NOT NULL` (CHECK = `'youtube_channel_analytics'`), `generated_at_utc timestamptz NOT NULL`, `source text NOT NULL` (CHECK = `'youtube_analytics_api'`), `api_version text NOT NULL` (CHECK = `'v2'`), `collection_id uuid` (nullable, FK → `collection_runs`), `channel_id text NOT NULL`, `reporting_start_date date NOT NULL`, `reporting_end_date date NOT NULL`, `metrics_requested text[] NOT NULL`, `analytics jsonb NOT NULL`, `retrieval_metadata jsonb NOT NULL`, `source_file text` (nullable), `ingested_at_utc timestamptz NOT NULL default now()`.

**Constraints (8 named, beyond per-column NOT NULLs):** the three constant-value CHECKs above, plus `channel_analytics_snapshots_period_valid` — `CHECK (reporting_end_date >= reporting_start_date)`, a cross-field constraint with no analogue in `channel_snapshots` or `video_inventory_snapshots` — plus `channel_analytics_snapshots_channel_time_uq` — `UNIQUE (channel_id, generated_at_utc)` — plus the PK and the `collection_id` FK.

**Indexes (5):** the PK index, the unique-constraint's index, `channel_analytics_snapshots_channel_time_idx (channel_id, generated_at_utc DESC)`, `channel_analytics_snapshots_period_idx (channel_id, reporting_start_date, reporting_end_date)`, `channel_analytics_snapshots_collection_idx (collection_id)`. Materially more indexes than the other three snapshot tables — this table was built with the "analytics for a period" read pattern in mind from the start.

**RLS / policies / triggers / grants, as of the investigation:**
- RLS is **enabled**, with **zero policies** — confirmed two independent ways (direct `pg_policies` query, and `get_advisors(security)` flagging `rls_enabled_no_policy` on this exact table).
- The `forbid_mutation()` append-only trigger fires `BEFORE UPDATE` and `BEFORE DELETE`, same as every other evidence table.
- Grants: only `postgres` (full) and `service_role` (`SELECT`, `INSERT`). `youtube_ingest` has **neither a grant nor a policy** here — confirmed three independent ways (table-scoped grants query, `youtube_ingest`'s full cross-schema grant list, `get_advisors`). §8 addresses closing this gap; nothing in this design applies that fix yet.

**Row counts at investigation time:** `collection_runs`=1, `channel_snapshots`=1, `video_inventory_snapshots`=1, `channel_analytics_snapshots`=**0**, `change_detection_events`=0.

**Migrations applied (3, exactly, as of this design):** `20260814045608_b2_3_1_youtube_evidence_foundation`, `20260814093130_b2_3_2_youtube_ingest_role_and_policies`, `20260814160151_b2_3_3_video_inventory_grant_and_policy`. No B2.3.4 migration exists yet.

### 3.1 Real vs. synthetic evidence — fixture inventory

Three real `channel_analytics_*.json` files exist on disk, none synthesized for this design:

| Field | `channel_analytics_20260812_172513.json` | `channel_analytics_20260812_173839.json` | `channel_analytics_20260812_192340.json` |
|---|---|---|---|
| `snapshot_id` | **absent** | **absent** | present, valid UUID |
| `source` | **absent** | **absent** | `"youtube_analytics_api"` |
| `api_version` | **absent** | **absent** | `"v2"` |
| `retrieval_metadata` | **absent** | **absent** | present, full object |
| `collection_id` | absent (not itself a failure — nullable) | absent (not itself a failure — nullable) | present, valid UUID |
| `reporting_period`, `metrics_requested`, `analytics` | present | present | present |

The two smaller files predate the four now-required fields, the same situation B2.3.2 found for two of its own three real channel snapshots and B2.3.3 found for one of its own. Per Decision D, these two are rejected by the ordinary required-field check — the fixture inventory is not fixed by cleverer mapping, for the same reason B2.3.2 §5 gave: `snapshot_id` is the table's primary key, and there is no truthful value to derive it from when the source never had one.

All three real fixtures currently show `analytics.rows == [[0, 0, 0, 0, 0, 0, 0, 0]]` — every requested metric is zero in every real fixture that exists today. No real fixture demonstrates non-zero analytics values, and none demonstrates a genuinely empty `analytics.rows == []` (a real, documented possible API response, distinct from "one row of zeros"). §4 and the test suite (§6) treat that distinction as real and do not conflate the two.

### 3.2 Evidence fidelity — do not assume symmetry with B2.3.2/B2.3.3

This table is **not** a passthrough table the way the other three largely are. Four genuine differences, each confirmed against the live schema rather than assumed:

1. **No extra evidence wrapper.** `channel_snapshots` has a nested `evidence.raw_response` object; `video_inventory_snapshots` preserves per-item `video_details` raw blobs. `channel_analytics_snapshots` has neither — its `analytics` field already *is* the complete, untouched API response, and there is no `raw_response` column on this table at all.
2. **Real reshaping required, not pure passthrough.** The source JSON nests the period as `reporting_period: {start_date, end_date}`. The live table has no `reporting_period` column — it has two flat, native `date` columns, `reporting_start_date` and `reporting_end_date`. §5 extracts these explicitly.
3. **A real type-handling change, not just a shape change.** `metrics_requested` is a native Postgres `text[]` column, not `jsonb` — unlike every other structured field this codebase has mapped so far. §5 and §6 treat this as load-bearing, not stylistic.
4. **Different uniqueness semantics.** The table comment states: *"Multiple rows legitimately share the same reporting period — Analytics data can be revised after initial reporting, so repeat observations of one period are evidence, not duplicates."* The `UNIQUE` constraint is on `(channel_id, generated_at_utc)` — the retrieval timestamp — not on the reporting period. Two rows covering the identical week are explicitly intended to coexist. This design adds no domain-level de-duplication logic at the ingestion layer; the schema already made that call.

## 4. Validation spec — `validate_channel_analytics_snapshot(doc)`

Implemented in `src/ingestion/mappings.py`. Same 8-field required-envelope core as both existing validators — `snapshot_id`, `schema_version`, `snapshot_type`, `generated_at_utc`, `source`, `api_version`, `channel_id`, `retrieval_metadata` (`REQUIRED_ANALYTICS_KEYS`) — `collection_id` deliberately excluded, nullable everywhere in this codebase, never required. Beyond that core:

- **`reporting_period`** — must be present and a `dict`; must contain `start_date` and `end_date`, both parseable via `date.fromisoformat(...)` (a new `_is_valid_date` helper, parallel to and deliberately separate from the existing `_is_valid_timestamp` — these are plain `"YYYY-MM-DD"` strings, not timestamps). If both parse, `end_date >= start_date` is checked in Python, replicating the live `channel_analytics_snapshots_period_valid` CHECK constraint at the application layer, so a bad file is rejected with a clear message instead of surfacing as a raw Postgres constraint violation.
- **`metrics_requested`** — must be present and a list; every element must be a `str`. Stricter than `video_inventory_snapshots`' "just a dict" per-item precedent, because this targets a `NOT NULL text[]` column, not a loosely-typed `jsonb` blob.
- **`analytics`** (Decision C) — must be present and a `dict`. Nothing about `rows`, `columnHeaders`, or row-length-vs-`metrics_requested` is checked. This is a deliberate, decision-backed limit: dedicated tests (`test_analytics_empty_dict_is_accepted`, `test_analytics_with_empty_rows_is_accepted`, `test_analytics_row_length_mismatch_with_metrics_requested_is_not_checked`) prove the limit is intentional, not missing coverage.
- Existing-pattern checks carried over unchanged: `snapshot_id`/`collection_id` UUID validity when present, `generated_at_utc` timestamp validity, `snapshot_type == 'youtube_channel_analytics'`, `source == 'youtube_analytics_api'`, `api_version == 'v2'`.
- **Truthy-trap discipline** (same lesson as `video_count` in B2.3.3): every check above uses presence (`"x" not in doc` / `doc.get("x") is None`), never truthiness — an empty-but-present `rows: []`, or a genuinely empty `analytics: {}`, must never be misread as "missing."

**Decision D in practice.** The two legacy fixtures (§3.1) are missing `snapshot_id`, `source`, `api_version`, and `retrieval_metadata` at once — all four are named explicitly in the rejection message (`test_legacy_analytics_snapshot_rejected_naming_every_missing_field`), and `collection_id` is asserted **not** named, since its absence is not itself a validation failure. This proactively applies the exact lesson B2.3.3's own test suite learned the hard way for its equivalent legacy fixture (its first version of that same test wrongly asserted `collection_id` would be named; caught and fixed before delivery).

## 5. Mapping spec — `map_channel_analytics_snapshot(doc, source_file)`

Implemented in `src/ingestion/mappings.py`, directly below the validator. Caller must run `validate_channel_analytics_snapshot(doc)` first — this function assumes the document already passed.

```python
def map_channel_analytics_snapshot(doc, source_file):
    reporting_period = doc["reporting_period"]
    return {
        "snapshot_id": doc["snapshot_id"],
        "schema_version": doc["schema_version"],
        "snapshot_type": doc["snapshot_type"],
        "generated_at_utc": doc["generated_at_utc"],
        "source": doc["source"],
        "api_version": doc["api_version"],
        "collection_id": doc.get("collection_id"),
        "channel_id": doc["channel_id"],
        "reporting_start_date": reporting_period["start_date"],
        "reporting_end_date": reporting_period["end_date"],
        "metrics_requested": doc["metrics_requested"],
        "analytics": doc["analytics"],
        "retrieval_metadata": doc["retrieval_metadata"],
        "source_file": source_file,
    }
```

Two genuine transformations, unlike every mapping function before this one, which are near-total passthrough into `jsonb`:

1. **`reporting_start_date`/`reporting_end_date` are extracted** out of the nested `reporting_period` object into flat top-level values, matching the live table's flat `date` columns (§3.2, difference 2). The returned row has no `reporting_period` key at all (`test_map_channel_analytics_snapshot_has_no_reporting_period_key`).
2. **`metrics_requested` stays a plain Python `list`** all the way through this function — verified by `type(row["metrics_requested"]) is list` (`test_map_channel_analytics_snapshot_metrics_requested_stays_a_plain_list`). Casing is preserved verbatim (e.g. `estimatedMinutesWatched`) — these are literal YouTube Analytics API metric identifiers a future script would reuse verbatim; translating casing would be actively harmful, not a style choice.

**The `Json()`-wrapping split — the single most load-bearing implementation detail in this design.** It happens one layer down, in `analytics_ingest.py`'s insert function, not here:

```python
cur.execute(
    """insert into youtube_evidence.channel_analytics_snapshots (...) values (...)
       on conflict (snapshot_id) do nothing returning snapshot_id;""",
    {
        **row,
        # metrics_requested passed through UNWRAPPED -- targets a native
        # text[] column, not jsonb. psycopg2 adapts a Python list to a
        # Postgres array automatically. Wrapping it in Json(...) here
        # would be a real type mismatch against the live column, not a
        # style choice.
        "analytics": Json(row["analytics"]),
        "retrieval_metadata": Json(row["retrieval_metadata"]),
    },
)
```

`analytics` and `retrieval_metadata` target `jsonb` columns and are wrapped in psycopg2's `Json(...)` adapter, exactly like every prior adapter's structured fields. `metrics_requested` targets `text[]` and is passed through bare, letting psycopg2's native list→array adapter handle it — `Json([...])` against a `text[]` column would be a real bug, not a style inconsistency. `test_ingest_passes_metrics_requested_as_plain_list_not_json_wrapped` (§6) asserts both halves of this split directly against the executed SQL parameters, not just the SQL text — proving the distinction is real and enforced, not merely documented.

## 6. Test coverage

**Regression discipline followed:** the pre-existing 85-test baseline was confirmed passing, unmodified, before any new file was written (per the founder's explicit "run the 85-test baseline first" instruction), and again after every new file landed.

Three new test files, mirroring established B2.3.2/B2.3.3 shapes:

| File | Tests | Mirrors |
|---|---|---|
| `tests/test_ingestion_analytics_mappings.py` | 29 | `test_ingestion_video_mappings.py` — validate/map, pure, no DB |
| `tests/test_ingestion_analytics.py` | 9 | `test_ingestion_video_inventory.py`'s 8-test shape, plus 1 new |
| `tests/test_channel_analytics_grant_proposal.py` | 10 | `test_video_inventory_grant_proposal.py`'s 10 static checks |

**`test_ingestion_analytics_mappings.py` (Tier 0 — pure logic, no network, no Supabase):** the one real current-shape fixture validates and maps correctly, field for field; both legacy fixtures rejected, naming all four actually-missing fields and not naming `collection_id` (§4); invalid/null `collection_id`; wrong `snapshot_type`/`source`/`api_version`; `reporting_period` missing/not-an-object/missing `start_date`/missing `end_date`/unparseable date/`end < start` rejected, `end == start` valid; `metrics_requested` missing/not-a-list/non-string-element rejected, empty list valid; `analytics` missing/not-a-dict rejected, empty dict accepted, empty `rows` accepted, row-length-vs-`metrics_requested` mismatch not checked (Decision C, proven directly); mapping tests confirming field-by-field extraction, the missing `reporting_period` key, the plain-list `metrics_requested`, verbatim `analytics`/`retrieval_metadata` preservation (`is` identity checks), and null-`collection_id` passthrough for standalone runs.

**`test_ingestion_analytics.py` (adapter orchestration):** pure local dry run with no connection; `dry_run=False` with no connection raises `ValueError`; malformed file rejected before any DB call; full dry run against a live connection issues zero writes; first real insert orders the `collection_runs` parent before the `channel_analytics_snapshots` child and commits once; a duplicate `snapshot_id` is a clean skip, not an error; a failure after the parent insert rolls back cleanly, leaving no orphaned parent row; ingestion fails closed (raises, does not silently proceed) when a `collection_id` has no matching `logs/collection_*.json` and no existing `collection_runs` row. Plus, new to this table: `test_ingest_passes_metrics_requested_as_plain_list_not_json_wrapped`, which inspects the actual executed SQL parameters (not just the SQL text) to confirm `metrics_requested` is a plain `list` while `analytics`/`retrieval_metadata` are genuinely `Json`-wrapped in the same call — the direct test for §5's load-bearing type-correctness risk.

**`test_channel_analytics_grant_proposal.py` (static-only, never executes the SQL):** proposal file exists; no `bypassrls`; no `superuser`/`createrole`/`createdb`; does not create a new role; exactly one policy, scoped to `channel_analytics_snapshots`; the policy is scoped to `youtube_ingest` only; no `update`/`delete` grant; does not mention `channel_snapshots`/`video_inventory_snapshots`/`collection_runs`/`change_detection_events`; no password; no redundant schema-level `USAGE` grant (already granted schema-wide by the applied B2.3.2 migration).

**Full suite result: 133 passed, 0 failed** (85 baseline + 29 + 9 + 10 = 133). No test was skipped, xfailed, or modified from its baseline form to make this pass.

## 7. Collection-run reuse

**PROVEN — repository evidence.** `collection_runs.py` takes only `conn`, `collection_id`, and `dry_run` — nothing channel/video/analytics-specific; its own docstring already names itself as designed for a third caller.

**PROVEN — live schema evidence.** `channel_analytics_snapshots.collection_id` already has a live FK to `collection_runs.collection_id`, confirming the schema was built expecting this exact reuse.

`analytics_ingest.py` calls `ensure_collection_run()` exactly as `video_inventory_ingest.py` does today — no new collection-run code, no modification to `collection_runs.py` (hash-verified unchanged, §10). When `collection_id` is present and unresolved, the same B2.3.3 Decision 2 fail-closed behavior applies: a `collection_id` with no matching `logs/collection_*.json` and no existing `collection_runs` row raises `IngestRejected` rather than proceeding with an unresolvable FK (`test_ingest_fails_closed_when_no_matching_collection_log_exists`).

## 8. Security / migration (Decision E)

**Current live state, confirmed three independent ways during the investigation gate:** `youtube_ingest` has zero grants and zero policies on `channel_analytics_snapshots`. A migration is unambiguously required before any live write to this table is possible.

**`NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_GRANT_PROPOSAL.sql`** (new, text only, not applied) follows the exact B2.3.3 shape: a single-purpose file granting `SELECT, INSERT` on `youtube_evidence.channel_analytics_snapshots` to `youtube_ingest`, plus one `FOR ALL` policy scoped to that table only. No new role — schema-level `USAGE` is already granted from the applied B2.3.2 migration. No `UPDATE`/`DELETE` grant — moot, since `forbid_mutation` blocks both regardless of grants.

**Gating sequence (Decision E — the same one B2.3.3 used):**
1. Design and code review (this document, plus the six implementation files — this gate).
2. The grant-proposal SQL reviewed standalone, as its own artifact.
3. Explicit, unambiguous founder authorization to apply it.
4. Independent read-only verification that the applied grant/policy matches the reviewed text.
5. Only then: a dry run against a real fixture, first live ingestion, an idempotency re-run, and read-only verification at each step.

**Nothing in this document authorizes writing (beyond producing the proposal text itself), reviewing standalone, or applying that migration.** Steps 2 through 5 above are future, separately-gated work.

## 9. Quota governance / API-call boundary

Ingestion-layer code never calls the YouTube API — it only reads JSON files `analytics_snapshot.py` already wrote to disk. `analytics_ingest.py` does not import, call, or reference `quota_ledger.py`, and has zero interaction with quota policy at all. This mirrors the identical, pre-existing non-relationship `video_inventory_ingest.py` already has with quota governance — not a gap this design leaves open, but a boundary that never needed crossing. `analytics_snapshot.py` itself (which does call the YouTube Analytics API, and does carry its own `analytics_call_frequency_v1` quota sub-policy) is unmodified by this design — confirmed unmodified because it was never copied into this implementation pass at all (§10).

## 10. Implementation record

**Seven artifacts this gate, exactly as clarified** — six code/test/SQL files, plus this document counted separately, per the founder's explicit instruction not to let the design artifact silently merge into the implementation-file count the way prior B2.3.x design docs were referenced but never committed:

| # | File | Change | Lines |
|---|---|---|---|
| 1 | `src/ingestion/mappings.py` | Modified — module docstring updated; new `_is_valid_date` helper; new `channel_analytics_snapshots` section appended (`REQUIRED_ANALYTICS_KEYS`, `validate_channel_analytics_snapshot`, `map_channel_analytics_snapshot`). Zero changes to the existing `channel_snapshots`/`collection_runs`/`video_inventory_snapshots` sections — confirmed by direct diff against the pre-B2.3.4 baseline copy, not merely by intent. | 524 (was 360) |
| 2 | `src/ingestion/analytics_ingest.py` | New | 206 |
| 3 | `tests/test_ingestion_analytics_mappings.py` | New | 351 |
| 4 | `tests/test_ingestion_analytics.py` | New | 310 |
| 5 | `NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_GRANT_PROPOSAL.sql` | New, text only — never submitted to `apply_migration` | 57 |
| 6 | `tests/test_channel_analytics_grant_proposal.py` | New | 108 |
| 7 | `NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_INGESTION_DESIGN.md` (this file) | New — the design artifact itself, Decision F | — |

**Confirmed unmodified, by SHA-256 comparison against the recorded pre-B2.3.4 baseline, not by assumption:** `video_inventory_ingest.py`, `channel_snapshot_ingest.py`, `collection_runs.py`, `db.py`, `errors.py`, `src/ingestion/__init__.py`, and both pre-existing SQL proposal files (`NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql`, `NIK_YOUTUBE_B2_3_3_VIDEO_INVENTORY_GRANT_PROPOSAL.sql`). `analytics_snapshot.py`, `quota_ledger.py`, and `change_detection.py` were never present in this implementation sandbox at all, so their absence from every diff is structural, not merely observed.

**Test result:** 133 passed, 0 failed — the 85-test baseline plus 48 new tests (§6), confirmed by a full, unfiltered suite run after every file above was in place.

**Explicitly NOT done in this implementation gate:** the grant-proposal migration (§8) was not applied. No live database write occurred — no row was inserted into any Supabase table. No file was staged, committed, or pushed. No credential was opened, printed, or transmitted. Nothing here should be read as authorization for any of those; each remains its own future, explicit gate (§11).

## 11. Remaining gates, in order

1. Founder review of this implementation (this document, the 133-test result, the six code/test/SQL files).
2. A separate, explicit founder gate for staging → commit → push, mirroring B2.3.3's own staging/commit gates exactly.
3. Standalone review of `NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_GRANT_PROPOSAL.sql` as its own artifact (§8).
4. Explicit, unambiguous founder authorization to apply that migration.
5. Independent read-only verification that the applied grant/policy matches the reviewed text.
6. Dry run against `data/analytics/channel_analytics_20260812_192340.json` — the one real, schema-conformant fixture (§3.1).
7. First live ingestion, an idempotency re-run against the same file, and read-only verification at each step.
8. Close-out audit, matching the B2.3.2/B2.3.3 implementation-report precedent.

**Stopping here, per the implementation gate's own instruction: no migration applied, no live ingestion, no git staging/commit/push.**
