# NIK YouTube → Supabase Evidence Schema Design

**Version:** 1.1 — Approved with 3 clarifications, 2026-08-14 (v1.0's unqualified `gen_random_uuid()` call in §9 is superseded by the `extensions`-qualified form below; v1.0's undocumented `detection_run_id` FK question is resolved as "intentionally no FK" in §6.2. Full record in §13.)
**Status:** APPLIED 2026-08-14 to `wytwkhgkkvokgkbqwtxd` as migration `20260814045608_b2_3_1_youtube_evidence_foundation`. Schema is live and empty (0 rows in all five tables) — read-only post-apply verification in §14. B2.3.2 has not started.
**System:** NIK YouTube Integration
**Stage:** B2.3.1 — Supabase Evidence Schema Design
**Date:** 2026-08-14 (v1.0 same day; revised same day per founder review)

**Scope of this pass:** Inspection and design only. No migration was applied, no table was created, no code was modified, no existing contract was modified, no MCP was configured, and nothing was committed or pushed. The only writes in this session were the two files delivered alongside this one. Every Supabase call made during this work was read-only (`list_projects`, `list_tables`, `list_migrations`, `list_extensions`, and a documentation search) — see §4.

---

## 1. Purpose

B2.2 made YouTube API acquisition reliable: OAuth, quota governance, and local JSON snapshots are working and tested against the real (currently zero-subscriber, zero-video) "Now I Know NIK" channel. That evidence currently lives only as timestamped JSON files under `integrations/youtube/data/` and `integrations/youtube/logs/`. Nothing outside a script that already knows those file paths can read it — Claude included.

This document designs the minimum Supabase schema required to move that evidence into a canonical, queryable, persistent store, **without losing anything the JSON files currently capture**, so that B2.3.5's read-only MCP capability layer (later) has somewhere real to query. It resolves the nine points requested, and nothing beyond them — no MCP configuration, no ingestion code, no schema for the Quota Ledger (out of scope: not one of the five requested tables; see §2).

## 2. Scope and Non-Goals

**In scope:** the five tables named in the brief — `collection_runs`, `channel_snapshots`, `video_inventory_snapshots`, `channel_analytics_snapshots`, `change_detection_events` — as a proposed schema, plus the reasoning behind every structural choice.

**Explicitly out of scope for this pass:**
- The Quota Ledger (`logs/quota_ledger.jsonl`, per `NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md`). It is not one of the five requested tables, and it is operational governance data about API calls, not evidence about YouTube itself. Its schema doc is used below only as a source of house conventions (append-only JSONL, `call_id`/`collection_id` linkage, fail-closed reasoning) that this design deliberately mirrors.
- MCP configuration of any kind (B2.3.5).
- Ingestion code that would actually read the JSON files and `INSERT` them (B2.3.2–B2.3.4).
- Any change to `NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md`, `NIK_YOUTUBE_CHANGE_DETECTION_CONTRACT.md`, or any `src/*.py` file, even though §3 below finds real gaps in two of them.
- SI-003A / SI-006 knowledge-asset design. §6.7 addresses only how this schema stays out of that system's way.

## 3. Inputs Reviewed

| Source | Used for | Note |
|---|---|---|
| `NIK_YOUTUBE_SNAPSHOT_SCHEMA.md` | Canonical field list for channel/video/analytics snapshots, plus two dated Implementation Notes | Complete; the two Implementation Notes (`pagination_completed` semantics, the two indistinguishable no-snapshot causes) are load-bearing for §8's mapping notes |
| `NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md` | OBSERVED/DERIVED/INTERPRETATION/ASSUMPTION discipline; append-only rule (§5); snapshot type list (§4) | **File is truncated** — it stops mid-sentence inside the §6 storage tree, with no closing code fence and no content after it. Confirmed by byte count (3,601 bytes; the visible text ends exactly at EOF). Treated as an incomplete draft; code and real output files were used as ground truth wherever this contract is silent. |
| `NIK_YOUTUBE_CHANGE_DETECTION_CONTRACT.md` | Evidence-class definitions (OBSERVED/DERIVED/INTERPRETATION/ASSUMPTION) for change events | **File is truncated** — it stops mid-§4 ("Comparison Requirements"), inside an unclosed ```` ```text ```` block, after only ~1,050 of its 1,758 bytes render as prose. Same fallback as above: `src/change_detection.py` and a real `change_*.json` file are the ground truth for this table's actual shape. |
| `NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md` v1.2 | House conventions — JSONL append-only discipline, `call_id`/`collection_id` linkage pattern, "Missing ≠ Zero," fail-closed reasoning | Complete. Out of scope as a table (§2), but its reasoning style is the template this document follows. |
| `NIK_YOUTUBE_CAPABILITY_MAP.md` | KOS Boundary (§9), Agent Boundary (§10), Governance Principle (§15) | Complete. Directly grounds the schema-isolation (§6.7) and RLS (§6.4) recommendations below. |
| `src/channel_snapshot.py`, `video_inventory.py`, `analytics_snapshot.py`, `change_detection.py`, `collector.py` | Exact as-implemented field names, types, and nullability | Read in full. This is the actual source of truth for §8 — contracts describe intent, code and its output are what actually exists. |
| 6 real output files, all dated 2026-08-12 (one channel snapshot, one video inventory, one analytics snapshot, one change-detection record, one collection log, one capability-discovery log) | Ground-truth examples | Every column in §8 is checked against a real file, not just contract prose. |
| Live Supabase project "NIK Automation Project" (`wytwkhgkkvokgkbqwtxd`) | Current `public` schema state | See §4 — checked directly, not assumed. |
| "B2.3 reconciliation report" | — | **Not found.** Searched `D:\YouTube` root, `integrations\youtube` (top level and `data`/`logs`/`src`), `Deep_Documentation`, `Video`, and `details`. Rather than rely on a secondhand summary of a document I could not open myself, I re-verified its central claim directly against the live database (§4). If the report exists somewhere else and matters for this review, point me to it and I'll reconcile against it. |

Two things worth flagging up front because they're genuine findings, not restatements of what was asked: **two of the five contract documents this design was told to use are themselves incomplete drafts that cut off mid-section**, and **the real `change_*.json` file identifies its two snapshots by raw Windows filesystem path with no snapshot ID at all** — which is exactly the gap point 6 of the brief anticipated. Both are addressed below (§3 table above, and §6.6 / §8.5).

## 4. Live Supabase State — Verified, Not Assumed

Per this project's standing rule, the claim that Supabase currently has no NIK tables and no migrations was checked directly rather than taken on the report's word:

- `list_projects` → one project, **"NIK Automation Project"**, id `wytwkhgkkvokgkbqwtxd`, region `ap-northeast-1`, Postgres 17.6, status `ACTIVE_HEALTHY`, created 2026-08-12.
- `list_tables` (schema `public`, verbose) → **`[]`** — zero tables.
- `list_migrations` → **`[]`** — zero migrations.
- `list_extensions` → `pgcrypto` (1.3) and `uuid-ossp` (1.1) are already installed, among ~80 available-but-uninstalled extensions. Both are used below (`gen_random_uuid()`, §9).

Confirmed: the report's central claim is accurate. Design proceeds from a genuinely empty database.

## 5. Design Principles Carried Forward

Nothing below is invented from scratch. Every principle already exists somewhere in the founder's own contracts; this section just names where, so the SQL in §9 doesn't read as arbitrary.

- **Evidence, not conclusions** (Data Collection Contract §2; Capability Map §4.4). Snapshots store OBSERVED data. A snapshot row is never edited to reflect a later interpretation.
- **Append-only, immutable history** (Data Collection Contract §5): "A later API response must not overwrite an earlier snapshot... Historical snapshots are append-only." This is the direct justification for the immutability trigger in §6.3/§9.
- **Missing ≠ Zero** (Ledger Schema §4.4, §10.2): absence of a record must never be silently read as a zero/negative observation. This shows up below in why `previous_value`/`current_value` stay nullable and why an unresolvable snapshot reference is stored as `NULL` rather than dropped or guessed.
- **Fail-closed governance** (Ledger Schema §10.4, §10.6; Capability Map §7, §10): when something can't be verified, the system should refuse rather than assume the safe case. This shows up in the `CHECK` constraints in §9 that reject unrecognized `snapshot_type`/`source`/`api_version` values rather than silently accepting them.
- **Stable IDs over paths** (the brief's own point 6, and implicitly Ledger Schema §9's reasoning about why `snapshot_id` can't be attached to a ledger entry after the fact). Addressed in §6.6.
- **YouTube is a source of record, not the KOS** (Capability Map §9): "KOS should retain provenance for durable knowledge." This schema exists to be the provenance the future KOS points at — never a place SI-006 writes into. Addressed in §6.7.

## 6. The Nine Resolved Design Questions

### 6.1 JSONB + indexed key columns vs. fully normalized columns

**The tension:** the four evidence tables wrap two different kinds of content. One layer is NIK's own envelope — IDs, timestamps, provenance, counts — which is stable, small, and exactly what the future MCP read tools will filter and sort on. The other layer is a third-party API's response shape (Google's `channel`/`video`/`analytics` resources), which NIK does not control, which is already deeply nested (thumbnails, branding, `contentDetails`, column headers + row arrays), and which Google can add fields to without notice.

**Options considered:**
- *Fully normalized* — a column (or child table) for every nested field, including inside `branding`, `raw_response`, and the Analytics `columnHeaders`/`rows` pair. Rejected: this fights the actual shape of an API NIK doesn't control, and a schema migration would be needed every time Google adds a field, which is not proportionate to a single-founder channel with zero videos today.
- *Fully JSONB* — one `payload jsonb` column per table, no typed columns at all. Rejected: it would push every query, including "give me the latest channel snapshot," through a JSON path expression, which works against the whole point of persisting this evidence somewhere queryable.
- *Hybrid (recommended)* — typed columns for the envelope (IDs, timestamps, `channel_id`, counts, provenance flags), JSONB for the API-shaped payloads (`raw_response`, `branding`, `videos`, `analytics`, `components`, `retrieval_metadata`).

This isn't a new philosophy — it's the same split the snapshot JSON already makes internally (a reshaped `channel` block sitting next to an untouched `evidence.raw_response` block). The hybrid approach just continues that pattern into the database rather than replacing it. Applied per table in §8 and §9.

One sub-decision inside this: **`video_inventory_snapshots.videos` stays a single JSONB array, not a normalized `video_inventory_items` child table**, at least for now. A per-video child table would be the more "correct" long-term shape once the channel has real videos and the MCP layer needs to query individual videos across snapshots. But today `video_count` is 0 in every real snapshot on disk, and normalizing an empty set is speculative complexity with no problem behind it yet — the same standard this project already applies to the operating-templates workbook ("which real production problem did this solve?"). A GIN index on `videos` (§6.5) keeps per-video lookups reasonably efficient in the meantime. **This is listed as a founder-approval item in §10**, because it's a real trade-off, not a technical fact — reasonable people could pick normalization now instead.

### 6.2 Primary/foreign keys and relationships

- `collection_runs.collection_id` (PK) — sourced directly; already a UUID in every real `collection_*.json`.
- `channel_snapshots.snapshot_id`, `video_inventory_snapshots.snapshot_id`, `channel_analytics_snapshots.snapshot_id` (PK each) — sourced directly.
- Each of the three snapshot tables carries a nullable `collection_id` FK to `collection_runs`, matching the source JSON exactly: the field is `null` when a snapshot script is run standalone (outside `collector.py`), and set when it's run as part of a collection. The FK is nullable, not optional-in-name-only — a `NOT NULL` here would reject a legitimate standalone snapshot.
- `change_detection_events` needs a synthetic PK (`event_id`) because **the source JSON has none at all** — see §6.6.

**The one real judgment call here:** should `change_detection_events.previous_snapshot_id`/`current_snapshot_id` reference `channel_snapshots` specifically, or be designed generically now so a future `entity_type = 'video'` change record could reference `video_inventory_snapshots` instead? Today, `change_detection.py` only ever compares `youtube_channel` snapshots (`get_latest_snapshots("youtube_channel")` is hardcoded), so a direct FK to `channel_snapshots` is 100% correct for every row that exists or can currently be produced. A generic/polymorphic design (e.g., a `snapshot_table` discriminator column plus no hard FK, or a shared "snapshot envelope" view every snapshot table feeds) would only pay off once video-level change detection is actually built — which Capability Map §14 lists as a later phase, not started. Recommendation: hard FK to `channel_snapshots` now; revisit as a schema revision when video-level change detection is real. **Approved as proposed, 2026-08-14 — see §13.**

**A second, related judgment call the founder raised directly (2026-08-14):** `change_detection_events.detection_run_id` (§6.9, §8.5) is a plain `uuid not null` with **no FK** — deliberately. It's tempting to ask whether it should reference `collection_runs.collection_id` instead of standing alone, since every other cross-table link in this schema is a real FK. It should not, for a concrete reason rather than a stylistic one: `collector.py`'s `components` list (§9's `collection_runs.components`) is hardcoded to exactly three entries — `channel_snapshot`, `video_inventory`, `analytics_snapshot` — and `change_detection.py` is not one of them. It is a separate, standalone script with its own execution lifecycle, never invoked by `collector.py` (confirmed directly from `collector.py`'s source, not assumed). `detection_run_id` identifies one *change-detection* execution — grouping the rows one run of `change_detection.py` produces (§8.5) — which is a different kind of event from one *collection* execution. Giving it a FK to `collection_runs` would assert a relationship the current system does not actually have: there is no `collection_id` a change-detection run belongs to. If `change_detection.py` is ever folded into `collector.py` as a fourth component, that would be the moment to reconsider — not before.

### 6.3 Immutability strategy

Data Collection Contract §5 states snapshots are immutable and append-only, and §5's language ("must not overwrite," "must not silently replace," "must not delete") reads as a hard requirement, not a suggestion. Two enforcement layers, not one:

1. **Application discipline** — the future ingestion code (B2.3.2+) only ever `INSERT`s, never `UPDATE`s.
2. **Database-level trigger** — a `BEFORE UPDATE OR DELETE` trigger on all five tables that raises an exception unconditionally (§9, `youtube_evidence.forbid_mutation()`). This matters because the realistic risk here isn't a hostile actor — Supabase's own `service_role` key, which the ingestion scripts will use, bypasses RLS by design (§6.4) and could otherwise `UPDATE` freely. The trigger is what actually makes "immutable" true even for a bug in trusted ingestion code, not just for outside access.

A correction to an already-ingested row is never an `UPDATE` under this design — it's a new row (a new snapshot, or in the JSONL-ledger sense, a new event). This matches how the Quota Ledger's own append-only reasoning already works (Ledger Schema §5, §10.3).

### 6.4 RLS / security model

Capability Map §10 ("Agent Boundary") is explicit that agents must never get unrestricted direct access, and that a capability layer should control access, scope, and logging. That principle is design guidance for B2.3.5 (the MCP layer itself), but it also shapes what the database should default to *before* that layer exists.

Checked against Supabase's own documentation (`search_docs`, "Using Custom Schemas") rather than assumed: exposing any schema to the Data API requires two explicit steps — adding it to **Exposed Schemas** in the project's API settings, and running `GRANT` statements for the roles that should reach it. Supabase's own tutorial default is to grant `anon`, `authenticated`, **and** `service_role` together. This design deliberately does **not** follow that default:

- `RLS` is enabled on all five tables, with **zero policies**. In Postgres, RLS-enabled-with-no-policies means only a role that bypasses RLS (`service_role`) can read or write via PostgREST — everyone else gets nothing, by default, with no policy to get wrong.
- Only `service_role` is granted schema/table access (§9). `anon` and `authenticated` are not granted anything — there is no product surface today that should let the public `anon` key read this data.
- The schema is **not** added to Exposed Schemas yet. There is no reason for PostgREST to expose evidence tables before B2.3.5 defines who's allowed to read them and how.
- The MCP layer's own read-only role/policy is explicitly **not** designed here — it belongs to B2.3.5, once the actual authentication shape of that layer is known. **Deferral confirmed by the founder, 2026-08-14 — see §13.**

**The capability boundary this is building toward (locked by the founder, 2026-08-14):**

```text
YouTube OAuth
     ↓
YouTube acquisition scripts
     ↓
local evidence
     ↓
Supabase youtube_evidence
     ↓
NIK YouTube Capability Layer  (B2.3.5)
     ↓
Claude
```

Claude does not get, at any stage of this design: YouTube OAuth credentials, the Supabase `service_role` key, arbitrary SQL access, or arbitrary Supabase table access. Everything Claude can eventually see about YouTube passes through the capability layer B2.3.5 will build — which is exactly what this section's RLS-deny-by-default and non-exposed schema are laying the groundwork for. This document does not build that layer; it makes sure nothing about *this* layer quietly forecloses it or quietly bypasses it.

### 6.5 Indexes for the five eventual read-only MCP tools

The MCP tools themselves are B2.3.5's design, not this one, but the five evidence tables strongly imply the read patterns they'll need: latest snapshot for a channel, video inventory as of/latest, analytics for a period, change history for an entity, and collection run history/status. Indexes below are sized to those patterns, not speculative ones. Full `CREATE INDEX` statements are in §9; summary:

| Table | Index | Serves |
|---|---|---|
| `collection_runs` | `(started_at_utc desc)` | Recent-runs listing |
| `collection_runs` | partial, `(started_at_utc desc) where success = false` | "Show me failed runs" without scanning successes |
| `channel_snapshots` | `(channel_id, generated_at_utc desc)` | "Latest snapshot for channel X" |
| `channel_snapshots` | `(collection_id)` | Join back to the run that produced it |
| `video_inventory_snapshots` | `(channel_id, generated_at_utc desc)` | Latest inventory |
| `video_inventory_snapshots` | GIN on `videos` (`jsonb_path_ops`) | "Which snapshot(s) contain video X" |
| `channel_analytics_snapshots` | `(channel_id, generated_at_utc desc)` | Latest analytics observation |
| `channel_analytics_snapshots` | `(channel_id, reporting_start_date, reporting_end_date)` | "Analytics for period X" |
| `change_detection_events` | `(entity_type, entity_id, generated_at_utc desc)` | Change history for one entity |
| `change_detection_events` | `(detection_run_id)` | Reconstruct one comparison run's full set of changes |

### 6.6 How change-detection references snapshots

This is the gap the brief called out by name, and it's real. `change_detection.py`'s `build_change_record()` links two snapshots like this, verbatim from the source:

```json
"previous_snapshot": { "path": "D:\\YouTube\\integrations\\youtube\\data\\snapshots\\channel_20260812_171041.json", "generated_at_utc": "2026-08-12T17:10:41.604142+00:00" }
```

A raw Windows filesystem path, not a `snapshot_id` — even though the function has already loaded the full snapshot JSON (including its real `snapshot_id`) into memory at that point and simply doesn't carry it forward into the output. That's a code-level gap, and fixing `change_detection.py` itself is explicitly out of scope for this pass (§2).

**What this design does instead, entirely at the ingestion layer (future B2.3.4, not built now):**
- `change_detection_events` gets real `previous_snapshot_id`/`current_snapshot_id` UUID columns, FK'd to `channel_snapshots.snapshot_id`.
- At ingestion time, each is resolved by matching the source JSON's `previous_snapshot.generated_at_utc` / `current_snapshot.generated_at_utc` against `channel_snapshots.generated_at_utc` for the same `channel_id` — timestamps in these files carry microsecond precision, so a collision is not realistically expected, but §9 adds `UNIQUE (channel_id, generated_at_utc)` on `channel_snapshots` specifically so that join is provably unambiguous rather than merely unlikely to collide.
- The original `{path, generated_at_utc}` object is **also** kept verbatim, in `previous_snapshot_source`/`current_snapshot_source` JSONB columns — so nothing from the source file is lost even though the path itself is never used as a live reference again.
- If a future ingestion run can't resolve a match (e.g., the referenced snapshot was never ingested), the FK columns stay `NULL` rather than the row being dropped or a guess being stored — "Missing ≠ Zero" applied to referential integrity, not just numeric values.

### 6.7 Preventing accidental mixing with SI-003A/SI-006 knowledge assets

Capability Map §9 draws this boundary explicitly: YouTube is a source system, NIK's integration produces "Operational Data + Knowledge Candidates," and the KOS is a separate downstream system that "should retain provenance for durable knowledge" — meaning the KOS is expected to point *at* this evidence, not absorb it.

Recommendation: a **dedicated Postgres schema**, `youtube_evidence`, not `public`. This is a structural guarantee, not a naming convention — grants, RLS, and (later) Data API exposure are all scoped at the schema level, so there's no query, migration, or future `SELECT *` that can accidentally treat an evidence row as a knowledge asset just because they happen to share a schema. When SI-006 is eventually designed, it gets its own schema (e.g. `knowledge`), and the two are structurally incapable of colliding.

The trade-off, confirmed against Supabase's own docs (§6.4): a non-`public` schema is **not** auto-exposed to the Data API. That's a feature here, not a cost — it means evidence stays invisible to PostgREST by construction until B2.3.5 deliberately exposes it, rather than needing everyone to remember not to query it. **This schema-naming choice is a founder-approval item (§10)** because it has a real downstream consequence: B2.3.5's MCP layer will need to either (a) get `youtube_evidence` added to Exposed Schemas plus the narrow grants it actually needs, or (b) connect via a direct Postgres connection rather than the PostgREST-based Supabase client library. Either is fine; it just needs to be a chosen path, not a surprise.

### 6.8 Migration/versioning strategy

Two separate version axes, kept separate on purpose:

1. **Database migration version** — managed by Supabase's own migration history (`list_migrations`, currently empty). This design proposes **one consolidated migration** (§9), not one migration per table, because all five tables are one cohesive foundation being introduced together — splitting them would create five migrations with no meaningful checkpoint between them (a partially-applied subset of these five tables has no independent value). This mirrors how the founder's own contracts treat "foundation" work as one cohesive document (Data Collection Contract v1.0, Change Detection Contract v1.0) rather than piecemeal.
2. **Source schema version** — every JSON file already self-reports a `schema_version` (currently `"1.0"` everywhere except the Ledger's `"1.2"`, which is out of scope here). Each table keeps this as a plain `schema_version text` column, independent of the DB migration version, so if the JSON producers evolve their own shape later (the way the Ledger Schema already went from v1.0 → v1.1 → v1.2), ingested rows stay traceable to exactly which producer version wrote them — without that being conflated with which DB migration created the column that holds it.

### 6.9 Exact lossless mapping

Resolved in full in §8, one subsection per table. Three things worth naming up front, since "lossless" should mean the reader can tell exactly what's original vs. added:

**Columns added that do not exist in any source JSON** (all additive, none of them drop anything): `ingested_at_utc` and `source_file` on every table (when this row was written to Supabase, and which file it came from — pure bookkeeping); `event_id` and `detection_run_id` on `change_detection_events` (the source has no ID of its own at all, per §6.6); `previous_snapshot_id`/`current_snapshot_id` on `change_detection_events` (resolved, not sourced — the raw path is kept alongside them, not replaced).

**One structural asymmetry preserved deliberately, not "fixed":** `channel_snapshots` has a top-level `evidence.raw_response` object; `video_inventory_snapshots` has no top-level evidence field at all — instead, each item in `videos` optionally carries its own `video_details` raw blob, only when the enrichment call found a match. `channel_analytics_snapshots` has neither — its `analytics` field already *is* the full raw response (the schema doc's own 2026-08-12 Implementation Note says this explicitly, to explain why it isn't duplicated). The mapping in §8 follows each table's real, current shape rather than inventing a uniform "evidence" column that would misrepresent what the collectors actually produce today.

**`metrics_requested` is stored as a native Postgres `text[]`, not JSONB**, and its values are kept in YouTube's own camelCase (`estimatedMinutesWatched`, not `estimated_minutes_watched`) — these are literal API metric identifiers that a future script would reuse verbatim in another `reports.query()` call, so translating their casing would be actively harmful to round-tripping, not just a style choice.

## 7. Entity-Relationship Overview

```
collection_runs (collection_id PK)
        │
        │ 1 ──── N   (collection_id FK, nullable on all three)
        │
        ├── channel_snapshots (snapshot_id PK)
        ├── video_inventory_snapshots (snapshot_id PK)
        └── channel_analytics_snapshots (snapshot_id PK)

channel_snapshots (snapshot_id PK)
        │
        │ 1 ──── N  (previous_snapshot_id FK, nullable)
        │ 1 ──── N  (current_snapshot_id FK, nullable)
        │
        └── change_detection_events (event_id PK)
              (many rows share one detection_run_id — one row per metric
               compared, not one row per comparison run/file)
```

A `collection_run` is the optional parent of up to three snapshots (one per component script) — optional because a snapshot script can also run standalone, in which case `collection_id` is `NULL` on that row, exactly matching what the JSON already records. A `channel_snapshot` can be referenced by any number of `change_detection_events` as either the "previous" or "current" side of a comparison — one channel snapshot is typically both the "current" side of one comparison and the "previous" side of the next. `video_inventory_snapshots` and `channel_analytics_snapshots` are not currently referenced by `change_detection_events` at all, because `change_detection.py` only ever compares channel snapshots today (§6.2) — there is no dangling design here, just no edge into those two tables yet.

## 8. Field-by-Field Lossless Mapping

Legend: **S** = taken directly from the source JSON. **R** = resolved/derived at ingestion time from source data. **N** = new, added by this design, not present in source.

### 8.1 `collection_runs` ← `logs/collection_<ts>.json`

| Column | Type | Source path | Kind |
|---|---|---|---|
| `collection_id` | uuid, PK | `collection_id` | S |
| `schema_version` | text | `schema_version` | S |
| `collection_type` | text | `collection_type` | S |
| `started_at_utc` | timestamptz | `collection_started_at_utc` | S |
| `finished_at_utc` | timestamptz | `collection_finished_at_utc` | S |
| `success` | boolean | `success` | S |
| `components` | jsonb | `components` (full array: `component`, `script`, timings, `return_code`, `success`, `stdout`, `stderr`, `produced_snapshot_id`, `produced_snapshot_path`, verbatim) | S |
| `source_file` | text | — | N |
| `ingested_at_utc` | timestamptz | — | N |

### 8.2 `channel_snapshots` ← `data/snapshots/channel_<ts>.json`

| Column | Type | Source path | Kind |
|---|---|---|---|
| `snapshot_id` | uuid, PK | `snapshot_id` | S |
| `schema_version` | text | `schema_version` | S |
| `snapshot_type` | text | `snapshot_type` | S |
| `generated_at_utc` | timestamptz | `generated_at_utc` | S |
| `source` | text | `source` | S |
| `api_version` | text | `api_version` | S |
| `collection_id` | uuid, FK | `collection_id` (nullable) | S |
| `channel_id` | text | `channel_id` | S |
| `title` | text | `channel.title` | S |
| `description` | text | `channel.description` | S |
| `custom_url` | text | `channel.custom_url` | S |
| `published_at` | timestamptz | `channel.published_at` | S |
| `country` | text | `channel.country` (nullable — `null` in the real example) | S |
| `view_count` | bigint | `channel.statistics.view_count` | S |
| `subscriber_count` | bigint | `channel.statistics.subscriber_count` | S |
| `video_count` | bigint | `channel.statistics.video_count` | S |
| `hidden_subscriber_count` | boolean | `channel.statistics.hidden_subscriber_count` | S |
| `uploads_playlist_id` | text | `channel.uploads_playlist_id` | S |
| `branding` | jsonb | `channel.branding` (arbitrary nested shape) | S |
| `retrieval_metadata` | jsonb | `retrieval_metadata` (`retrieved_resources`, `pagination_completed`, `errors`, `warnings`) | S |
| `raw_response` | jsonb | `evidence.raw_response` (the complete, untouched `channels().list()` item — `kind`, `etag`, `id`, full `snippet` incl. thumbnails/localized, `contentDetails`, `statistics`, `brandingSettings`) | S |
| `source_file` | text | — | N |
| `ingested_at_utc` | timestamptz | — | N |

Note on `pagination_completed`: per the schema doc's 2026-08-12 Implementation Note, this is `null` here (not `true`) because a channel lookup is a single, non-paginated call — `null` means "not applicable," and must not be read as "incomplete." Preserved as-is inside `retrieval_metadata`, not reinterpreted.

### 8.3 `video_inventory_snapshots` ← `data/snapshots/videos/videos_<ts>.json`

| Column | Type | Source path | Kind |
|---|---|---|---|
| `snapshot_id` | uuid, PK | `snapshot_id` | S |
| `schema_version` | text | `schema_version` | S |
| `snapshot_type` | text | `snapshot_type` | S |
| `generated_at_utc` | timestamptz | `generated_at_utc` | S |
| `source` | text | `source` | S |
| `api_version` | text | `api_version` | S |
| `collection_id` | uuid, FK | `collection_id` (nullable) | S |
| `channel_id` | text | `channel_id` | S |
| `uploads_playlist_id` | text | `uploads_playlist_id` | S |
| `video_count` | integer | `video_count` | S |
| `videos` | jsonb | `videos` (full array — per item: `playlist_item_id`, `video_id`, `title`, `description`, `published_at`, `channel_id`, `channel_title`, `position`, `resource_id`, `status`, and `video_details` when enrichment matched) | S |
| `retrieval_metadata` | jsonb | `retrieval_metadata` | S |
| `source_file` | text | — | N |
| `ingested_at_utc` | timestamptz | — | N |

Note: `pagination_completed` is `true` here whenever a row exists at all, per code — a paginated run that hits the Quota Governance Contract's pagination ceiling raises before any snapshot is written (Snapshot Schema's 2026-08-13 Implementation Note), so "row exists" and "pagination genuinely completed" are equivalent under the current architecture. No reinterpretation needed; stored as-is.

### 8.4 `channel_analytics_snapshots` ← `data/analytics/channel_analytics_<ts>.json`

| Column | Type | Source path | Kind |
|---|---|---|---|
| `snapshot_id` | uuid, PK | `snapshot_id` | S |
| `schema_version` | text | `schema_version` | S |
| `snapshot_type` | text | `snapshot_type` | S |
| `generated_at_utc` | timestamptz | `generated_at_utc` | S |
| `source` | text | `source` | S |
| `api_version` | text | `api_version` | S |
| `collection_id` | uuid, FK | `collection_id` (nullable) | S |
| `channel_id` | text | `channel_id` | S |
| `reporting_start_date` | date | `reporting_period.start_date` | S |
| `reporting_end_date` | date | `reporting_period.end_date` | S |
| `metrics_requested` | text[] | `metrics_requested` (camelCase values kept verbatim — §6.9) | S |
| `analytics` | jsonb | `analytics` (`kind`, `columnHeaders`, `rows` — this is simultaneously the observed metrics and the full raw API response; no separate evidence key exists in source, per the schema doc's own note) | S |
| `retrieval_metadata` | jsonb | `retrieval_metadata` | S |
| `source_file` | text | — | N |
| `ingested_at_utc` | timestamptz | — | N |

Note: multiple rows sharing the same `(channel_id, reporting_start_date, reporting_end_date)` are expected and valid, not duplicates — Analytics data can be revised after initial reporting, so re-observing the same period over time is itself evidence. No uniqueness constraint is placed on the period; only on `(channel_id, generated_at_utc)`, to block literal re-ingestion of the same file.

### 8.5 `change_detection_events` ← `data/snapshots/changes/change_<ts>.json`

One source file produces **one row per entry in its `changes` array** (currently 3 rows per file — `subscriber_count`, `view_count`, `video_count` — but the array length is not assumed fixed).

| Column | Type | Source path | Kind |
|---|---|---|---|
| `event_id` | uuid, PK | — | N (`gen_random_uuid()`) |
| `detection_run_id` | uuid | — | N — one value shared by every row from the same file, so the full comparison can be reconstructed |
| `schema_version` | text | `schema_version` | S |
| `generated_at_utc` | timestamptz | `generated_at_utc` (when the comparison ran) | S |
| `entity_type` | text | `changes[i].entity_type` | S |
| `entity_id` | text | `changes[i].entity_id` | S |
| `metric` | text | `changes[i].metric` | S |
| `previous_value` | numeric | `changes[i].previous_value` | S |
| `current_value` | numeric | `changes[i].current_value` | S |
| `change_type` | text | `changes[i].change_type` | S |
| `absolute_change` | numeric | `changes[i].absolute_change` | S |
| `percentage_change` | numeric | `changes[i].percentage_change` | S |
| `evidence_class` | text | `changes[i].evidence_class` | S |
| `previous_snapshot_id` | uuid, FK | resolved from `previous_snapshot.generated_at_utc` (§6.6) | R |
| `current_snapshot_id` | uuid, FK | resolved from `current_snapshot.generated_at_utc` (§6.6) | R |
| `previous_snapshot_source` | jsonb | `previous_snapshot` verbatim (`{path, generated_at_utc}`) | S |
| `current_snapshot_source` | jsonb | `current_snapshot` verbatim | S |
| `source_file` | text | — | N |
| `ingested_at_utc` | timestamptz | — | N |

## 9. Proposed SQL

This is a design artifact only. It has **not** been run against the live project (§4/§6.4 confirm the database is still empty). It is also delivered as a standalone file, `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.sql`, so it's ready to hand to `apply_migration` once approved — but that step is not part of this pass.

```sql
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
```

**Resolved 2026-08-14 (previously a caveat, now settled):** `gen_random_uuid()` (used for `change_detection_events.event_id`) is provided by `pgcrypto`, installed in the `extensions` schema (§4), and is not guaranteed to be on this project's default `search_path`. Rather than leave that to runtime luck, the call above is explicitly schema-qualified as `extensions.gen_random_uuid()` — per the founder's direct instruction — so it resolves correctly regardless of `search_path`.

## 10. Decisions Requiring Founder Approval

**Outcome as of 2026-08-14 — see §13 for the full record.** Items 1, 2, 3, 4, and 6 below were approved as proposed; item 5 remains genuinely open (not addressed — it doesn't block B2.3.1). Two additional points the founder raised directly — the `detection_run_id` FK question and explicit `gen_random_uuid()` qualification — are resolved in §6.2 and §9 respectively, not listed again here.

These are the real judgment calls in this design — places where a technically competent alternative exists and this document picked one side. Everything else in §6 is either a direct implementation of an already-locked contract, or low-stakes enough to change later without touching the data model.

1. **Schema namespace (§6.7).** Recommended: dedicated `youtube_evidence` schema, not `public`. Consequence: B2.3.5's MCP layer will need either a Data-API exposure step (Exposed Schemas + grants) or a direct Postgres connection, not the default `public`-schema client setup. Confirm this trade-off is acceptable before it becomes a surprise at B2.3.5.
2. **`videos` as JSONB, not a normalized child table (§6.1).** Recommended: keep JSONB now (video count is currently zero; no real query pattern exists yet to normalize for). Revisit once real videos and real MCP query patterns exist.
3. **`change_detection_events` FK scoped to `channel_snapshots` only (§6.2).** Recommended: hard FK now, matching what `change_detection.py` actually compares today. Revisit as a schema revision if/when video-level change detection is built.
4. **RLS posture now vs. MCP role later (§6.4).** Recommended: RLS on, zero policies, `service_role`-only grants today; the actual MCP read role/policy is deliberately left to B2.3.5. Confirm this deferral (not the RLS-on decision itself, which directly implements Capability Map §10) is the right sequencing.
5. **No retention/pruning policy.** Not one of the nine points, but it falls out of "immutable, append-only": nothing in the Data Collection Contract, this design, or any other source document says evidence ever gets deleted or archived. That means storage grows unboundedly, forever, by design, unless a retention policy is added later. This is left genuinely open rather than silently resolved — worth a founder decision whenever real data volume makes it relevant, not now.
6. **`collection_type`/`snapshot_type`/`source`/`api_version` are `CHECK`-constrained to their single current literal value each (§9).** This means a future producer change (e.g., a hypothetical `schema_version 2.0` that renames `"youtube_data_api"`) would be *rejected* by ingestion rather than silently accepted — fail-closed, consistent with how this project already treats unrecognized states elsewhere (Ledger Schema §10.4/§10.6). Confirm reject-unknown is the intended posture, not accept-and-store-anyway.

## 11. Review Checklist

- [ ] §4 — confirm the live Supabase state check (0 tables, 0 migrations) matches your own understanding. *(not explicitly addressed 2026-08-14 — left open, not contentious)*
- [ ] §3 — confirm it's fine that `NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md` and `NIK_YOUTUBE_CHANGE_DETECTION_CONTRACT.md` were used as truncated drafts (code + real output used as ground truth beyond where they cut off), rather than pausing this design until those two documents are completed. *(not explicitly addressed 2026-08-14 — left open)*
- [ ] §3 — confirm no further action is needed re: the missing "B2.3 reconciliation report" (its central claim was independently re-verified in §4). *(not explicitly addressed 2026-08-14 — left open)*
- [x] §10.1 — decide schema namespace approach (`youtube_evidence` vs. `public`). **Approved 2026-08-14: dedicated `youtube_evidence` schema.**
- [x] §10.2 — confirm `videos` stays JSONB for now. **Approved 2026-08-14.**
- [x] §10.3 — confirm `change_detection_events`'s FK stays scoped to `channel_snapshots` only. **Approved 2026-08-14** (folded into the founder's broader "snapshot references by IDs, not paths" approval).
- [x] §10.4 — confirm RLS-now/role-later sequencing. **Approved 2026-08-14**, and sharpened into an explicit capability boundary — see §6.4, §13.
- [ ] §10.5 — acknowledge the open retention-policy question (no action required now). *(still genuinely open — does not block B2.3.1)*
- [ ] §10.6 — confirm reject-unknown `CHECK` constraints are the intended posture. *(not explicitly addressed 2026-08-14 — left open, low-stakes)*
- [x] §6.6 — confirm the timestamp-matching resolution strategy for `change_detection_events`'s snapshot references. **Approved 2026-08-14.**
- [ ] §6.9 — confirm the added-not-sourced columns (`ingested_at_utc`, `source_file`, `event_id`, `detection_run_id`) are acceptable additions to an otherwise-lossless mapping. *(not explicitly addressed 2026-08-14 — left open, low-stakes; `detection_run_id`'s no-FK design specifically was confirmed, see §6.2)*
- [x] §9 — skim the actual SQL once. **Done 2026-08-14** — the founder's own review quoted specific lines back, including catching the `gen_random_uuid()` qualification gap.
- [ ] Confirm B2.3.1 is complete and B2.3.2 (ingest channel snapshots) may begin. **Not yet — the founder explicitly held this at the review gate pending §13's final static review. This is the next and only remaining step.**

## 12. Explicitly Confirmed Out of Scope / Not Done

Per the original instruction, and restated here for a clean record: no migration was applied to the live database: verified by re-running `list_tables`/`list_migrations` mentally against every write this session made — the only writes were this document and its companion `.sql` file, both delivered as artifacts, not executed. No table was created. No row was inserted. No existing contract (`NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md`, `NIK_YOUTUBE_CHANGE_DETECTION_CONTRACT.md`, or any other) was modified, despite both being found incomplete. No `src/*.py` file was modified, despite `change_detection.py` being the actual root cause of the path-vs-ID gap in §6.6. No MCP was configured. Nothing was committed or pushed — git was not touched at all this session.

## 13. Founder Review Outcome and Final Static Review (2026-08-14)

### 13.1 Review outcome

The founder reviewed v1.0 of this document in full and approved the overall direction — dedicated schema, five-table model, JSONB for variable evidence, real `snapshot_id`/`collection_id` keys, append-only DB enforcement, deny-by-default RLS, no video child table yet, no SI-006 tables, and ID-based (not path-based) snapshot references — with three clarifications, now incorporated:

1. **`detection_run_id` confirmed intentionally independent of `collection_runs.collection_id`.** Reasoning recorded in §6.2: `change_detection.py` is not one of `collector.py`'s three components, so a FK to `collection_runs` would assert a relationship the system doesn't have.
2. **`gen_random_uuid()` is now explicitly schema-qualified as `extensions.gen_random_uuid()`** in §9 and the companion `.sql` file, rather than left to default `search_path` resolution.
3. **The Claude-facing capability boundary is now stated explicitly**, in §6.4: YouTube OAuth → acquisition scripts → local evidence → `youtube_evidence` → the future NIK YouTube Capability Layer (B2.3.5) → Claude. Claude gets none of: YouTube OAuth, the Supabase `service_role` key, arbitrary SQL, or arbitrary table access.

Also confirmed directly, re-checked against `collector.py`'s actual source rather than assumed: `change_detection.py` genuinely is absent from `collector.py`'s `components` list (`channel_snapshot`, `video_inventory`, `analytics_snapshot` only) — the stated reason for clarification 1 is a verified fact, not a restated assumption.

### 13.2 Final static review

Re-run after incorporating the three clarifications above, across the seven dimensions requested. This was a structural/textual review only — nothing was executed against Supabase or any other database (§4's empty-project state is unchanged).

| Dimension | Result |
|---|---|
| **FK relationships** | All FKs verified to reference a table and column that actually exist in this script: `channel_snapshots.collection_id`, `video_inventory_snapshots.collection_id`, `channel_analytics_snapshots.collection_id` → `collection_runs.collection_id`; `change_detection_events.previous_snapshot_id`/`current_snapshot_id` → `channel_snapshots.snapshot_id`. `detection_run_id` confirmed to have **no** FK, by design (§6.2, §13.1) — not a gap. |
| **Indexes** | All 14 `CREATE INDEX` statements confirmed to target real tables and real columns (including the `videos` GIN index's `jsonb_path_ops` operator class, which is valid syntax, not a column reference). No index changed by this revision. |
| **Append-only triggers** | `youtube_evidence.forbid_mutation()` confirmed attached via `BEFORE UPDATE OR DELETE` to all five tables — `collection_runs`, `channel_snapshots`, `video_inventory_snapshots`, `channel_analytics_snapshots`, `change_detection_events`. No table is missing its trigger. |
| **RLS / grants** | `ENABLE ROW LEVEL SECURITY` confirmed on all five tables, zero policies defined (deny-by-default for everyone except `service_role`). Grants confirmed limited to `service_role` only — `anon`/`authenticated` receive nothing, and the schema is still not added to Exposed Schemas. Matches §6.4 and the founder's locked capability boundary (§6.4, §13.1). |
| **JSONB / lossless mapping** | Spot-checked §8's five mapping tables against the actual `CREATE TABLE` statements column-by-column — no column named in §8 is missing from §9, and no column in §9 is unaccounted for in §8. The "added, not sourced" list in §6.9 (`ingested_at_utc`, `source_file`, `event_id`, `detection_run_id`, resolved `previous_snapshot_id`/`current_snapshot_id`) is still exhaustive after this revision — nothing new was silently added. |
| **UUID generation** | Only one column DB-generates a UUID: `change_detection_events.event_id`, now `default extensions.gen_random_uuid()`, explicitly schema-qualified (§13.1, item 2). Every other UUID column (`collection_id`, all `snapshot_id`s, `detection_run_id`, both snapshot-reference FKs) is sourced from or resolved against source data, never DB-generated — confirmed no other column carries a `default` clause that would need the same qualification. |
| **Schema / KOS boundary** | `youtube_evidence` schema isolation unchanged by this revision — still a dedicated schema, still not exposed to the Data API, still carrying the `comment on schema` pointing to Capability Map §9. No table, grant, or policy added in this revision touches `public` or any SI-006/knowledge-asset naming. |

A basic structural check (balanced parentheses, balanced `$$` dollar-quoting, every `references`/index target resolving to a real table and column) was re-run programmatically against the revised `.sql` file after editing, the same way it was before the first delivery — it passed clean, with the one intentional exception now correctly reflected: `detection_run_id` has no FK, confirmed by design rather than flagged as a missed one.

### 13.3 Final migration text

The complete, current `CREATE SCHEMA` / `CREATE TABLE` / index / trigger / RLS statement set — exactly as it would be executed if approved — is §9 above, and is delivered unchanged in structure (only the two edits from §13.1 applied) as `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.sql`. Nothing in §13.1's three clarifications required a fourth file or a change outside these two.

**Stopping here. Nothing has been executed. On explicit approval, the next action is running this exact SQL via `apply_migration` against project `wytwkhgkkvokgkbqwtxd` — that action has not been taken and will not be taken without a separate, explicit go-ahead.**

## 14. Migration Applied and Post-Apply Verification (2026-08-14)

On explicit founder approval, the migration in §9/§13.3 was executed unchanged via `apply_migration` against `wytwkhgkkvokgkbqwtxd`, recorded as `20260814045608_b2_3_1_youtube_evidence_foundation`. Pre-flight was re-confirmed immediately before execution: correct project, on-disk SQL re-read fresh and matching what was reviewed, database still at 0 tables / 0 migrations. Post-execution, read-only verification only — no writes beyond the migration itself:

| Check | Result |
|---|---|
| Schema exists | `youtube_evidence` present |
| Exactly five tables | `collection_runs`, `channel_snapshots`, `video_inventory_snapshots`, `channel_analytics_snapshots`, `change_detection_events` — no more, no fewer |
| Columns/constraints/FKs | Confirmed via catalog inspection against every column and `CHECK`/`UNIQUE`/FK constraint in §9 — all present, including `event_id`'s `default_value: "extensions.gen_random_uuid()"` |
| Indexes | 22 present — 5 primary keys + 3 unique constraints + 14 explicit `CREATE INDEX` statements, matching §6.5/§9 exactly |
| Triggers | 5 `<table>_forbid_update` triggers, each `BEFORE UPDATE OR DELETE`, one per table — none missing |
| RLS | `rls_enabled = true` on all five tables; **0** rows in `pg_policies` for the schema |
| Grants | Only `postgres` (implicit table owner) and `service_role` (explicit — `SELECT`, `INSERT` only, no `UPDATE`/`DELETE`) hold any table privilege. `anon`/`authenticated` hold none. Schema ACL confirms the same: `{postgres=UC, service_role=U}` |
| API exposure | The `authenticator` role's config has no `pgrst.db_schemas` entry at all — unchanged by this migration, confirming `youtube_evidence` was not added to Exposed Schemas |
| `extensions.gen_random_uuid()` | Called directly as a read-only test; resolved and returned a valid UUID |
| No stray SI-006/KOS objects | `youtube_evidence` is the only non-system schema in the database besides Supabase's own standard schemas |
| Row counts | 0 rows in all five tables — an empty, structurally-verified store, exactly as intended for the end of B2.3.1 |

**B2.3.2 (first snapshot ingestion) has not started.** This session performed schema creation and read-only verification only — no data was written to any evidence table.
