# NIK YouTube B2.3.2 — Channel Snapshot → Supabase Ingestion Design

**Version:** 1.0
**Status:** DESIGN ONLY. No code was written, no file was modified, no row was inserted, no migration was run, no MCP was configured, nothing was staged, committed, or pushed. Awaiting founder review.
**System:** NIK YouTube Integration
**Stage:** B2.3.2 — Channel Snapshot → Supabase Ingestion (Design Phase)
**Date:** 2026-08-14

**Scope of this pass:** Inspection and design only, per the founder's instruction. Every Supabase call made in this session was read-only (`list_tables`, `search_docs`); every device call was a `cat`/`ls` read. The only write anywhere was this document.

---

## 1. Purpose

B2.3.1 produced a live, empty, structurally-verified Supabase evidence store: five tables under `youtube_evidence`, append-only, RLS deny-by-default, not exposed through the Data API. That closed the "does a real persistent store exist" gap. It did not close the "does any evidence actually live there" gap — as of this document, all five tables still have zero rows.

This document designs — but does not build — the narrow path for exactly one of those tables:

```
channel_snapshot.py                        collector.py
       │                                         │
       │ data/snapshots/channel_<ts>.json        │ logs/collection_<ts>.json
       ▼                                         ▼
        \_____________  B2.3.2 ingestion adapter  _____________/
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                            ▼
   youtube_evidence.collection_runs   youtube_evidence.channel_snapshots
      (parent row, only if missing)      (this design's actual subject)
```

The right-hand input (`collector.py`'s log) is not in scope as its own ingestion target — it shows up here only because §6.2 below found that `channel_snapshots.collection_id` is a real foreign key, and a real FK has to resolve to a real parent row or be rejected; it can't be waved through. That finding, and what to do about it, is explained in §6.2, not assumed here.

Video inventory and analytics ingestion (B2.3.3, B2.3.4) are not addressed. Nothing here should be read as a general ingestion framework — it is the smallest adapter that gets one real, already-existing, known-good snapshot into Supabase losslessly and idempotently, per the founder's own stated success criterion.

## 2. Scope and Non-Goals

**In scope:** the ingestion path for `channel_snapshot.py`'s JSON output into `youtube_evidence.channel_snapshots`, including the minimum handling of its `collection_runs` parent required to keep that FK honest.

**Explicitly out of scope, per direct instruction:**
- Modifying `channel_snapshot.py`, `collector.py`, or any other acquisition script. They are done; this is a downstream, read-only-of-the-filesystem consumer of their output.
- Quota governance. Ingestion reads JSON files already on disk — it makes no YouTube API calls, so `quota_ledger.py` and the Quota Governance Contract are not touched or re-evaluated.
- The Supabase schema itself (§9 of `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md`). No `ALTER TABLE`, no new column, no new table.
- Video inventory ingestion, analytics ingestion, change-detection ingestion (B2.3.3/B2.3.4).
- MCP configuration (B2.3.5) — untouched.
- Exposing `youtube_evidence` through the Data API. §7 below explains why this also isn't needed for ingestion to work.
- Writing or running actual ingestion code. Everything under §8 is architecture and illustrative pseudocode for review, not a delivered script.

## 3. Inputs Reviewed This Session

| Source | Freshness | Used for |
|---|---|---|
| `src/channel_snapshot.py` | Re-read in full, this session | Ground truth for exactly what fields `build_snapshot()` produces and under what conditions — not inferred from the earlier design doc |
| `src/collector.py` | Re-read in full, this session | Confirmed `components` is still hardcoded to exactly `channel_snapshot`, `video_inventory`, `analytics_snapshot`; confirmed how `collection_id` is generated and passed down |
| `NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md` | Re-read, this session | Re-confirmed still truncated at 3,601 bytes, cutting off mid-`§6` storage tree — same finding as B2.3.1, not a new problem |
| `data/snapshots/channel_20260812_192334.json` | Read in full, this session | The one real, schema-conformant channel snapshot — used as the positive test case throughout |
| `data/snapshots/channel_20260812_171041.json`, `channel_20260812_173832.json` | Read in full, this session | Two more real channel snapshots — turned out to be structurally incompatible with the live schema; see §5 |
| `logs/collection_20260812_192340.json`, `collection_20260812_173840.json` | Read in full, this session | Real `collector.py` output, used to check the `collection_id` FK against an actual parent record, not a hypothetical one |
| `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` + `.sql` | Read in full, this session (both already reflect the applied migration) | The live schema's authoritative definition — column types, constraints, the `forbid_mutation` trigger, the grant model |
| Live `youtube_evidence` schema, `wytwkhgkkvokgkbqwtxd` | Re-checked via `list_tables`, this session | Confirmed still exactly 5 tables, RLS on, 0 rows each — see §4 |
| Supabase docs, "Postgres Roles" | Checked via `search_docs`, this session | Confirmed what `service_role` and `postgres` actually are at the role level — grounds §7 |

`NIK_YOUTUBE_SNAPSHOT_SCHEMA.md` and `NIK_YOUTUBE_CAPABILITY_MAP.md` are not re-read here; B2.3.1 already incorporated both in full and nothing in this document revisits a question either one settles.

## 4. Live State — Re-Verified, Not Assumed

Per this project's standing rule, "the database is still empty" is checked again here rather than carried forward from memory:

- `list_tables` (schema `youtube_evidence`) → exactly 5 tables, all `rls_enabled: true`, all `rows: 0`.
- `list_migrations` → exactly one migration, `20260814045608_b2_3_1_youtube_evidence_foundation`.

Nothing has written to this schema since B2.3.1 closed. Design proceeds from a genuinely empty, unchanged store.

## 5. Key Finding — Not Every On-Disk Snapshot Is Ingestible As-Is

Three real `channel_*.json` files exist on disk. Only one of them can actually satisfy the schema B2.3.1 built:

| Field | `channel_20260812_171041.json` (657 B) | `channel_20260812_173832.json` (657 B) | `channel_20260812_192334.json` (2,691 B) |
|---|---|---|---|
| `snapshot_id` | **absent** | **absent** | `a9594393-7572-4597-bb05-76082a9c993d` |
| `source` | **absent** | **absent** | `"youtube_data_api"` |
| `api_version` | **absent** | **absent** | `"v3"` |
| `collection_id` (key) | **absent** | **absent** | `"98321ba3-6bf1-4e50-aa8b-8a223ccd4862"` |
| top-level `channel_id` | **absent** | **absent** | `"UCn4OmZFMasYBkmCx6Q2oUBQ"` |
| `retrieval_metadata` | **absent** | **absent** | present, full object |
| `evidence.raw_response` | **absent** | **absent** | present, full raw API item |
| `channel` block (title, statistics, branding, …) | present, identical shape | present, identical shape | present |
| `schema_version` | `"1.0"` | `"1.0"` | `"1.0"` |

The two smaller files are real output from an earlier iteration of `channel_snapshot.py` — both dated the same day, both timestamped before the 19:23 run (17:10 and 17:38 respectively) — that predates several fields the *current* script, and the schema built around it, both treat as required. This isn't a hypothetical "what if a file is malformed" scenario: it's the actual current state of the one directory B2.3.2 has to read from.

Two things follow directly from this table:

1. **`schema_version` cannot be used to detect this.** All three files claim `"1.0"`. Validation has to check for the actual required keys, not trust the version string.
2. **This isn't fixable by cleverer mapping.** `snapshot_id` is the table's primary key — there is no value to derive it from when the source has no ID at all, and inventing one would misattribute an identity the source never had. `source`, `api_version`, `retrieval_metadata`, and `raw_response` are all `not null` in the live schema with no truthful fallback. The only honest response is: these two files are not ingestible under this design, full stop.

Cross-checking `collection_20260812_173840.json` (the collection log covering the same window as the 17:38 snapshot) confirms this isn't a fluke: that log has no top-level `collection_id` either, and its `components` entries have no `produced_snapshot_id`/`produced_snapshot_path` fields — it's from the same earlier iteration of the whole pipeline, not just the one script. The 19:23 collection run is the first one on disk where `collector.py` and `channel_snapshot.py` both already match what `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` was designed against. It is also, not coincidentally, the only one where the snapshot's `collection_id` and the log's `collection_id` actually cross-reference each other correctly (`98321ba3-6bf1-4e50-aa8b-8a223ccd4862` on both sides, and the log's `produced_snapshot_id` for the `channel_snapshot` component is `a9594393-7572-4597-bb05-76082a9c993d` — the snapshot's own `snapshot_id`, exactly).

This is used directly in §6.6 (malformed-input handling) and §6.10 (which file to use for the first live test).

## 6. The Ten Resolved Design Questions

### 6.1 How `snapshot_id` maps to the DB PK

Direct passthrough, `S` in B2.3.1's mapping legend — no transformation. `channel_snapshots.snapshot_id` (PK, `uuid`) = the source JSON's top-level `snapshot_id` string, parsed and validated as a UUID before use (Python's `uuid.UUID(value)` — raises on anything malformed, which becomes a rejection under §6.6, not a raw Postgres type error). Confirmed unchanged from `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` §8.2 — this document adds nothing new here beyond re-confirming it against the real file and current source.

### 6.2 How `collection_id` is resolved, and what happens if the parent doesn't exist yet

This is the one place this pass found something B2.3.1 didn't fully play out.

`channel_snapshots.collection_id` is `uuid references youtube_evidence.collection_runs (collection_id)` — nullable, but **not optional once a value is supplied**. If the adapter inserts a snapshot with `collection_id = '98321ba3-...'` and no row with that `collection_id` exists in `collection_runs`, Postgres rejects the insert with a foreign-key violation. There are only three honest ways to handle that:

- **(a) Ingest the parent `collection_runs` row first, if it isn't already there.** The mapping for `collection_runs` is already fully specified — B2.3.1 §8.1 designed it in full, it just hasn't been built. `logs/collection_20260812_192340.json` is the real parent for the real snapshot this design tests against (§6.10), and its `collection_id` matches exactly.
- **(b) Null out `collection_id` on the snapshot row when the parent isn't present**, and drop the linkage rather than resolve it. Rejected: the source JSON really does carry a `collection_id`; silently nulling a real, present value to dodge an FK contradicts the lossless-mapping principle B2.3.1 §6.9 established, for no reason better than convenience.
- **(c) Add a side column to hold an "unresolved" collection_id outside the FK.** Rejected outright — it requires a schema change, which is explicitly out of scope for B2.3.2.

**Recommended: (a).** In practice this means the ingestion adapter, when it meets a non-null `collection_id` it hasn't seen in `collection_runs` yet, reads the matching `logs/collection_<ts>.json` (matched by `collection_id`, found by scanning the log directory — not by guessing a filename from a timestamp), inserts that row using the mapping B2.3.1 already designed, and only then inserts the snapshot. If no matching log file can be found at all, the snapshot is rejected under §6.6 rather than guessed at. This is a small, already-designed addition, not new scope — but it does mean B2.3.2's adapter writes to two tables, not one, which is why it's listed as a founder-approval item in §9.

### 6.3 Idempotency — the same `snapshot_id` ingested twice

`snapshot_id` is the primary key, so a second plain `INSERT` of the same row fails on a unique-violation. The correct idempotent form is:

```sql
insert into youtube_evidence.channel_snapshots (...) values (...)
on conflict (snapshot_id) do nothing;
```

**`do nothing`, never `do update`.** This isn't a style preference — `on conflict ... do update` would fire the `forbid_mutation` trigger from B2.3.1 §6.3 (it's a real row modification as far as Postgres is concerned) and abort the statement with the trigger's exception. `do nothing` skips the write at the row level without ever attempting a modification, so it doesn't touch the trigger at all.

Two layers, matching the immutability design's own two-layer pattern: an application-level pre-check (`select 1 from channel_snapshots where snapshot_id = ...`) so the adapter can report "already ingested, 0 rows written" as a clean, expected outcome with a clear log line — and the `on conflict do nothing` as the actual safety net underneath it, so a race between two ingestion runs (or a bug in the pre-check) still can't produce a duplicate or a mutation.

### 6.4 Append-only enforcement

Nothing new to design — this is B2.3.1 §6.3's trigger, already live, already verified. The only thing B2.3.2 adds is a matching application-level discipline: the adapter's code path only ever constructs `INSERT ... ON CONFLICT DO NOTHING` statements. There is no function in this design that issues `UPDATE` or `DELETE` against any evidence table, and none should ever be added — not even for cleanup (see §6.10's rollback discussion, which runs directly into this).

### 6.5 New module or existing module

**Recommended: a new module**, not an addition to `channel_snapshot.py` or `collector.py`. Reasons, in order of how much they matter:

1. The founder's own instruction is explicit: don't redesign the acquisition scripts. Adding Supabase-writing logic to `channel_snapshot.py` would blur exactly the acquisition/ingestion boundary this whole conversation has been careful to keep separate — "acquisition is done; this is a new downstream layer" only stays true if the downstream layer is actually a separate module.
2. Different dependency footprint. Ingestion needs a Postgres driver and a database credential (§7); acquisition scripts have no reason to import either.
3. Different failure domain. Supabase being unreachable should never affect a YouTube collection run, and a quota-governance failure should never affect an ingestion run. Sharing a module couples failure modes that are currently, correctly, independent.
4. It matches the architecture diagram in §1 and the one the founder gave: three distinct boxes, not two.

Proposed layout (paths, not files — nothing here is created):

```
src/ingestion/
  __init__.py
  db.py                       -- shared direct-Postgres connection helper (§7),
                                  reused by B2.3.3/B2.3.4 later
  channel_snapshot_ingest.py  -- this adapter: read one channel_*.json,
                                  validate, resolve/ingest its collection_runs
                                  parent if needed, insert
```

A `src/ingestion/` package (rather than one more flat file in `src/`) is proposed because B2.3.3 and B2.3.4 will need the same connection helper shortly, and putting it next to `channel_snapshot.py` risks exactly the naming collision this section is trying to avoid (an ingestion file that also wants to be called something like "channel_snapshot"). This is a low-stakes, changeable-later choice, not an architectural commitment — flagged in §9 rather than argued further.

### 6.6 Malformed JSON, missing fields, invalid UUIDs, FK failures

§5 turned this from a hypothetical into a concrete, three-part validation gate, run **before** any SQL is issued:

1. **Parse.** `json.load()` the file. A `JSONDecodeError` is an immediate reject — not-JSON is not evidence.
2. **Structural validation.** Check every column this design maps as `not null` has a present, non-null source value: `snapshot_id`, `schema_version`, `snapshot_type`, `generated_at_utc`, `source`, `api_version`, `channel_id`, `channel.statistics.*` (all four), `retrieval_metadata`, `evidence.raw_response`. This is exactly the check that correctly rejects the two legacy files in §5 — each is missing five of these outright. Failure produces one clear message naming every missing field, not a stack trace from a `KeyError` three functions deep.
3. **Value validation.** `snapshot_id` and `collection_id` (if present) parse as UUIDs (`uuid.UUID(...)`); `generated_at_utc` parses as an ISO-8601 timestamp; `snapshot_type == "youtube_channel"`, `source == "youtube_data_api"`, `api_version == "v3"` — the same three literals the live schema's `CHECK` constraints enforce, checked here first so a mismatch produces a clear application-level error instead of surfacing as a raw Postgres constraint violation.

Any failure at any of the three steps: **reject, log the specific reason, write nothing, move on** (or, for the single-file first-run in §6.10, stop and report). This is the same fail-closed posture B2.3.1 §6.4/§10.6 already committed to for the schema's own `CHECK` constraints — this section is that same posture applied one layer up, in application code, before the constraint would even be reached.

**FK failure** (the `collection_id` case from §6.2): if the parent can't be resolved *and* can't be ingested either (no matching log file found), that's also a reject-this-snapshot outcome, not a null-and-proceed outcome — consistent with the reasoning in §6.2.

### 6.7 Preservation of `raw_response`, `retrieval_metadata`, `source_file`, timestamps

All four already fully specified in B2.3.1 §8.2; restated here against the real file to confirm nothing changed:

- `evidence.raw_response` → `raw_response` (jsonb): the entire `channel` dict as returned by `channels().list()`, byte-for-byte — confirmed by re-reading `channel_snapshot.py`'s `build_snapshot()`, which does `"raw_response": channel` with no transformation.
- `retrieval_metadata` → `retrieval_metadata` (jsonb): same passthrough. In the real file this is `{"retrieved_resources": ["youtube#channel"], "pagination_completed": null, "errors": [], "warnings": []}` — the `null` is preserved as SQL `NULL` inside the JSONB, not coerced to `false` or dropped, per the Implementation Note B2.3.1 §8.2 already cites.
- `source_file`: new, not sourced — the path of the file actually ingested, in the same relative-to-repo-root style `collector.py` already uses for `produced_snapshot_path` (e.g. `data/snapshots/channel_20260812_192334.json`), so it's consistent with an existing convention rather than inventing a new one.
- Timestamps: `generated_at_utc` parses directly from the source's microsecond-precision ISO-8601 string (e.g. `2026-08-12T19:23:34.033659+00:00`) into `timestamptz` — no truncation. `ingested_at_utc` is the one new timestamp, DB-generated via the column's existing `default now()`, never supplied by the adapter.

### 6.8 Independence from SI-006/KOS

The adapter writes to exactly two tables, both under `youtube_evidence`: `channel_snapshots` and, when needed, `collection_runs`. Nothing in this design touches `public` or any future `knowledge`-type schema. The credential the adapter needs (§7) is a database-level credential held by whatever machine runs ingestion — not a Supabase API key, and specifically not anything Claude holds, consistent with the capability boundary B2.3.1 §6.4 locked: *YouTube OAuth → acquisition scripts → local evidence → `youtube_evidence` → (future) NIK YouTube Capability Layer → Claude*. Ingestion sits entirely on the left side of that diagram, one arrow before the layer that doesn't exist yet.

### 6.9 Exact tests required before the first real row is inserted

Four tiers, each a prerequisite for the next — nothing here has been run:

- **Tier 0 — pure logic, no network, no Supabase.** Run the mapping/validation function against fixtures: the real 19:23 file (must map cleanly to the exact column values in §6.1/§6.7) and both legacy files (must be rejected, with a clear reason each, and must not raise an unhandled exception).
- **Tier 1 — dry run against the live, empty database, read-only.** Connect for real (§7), run the duplicate-check and FK-existence-check queries for real, but stop before any `INSERT` — print what would be written. Confirm the table's row count is 0 both before and after, proving the dry run genuinely wrote nothing.
- **Tier 2 — the one real insert** *(not authorized by this pass — see §6.10)*. Insert the real `collection_runs` parent (if not already present) and the real `channel_snapshots` row, then `SELECT` it back and diff every field against the source JSON — including the two JSONB blobs compared for exact equality, not just presence.
- **Tier 3 — idempotency proof**, immediately after Tier 2: re-run ingestion on the identical file. Expected result: 0 rows written, a clear "already present" log line, table row count still exactly 1, and the existing row's `ingested_at_utc` unchanged — proving it truly wasn't touched, not silently rewritten.

### 6.10 Safe first-live-ingestion procedure, with verification and rollback/abort

**Which file:** `data/snapshots/channel_20260812_192334.json` — the only one of the three real files that's schema-conformant (§5), with a real, resolvable `collection_runs` parent (`logs/collection_20260812_192340.json`, cross-referenced and confirmed matching in §5). There is no second candidate to weigh this against; it's the only complete, self-consistent example that currently exists.

**Procedure, in order:**

1. Tier 0 and Tier 1 tests pass (§6.9) — nothing written yet.
2. **Explicit founder go-ahead**, separate from this document's approval — the same two-step pattern B2.3.1 used (design approval, then a distinct execute approval).
3. Insert the `collection_runs` parent row (only if `select 1 from collection_runs where collection_id = '98321ba3-...'` finds nothing).
4. Insert the `channel_snapshots` row.
5. Read both rows back; diff every field against the two source JSON files, field by field.
6. Re-run ingestion on the same file (Tier 3) to prove idempotency in the live database, not just in a test double.
7. Report row counts and the field-by-field diff result. Stop.

**Rollback/abort — the honest limitation.** Everything through step 2 is non-destructive and repeatable. After step 3/4, there is no `DELETE`-based undo available *by design*: the same `forbid_mutation` trigger from B2.3.1 that makes "append-only" true for real evidence also blocks deleting a bad test row — it doesn't distinguish "a mistake" from "a later correction," on purpose, because that distinction is exactly what the Data Collection Contract §5 says the system must not make for itself. Recovering from a bug discovered *after* step 4 means fixing the adapter and leaving the row in place (it's still a truthful copy of a real snapshot, even if, say, `source_file` had a bug in it) — not deleting it. This is worth founder awareness before step 2's go-ahead, not after: **the dry-run/validation steps before the real insert are the only real safety net here, not the ability to undo it afterward.** A Supabase development branch (`create_branch`) would offer genuine undo — delete the branch, start over — and is listed as an option in §9, but isn't the default recommendation given the size of this test (one row) against the cost of standing up a branch.

## 7. Connection and Access Architecture

This wasn't one of the ten numbered questions, but answering §6.2 and §6.8 honestly required settling it, so it gets its own section rather than being asserted in passing.

**Finding, checked against Supabase's own "Postgres Roles" doc, not assumed:** `service_role` is described there as "used by the API (PostgREST) to bypass Row Level Security" — it's the role PostgREST switches into for a request carrying the service-role key. It is not described as a role meant for direct `psql`-style login. Separately, and more directly decisive: **`youtube_evidence` is deliberately not in Exposed Schemas** (B2.3.1 §6.4, re-confirmed live in §4 of that document's §14) — PostgREST simply has no route into a schema that isn't exposed, regardless of which key or role is presented to it. That means the Supabase client library (`supabase-py`, or the JS client) — which only ever talks to Postgres *through* PostgREST — cannot reach this schema at all, full stop, independent of any grant. This also isn't a gap to fix: the founder's own instruction for this phase is "do not expose `youtube_evidence` through the normal Supabase API," so this isn't a workaround, it's the design working as intended.

**What does work:** a direct Postgres connection, using the project's database connection string (from Database Settings, not the API Keys page) and a driver like `psycopg2`/`psycopg` — not the Supabase client library. The same doc confirms the `postgres` role is the project's own admin/owner role, with its own settable password, explicitly documented as the credential behind that direct connection string. Since `postgres` owns every table in `youtube_evidence` (as the role that ran the B2.3.1 migration), it already has full access independent of the `service_role`-only grants B2.3.1 set up — those grants exist to prepare for a *future*, PostgREST-mediated path (most likely B2.3.5's MCP layer, once/if that schema is ever exposed), not for this one. **Recommended: the ingestion adapter connects directly as `postgres`, via a database connection string held as a local secret/environment variable by whichever machine runs ingestion** — the same "never given to Claude" treatment already locked for every other credential in this system (§6.8).

This is listed as a founder-approval item in §9 because it's a real credential-handling decision, not a technical inevitability — reasonable alternatives (a narrower, purpose-created ingestion role; a Supabase branch for testing) exist and are noted there.

## 8. Proposed Implementation Architecture

Illustrative only — describing the shape of the adapter for review, not delivered or executable code, per the founder's explicit instruction not to write ingestion code in this pass.

```
ingest_channel_snapshot(path: Path) -> IngestResult:
    doc = parse_and_validate(path)          # §6.6, tiers 1-3; raises IngestRejected
                                             # with a specific reason on any failure

    conn = get_connection()                 # §7 — direct Postgres, role postgres

    if doc["collection_id"] is not None:
        ensure_collection_run(conn, doc["collection_id"])   # §6.2 — find + insert
                                                              # the parent log if the
                                                              # row doesn't exist yet;
                                                              # raises IngestRejected
                                                              # if no matching log file
                                                              # can be found at all

    row = map_channel_snapshot(doc, source_file=relative_path(path))   # §6.1/§6.7

    inserted = insert_with_conflict_do_nothing(conn, row)    # §6.3 — never DO UPDATE

    return IngestResult(
        snapshot_id=row["snapshot_id"],
        inserted=inserted,               # False on a clean duplicate skip
        source_file=row["source_file"],
    )
```

`map_channel_snapshot()` itself is the direct implementation of the §8.2 table in `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` — every column on the left, the exact source path on the right, nothing invented beyond the four `N` (new) columns that document already names. It is not repeated field-by-field here since restating an already-approved mapping table a second time would just be duplication, not new design.

## 9. Decisions Requiring Founder Approval

1. **Scope extension to include `collection_runs` (§6.2).** Recommended: yes — ingest the parent row when needed, using the mapping B2.3.1 already designed. The alternative (null out a real `collection_id` to avoid touching a second table) throws away real source data for the sake of a narrower diff.
2. **New `src/ingestion/` package vs. a single flat module (§6.5).** Recommended: package, since two more adapters (B2.3.3, B2.3.4) are coming and will share the connection helper. Low-stakes, reversible later.
3. **Direct Postgres connection as `postgres`, vs. a narrower purpose-built role (§7).** Recommended: `postgres` for now, since it requires no new role/grant work and the credential is already treated as a held-locally secret either way. A dedicated `youtube_ingest` role with `INSERT`-only privileges on exactly these two tables would be more tightly scoped and is a reasonable upgrade — noted here as a real alternative, not dismissed, but adds setup this phase doesn't strictly need yet.
4. **What to do with the two legacy, non-conformant snapshot files (§5).** Recommended: leave them un-ingested, permanently — they're early-development artifacts of an earlier script version, not evidence the current contract or schema recognizes as complete. The alternative (synthesize a `snapshot_id` for each so they can be backfilled) would mean inventing an identity the source never had, which cuts against every "observed, not interpreted" principle this whole schema was built to enforce. This is genuinely the founder's call, not a technical fact.
5. **No Supabase branch for the first live test (§6.10).** Recommended: skip it — thorough dry-run validation before the one real insert, rather than a full branch for a single-row test. Flagged because the trade-off is real: a branch would provide true undo; this recommendation doesn't have one, by the append-only design's own logic.

## 10. Review Checklist

- [ ] §5 — confirm it's acceptable that two of the three real on-disk snapshots are permanently out of scope for ingestion (not a bug to fix, a fact about the data).
- [ ] §6.2 / §9.1 — approve `collection_runs` parent-row ingestion as part of B2.3.2's adapter.
- [ ] §6.5 / §9.2 — approve (or override) the `src/ingestion/` package layout.
- [ ] §7 / §9.3 — approve direct-Postgres-as-`postgres` as the connection method, or request a narrower dedicated role instead.
- [ ] §6.10 / §9.5 — approve skipping a Supabase branch for the first live test, given the no-undo consequence is now explicit.
- [ ] §6.9 — confirm the four-tier test plan is sufficient before any real row is written.
- [ ] §6.10 — confirm `channel_20260812_192334.json` as the file for the first live ingestion.
- [ ] Confirm this document may proceed to implementation (writing the actual adapter code) — separately from a later, distinct approval to actually run it against the live database, mirroring how B2.3.1 kept "design," "build," and "execute" as three separate gates.

## 11. Explicitly Confirmed Out of Scope / Not Done

No file under `src/` was modified — `channel_snapshot.py` and `collector.py` were opened with `cat` only. No SQL was executed against `wytwkhgkkvokgkbqwtxd` beyond the two read-only `list_tables` calls in §4. No row exists in any `youtube_evidence` table beyond the zero already confirmed. No new module, file, or package under `src/ingestion/` was created — §6.5/§8 describe a proposal, not a change made. No MCP configuration was touched. `youtube_evidence` was not added to Exposed Schemas. Nothing was staged, committed, or pushed — git was not touched this session.

**Stopping here at the review gate, per instruction. Nothing has been implemented and nothing has been executed.**
