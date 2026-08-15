# NIK YouTube — Change-Detection → Supabase Ingestion Design

**Status:** APPROVED. All 7 decisions below locked by the founder on 2026-08-15. Implementation (validator/mapper, ingestion adapter, tests, both migration proposals, both static SQL tests) is now underway in the same gate as this approval, per the founder's explicit implementation authorization. No Supabase migration has been applied. No Git operation has been performed. No live ingestion has occurred. This document itself was renamed from `NIK_YOUTUBE_CHANGE_DETECTION_INGESTION_DESIGN.md` to carry the B2.3.5 name once Decision 3 (below) was locked — its content is otherwise the same design, with each decision's status updated from "recommended/pending" to "APPROVED" and Sec 8/Sec 9 updated to reflect what actually happened next.
**Stage:** **B2.3.5** — change-detection ingestion. Locked by Decision 3 below. The MCP capability layer, previously referred to as "B2.3.5" throughout earlier documentation, is renumbered **B2.3.6** and remains reserved/deferred.
**Date:** 2026-08-15
**Founder-approved input to this design:** `youtube_evidence.change_detection_events.source_file` becomes `NOT NULL`, with `UNIQUE (source_file, metric)`, as the idempotency model — approved during the readiness gate, carried forward as a locked premise below, not re-litigated.
**Standing strategic constraint, locked alongside this approval (not part of this design's technical scope, recorded here so it isn't lost):** B2.3.5 is the **final** milestone in the current YouTube evidence-persistence foundation. B2.3.6 (the MCP capability layer) or any other YouTube capability work must **not** begin automatically once B2.3.5 closes. A separate "YouTube foundation close-out / readiness gate" must run first, to explicitly decide whether B2.3.6 is actually needed for KOS before any further YouTube work starts. KOS is the next major track after that close-out gate — not B2.3.6 by default.

---

## 1. Purpose

This document resolves every open question the Change-Detection Readiness/Design Gate report surfaced, into an implementable, unambiguous design, so that the implementation gate has nothing left to decide on the fly. At the time this document was first drafted it did not write code, apply any migration, or touch Supabase; implementation began only after every decision below was explicitly approved.

## 2. Scope

**In scope:** the ingestion path for `change_detection.py`'s JSON output into `youtube_evidence.change_detection_events`, including the two migrations this requires (the `NOT NULL`/`UNIQUE` constraint, and the `youtube_ingest` grant/policy).

**Explicitly out of scope:**
- Modifying `change_detection.py` itself — the readiness report already established it needs no changes.
- Completing `NIK_YOUTUBE_CHANGE_DETECTION_CONTRACT.md`'s truncation. This design proceeds against the live schema and the real code's actual behavior as ground truth for what the contract doesn't reach, exactly the same accepted practice already used for the Data Collection Contract's identical truncation at B2.3.1 — not a new exception.
- B2.3.6 (the MCP capability layer) — untouched, and not to be started automatically once B2.3.5 closes (see the standing strategic constraint above).
- Any change to `channel_snapshots`, `video_inventory_snapshots`, or `channel_analytics_snapshots`.

## 3. Inputs reviewed

`NIK_YOUTUBE_CHANGE_DETECTION_READINESS_DESIGN_GATE.md` (this gate's own predecessor, in full), `src/change_detection.py` (in full), the one real fixture, `NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md` §6.2/§6.6/§8.5/§9 and the applied DDL, and the three precedent ingestion adapters (`channel_snapshot_ingest.py`, `video_inventory_ingest.py`, `analytics_ingest.py`) as structural precedent.

---

## 4. Decisions — Approved 2026-08-15

1. **Dry-run semantics (§5.5) — APPROVED.** A four-mode matrix, described in full below, where a real connection is required to demonstrate genuine resolution — a real, founder-acknowledged deviation from the `conn=None` pattern used for every adapter through B2.3.4, since this is the first table whose mapping step cannot be fully computed without a database connection.
2. **Two migrations, not one (§6) — APPROVED.** The `NOT NULL`/`UNIQUE` constraint change and the grant/policy stay as two separate, narrowly-scoped migrations, continuing the one-clear-thing-per-migration discipline every prior B2.3.x phase used.
3. **Phase numbering — APPROVED.** This phase is **B2.3.5**. The MCP capability layer, previously referred to as "B2.3.5" throughout earlier documentation, becomes **B2.3.6** — preserving build order in the numbering rather than inserting a phase out of sequence. This decision touches no existing file by itself; every future reference to "B2.3.5" as the MCP layer in older documents should be read as B2.3.6 going forward.
4. **Empty `changes` array → reject — APPROVED.** A present-but-empty `changes` array is a validation failure, not a valid zero-row ingestion. `compare_channel()` always produces exactly three entries today, so this path is unreachable from real output — this is a defensive, fail-closed rule for hypothetical malformed input, not a rejection of anything the current code can actually produce. Implemented in `validate_change_detection_events()`.
5. **New validation rule: all `changes[]` entries must share one `entity_type`/`entity_id` — APPROVED.** Needed because snapshot-ID resolution (§5.3) resolves once per file, not once per row — it depends on every row in a file describing the same entity. `change_detection.py`'s current output already satisfies this by construction; this makes it an enforced contract rather than an unstated assumption. Implemented in `validate_change_detection_events()`.
6. **`detection_run_id` stays a plain, non-deterministic `uuid4()` generated fresh on every ingestion call — APPROVED.** It does not need to be deterministic or content-derived, because idempotency is enforced entirely at the `(source_file, metric)` level (§5.6), not through this column. Implemented in `map_change_detection_events()`.
7. **First-real-fixture strategy (§8) — APPROVED and EXECUTED.** Before implementation, `change_detection.py` was run again, filesystem-only, producing `data/snapshots/changes/change_20260815_130216.json` — a fresh comparison between `channel_20260812_173832.json` (previous) and `channel_20260812_192334.json` (current, the one snapshot actually in `channel_snapshots`). See §8 for the outcome.

---

## 5. Detailed design

### 5.1 Validation rules

`validate_change_detection_events(doc)` — same collect-every-problem, name-every-field posture as every prior validator in `mappings.py`.

Required top-level fields, present and non-empty: `schema_version`, `snapshot_type` (must equal `"youtube_change_detection"`), `generated_at_utc` (valid timestamp), `entity_type`, `previous_snapshot` (object with non-empty `path` and valid `generated_at_utc`), `current_snapshot` (same shape), `changes`.

`changes` must be a list, and — per Decision 4 — must be **non-empty**. Each entry must contain non-empty `entity_type`, `entity_id`, `metric`, `change_type` (one of `UNCHANGED`/`CHANGED`/`UNAVAILABLE`), `evidence_class` (one of `OBSERVED`/`DERIVED`/`INTERPRETATION`/`ASSUMPTION`) — matching the two live `CHECK` constraints exactly, even though real data only ever produces `DERIVED`. `previous_value`/`current_value`/`absolute_change`/`percentage_change` are permitted to be `null` (that's exactly what `UNAVAILABLE`/zero-baseline comparisons legitimately look like) — presence, not truthiness, is what's checked, consistent with every other validator in this codebase.

Per Decision 5: every entry's `entity_type` and `entity_id` must be identical across the whole `changes` array — named explicitly as its own problem (`"changes[] entries reference more than one entity — resolution requires exactly one"`) if violated, not silently handled by resolving against the first entry only.

### 5.2 Exact mapping — one file, N rows

`map_change_detection_events(doc, source_file)` returns a **list of dicts**, not a single dict — the first mapping function in this codebase with that shape. One `detection_run_id` (`uuid.uuid4()`, Decision 6) is generated once and shared identically across every dict in the returned list. Per-row fields come straight from each `changes[i]` entry; `schema_version`, `generated_at_utc` (the comparison run's own timestamp — not either snapshot's), `previous_snapshot_source`/`current_snapshot_source` (the `previous_snapshot`/`current_snapshot` objects, verbatim, per §6.6's lossless-preservation requirement), and `source_file` are identical across every row in the list, since they describe the run, not the individual metric.

This function deliberately does **not** include `previous_snapshot_id`/`current_snapshot_id` in its output — see §5.3. It is a pure function of its input, same as every prior mapping function; DB-dependent resolution is layered on separately, by the ingestion adapter, not folded into this function.

### 5.3 Snapshot-ID resolution and NULL fallback

A separate function, `resolve_channel_snapshot_ids(conn, previous_snapshot, current_snapshot, channel_id)`, requires a real connection and runs (up to) two lookups:

```sql
select snapshot_id from youtube_evidence.channel_snapshots
where channel_id = %(channel_id)s and generated_at_utc = %(generated_at_utc)s;
```

— once for `previous_snapshot["generated_at_utc"]`, once for `current_snapshot["generated_at_utc"]`. `channel_id` for this query comes from `changes[0]["entity_id"]` (guaranteed by Decision 5's new validation rule to be the same for every row). `channel_snapshots`'s live `UNIQUE (channel_id, generated_at_utc)` constraint (already applied, B2.3.1) makes each lookup return 0 or 1 rows, never more — no ambiguity is possible. A 0-row result resolves to `None`; the row is still produced, not dropped, matching §6.6's fail-open design exactly. Resolution happens **once per file** (not once per row) and the same result is applied to every row in the mapped list — three identical DB round trips would be wasteful and, worse, could theoretically observe different results if a concurrent write happened between them.

### 5.4 Collection-run independence

No FK, no `collection_id` handling, no call to `ensure_collection_run()` anywhere in this adapter — confirmed as the correct design in the readiness gate (§6.2 of the schema doc, founder-resolved 2026-08-14) and unchanged here. The result type reflects this structurally rather than papering over it with unused fields:

```python
@dataclass
class ChangeDetectionIngestResult:
    source_file: str
    detection_run_id: str
    rows_mapped: int
    previous_snapshot_id: "str | None"
    previous_snapshot_resolved: bool   # False = not attempted (conn=None); True = attempted, value may still be None
    current_snapshot_id: "str | None"
    current_snapshot_resolved: bool
    rows_inserted: int
    dry_run: bool
```

No `collection_run_id`/`collection_run_inserted` fields at all — unlike the other three adapters' `IngestResult`, which always carry them (often `None`/`False`, but present). Their absence here is deliberate and structural, not an oversight.

### 5.5 Dry-run semantics (Decision 1)

Four modes, distinguished by `conn` and `dry_run` together:

| `conn` | `dry_run` | Behavior |
|---|---|---|
| `None` | `True` | **Structural dry run.** Validates and maps every row. Resolution is not attempted — `previous_snapshot_resolved`/`current_snapshot_resolved` are `False`, both IDs `None`. Closest equivalent to the old B2.3.2–B2.3.4 pattern, honestly scoped to what it can actually prove without a connection. |
| real conn | `True` | **Resolution dry run.** Validates, maps, and *does* run the real resolution `SELECT`s (§5.3) — so this mode can show exactly what a live ingestion would produce, including genuine `NULL` fallbacks — but never executes an `INSERT` and never commits. This is the mode that should be used for the actual dry-run gate, since it's the only one that can honestly demonstrate resolution behavior before a real write. |
| real conn | `False` | **Live ingestion.** Resolves, inserts with `ON CONFLICT (source_file, metric) DO NOTHING` (§5.6), commits. |
| `None` | `False` | Raises `ValueError("dry_run=False requires a real database connection.")` — identical to the existing pattern in every prior adapter. |

### 5.6 Idempotency — `(source_file, metric)`

Per the decision approved at the readiness gate: `source_file` becomes `NOT NULL`, with `UNIQUE (source_file, metric)`. The insert becomes:

```sql
insert into youtube_evidence.change_detection_events (
    detection_run_id, schema_version, generated_at_utc, entity_type, entity_id, metric,
    previous_value, current_value, change_type, absolute_change, percentage_change, evidence_class,
    previous_snapshot_id, current_snapshot_id, previous_snapshot_source, current_snapshot_source,
    source_file
) values ( ... )
on conflict (source_file, metric) do nothing
returning event_id;
```

`event_id` is never supplied by the adapter — its `default extensions.gen_random_uuid()` fills it in, the only DB-generated column in this schema and the only one this adapter doesn't set. Why a non-deterministic `detection_run_id` (Decision 6) is still safe: on a re-ingestion of the same file, every row's `(source_file, metric)` pair already exists, so `ON CONFLICT ... DO NOTHING` skips all of them regardless of what `detection_run_id` the second attempt generated — the "extra" `detection_run_id` from the skipped attempt is simply never persisted. Idempotency is fully owned by the constraint, not by any property of `detection_run_id`.

---

## 6. Migration/security structure (Decision 2)

**Migration A — constraint (schema structure), `NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_CONSTRAINT_PROPOSAL.sql`:**

```sql
alter table youtube_evidence.change_detection_events
  alter column source_file set not null;

alter table youtube_evidence.change_detection_events
  add constraint change_detection_events_source_file_metric_key
  unique (source_file, metric);
```

Safe to apply cleanly against live state: the table currently holds zero rows (confirmed live during the readiness gate), so there is no existing `NULL` or duplicate to violate either constraint.

**Migration B — grant and policy (security), `NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_GRANT_PROPOSAL.sql`, identical template to B2.3.2/B2.3.3/B2.3.4:**

```sql
grant select, insert on youtube_evidence.change_detection_events to youtube_ingest;

create policy youtube_ingest_all on youtube_evidence.change_detection_events
    for all
    to youtube_ingest
    using (true)
    with check (true);
```

No new role. No `UPDATE`/`DELETE` grant — moot, `forbid_mutation` blocks both regardless. `youtube_ingest` already holds `SELECT` on `channel_snapshots` (granted at B2.3.2) — the resolution query in §5.3 needs no additional grant. Order: A before B, finalizing the table's shape before granting access to it — not a hard dependency, just the cleaner sequence.

Both files are drafted and exist in the implementation gate's file set; neither has been reviewed as a standalone SQL artifact yet, and neither has been submitted to `apply_migration`. That remains a separate, later gate.

---

## 7. Test strategy

**`test_ingestion_change_detection_mappings.py`** (pure, no DB): every rule in §5.1, including the new empty-`changes` rejection and the new entity-consistency rule; the N-rows-per-file mapping shape; `detection_run_id` identical across every row from one call but different across two separate calls; `previous_snapshot_source`/`current_snapshot_source` preserved verbatim; confirms the mapping function's output never includes `previous_snapshot_id`/`current_snapshot_id` keys at all (structurally proving resolution isn't folded in here).

**`test_ingestion_change_detection.py`** (mocked connection, mirroring the existing Json-wrapping-distinction test pattern from `test_ingestion_analytics.py`): all four modes from §5.5, including asserting `previous_snapshot_resolved`/`current_snapshot_resolved` are `False` specifically in the `conn=None` mode (not merely that the IDs are `None`, which could also be masking a real resolve-and-not-found); a mocked resolution `SELECT` returning a row (successful path) and returning no row (fail-open path) exercised independently; idempotency proven at the mock level — a second call with the same `source_file` results in `rows_inserted == 0` because the mocked `ON CONFLICT` returns nothing.

**`test_change_detection_events_constraint_proposal.py`** and **`test_change_detection_grant_proposal.py`** (static text only, never executed): the constraint file contains `not null` and `unique (source_file, metric)` and touches no other table or column; the grant file matches the established B2.3.2–B2.3.4 template exactly — one policy, scoped only to `change_detection_events` and `youtube_ingest`, no `update`/`delete`, no new role, no password.

All of the above are implemented and passing as of this implementation gate — see the implementation-review report for exact counts.

---

## 8. First-real-fixture strategy (Decision 7) — executed

The original fixture (`change_20260812_175040.json`) resolves both snapshot IDs to `NULL` if ingested as-is — correct fail-open behavior, but it proves only one of the two resolution branches with real data. Per the approved plan, before implementation began, `change_detection.py` was run again (filesystem-only, no Supabase, no code change), producing `data/snapshots/changes/change_20260815_130216.json` — a fresh comparison between `channel_20260812_173832.json` (previous) and `channel_20260812_192334.json` (current). `channel_20260812_192334.json` is the one channel snapshot that actually exists in `channel_snapshots` (confirmed live at the B2.3.4 close-out), so this fixture is expected to demonstrate a real successful resolution on the current side alongside a real fail-open result on the previous side, once ingested against a real connection. That live confirmation happens at the actual dry-run/live-ingestion gates, not in this document; this implementation gate's mocked tests exercise both branches independently (§7).

All three `changes[]` entries in this fixture are `UNCHANGED` (`subscriber_count`, `view_count`, `video_count`, each `0 → 0`) — the underlying test channel has not changed between the two snapshots being compared. This does not affect validation or mapping in any way; `UNCHANGED` is one of the three valid `change_type` values and is exercised directly by the test suite.

---

## 9. Artifacts

| # | File | Purpose | Status |
|---|---|---|---|
| 1 | `src/ingestion/mappings.py` (modified) | New `REQUIRED_CHANGE_DETECTION_KEYS`, `CHANGE_TYPE_VALUES`, `EVIDENCE_CLASS_VALUES`, `validate_change_detection_events`, `map_change_detection_events` section, appended after `map_channel_analytics_snapshot` | Implemented |
| 2 | `src/ingestion/change_detection_ingest.py` (new) | `resolve_channel_snapshot_ids`, `ChangeDetectionIngestResult`, `ingest_change_detection_events`, CLI `main()` | Implemented |
| 3 | `tests/test_ingestion_change_detection_mappings.py` (new) | §7 | Implemented, passing |
| 4 | `tests/test_ingestion_change_detection.py` (new) | §7 | Implemented, passing |
| 5 | `NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_CONSTRAINT_PROPOSAL.sql` (new) | §6 Migration A | Drafted, not applied |
| 6 | `NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_GRANT_PROPOSAL.sql` (new) | §6 Migration B | Drafted, not applied |
| 7 | `tests/test_change_detection_events_constraint_proposal.py` (new) | §7 | Implemented, passing |
| 8 | `tests/test_change_detection_grant_proposal.py` (new) | §7 | Implemented, passing |
| 9 | This document (renamed from `NIK_YOUTUBE_CHANGE_DETECTION_INGESTION_DESIGN.md`) | Design record | Updated to APPROVED |

---

## 10. Review Checklist

- [x] Decision 1 — approve the four-mode dry-run matrix (§5.5).
- [x] Decision 2 — confirm two separate migrations (constraint, then grant/policy).
- [x] Decision 3 — resolve phase numbering: this phase is B2.3.5; MCP layer is B2.3.6 (reserved, not started).
- [x] Decision 4 — confirm empty `changes` array is rejected, not accepted as a valid zero-row ingestion.
- [x] Decision 5 — confirm the new single-entity-per-file validation rule.
- [x] Decision 6 — confirm non-deterministic `detection_run_id` is acceptable given idempotency lives entirely in the `(source_file, metric)` constraint.
- [x] Decision 7 — first-real-fixture strategy: generate a fresh one. Executed; see §8.
- [x] Confirmed this document may proceed to implementation, separately from a later, distinct approval to stage, commit, push, migrate, or ingest live — mirroring every prior B2.3.x gate. Implementation and tests only in this gate; staging/commit/push/migration/live-ingestion remain separately gated.

---

## 11. Confirmation of scope discipline

As originally drafted (readiness/design gate), before any decision above was approved: no existing source file was modified, no implementation file was created, no Supabase migration was applied, no write of any kind was made to Supabase, no Git operation was performed.

As of this implementation gate: the nine artifacts in §9 have been implemented and tested in the isolated cloud sandbox exactly as this design specifies. No Supabase migration has been applied. No write of any kind has been made to Supabase. No Git operation (staging, commit, or push) has been performed. No live ingestion has occurred. Those remain separately gated steps, to be authorized individually, exactly as every prior B2.3.x phase required.
