\# NIK YouTube Quota Ledger Schema

\*\*Version:\*\* 1.2 \(Approved\)

\*\*Status:\*\* Approved 2026-08-13 — v1.1's single-field `pre_call_check` shape \(§6.2\) is superseded by the multi-ceiling shape below, which also corrects `search.list`'s accounting \(§10.1\) and adds pre-call write failure handling \(§10.6\). v1.0's entry model remains superseded by §4, unchanged from v1.1. Ledger module implementation \(Stage B1\) is complete per schema v1.1 and requires a follow-up code update to match v1.2 — see §11. Integration into any API-calling script \(Stage B2\) is separately gated and not yet approved.

\*\*System:\*\* NIK YouTube Integration

\---

\## 1. Purpose

This schema defines the exact structure of the quota ledger: the append-only record of individual YouTube API call attempts, used to enforce the limits defined in `NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md`.

This document defines structure only. It does not implement the ledger. Implementation is separate, future work, staged and gated per the Quota Governance Contract's §11 and §12.

\---

\## 2. Core Principle

Relationship to the Quota Governance Contract:

The contract defines what must be governed, and why.

This schema defines exactly what a ledger entry looks like, so implementation does not have to invent field names, types, or semantics on its own.

The same evidence discipline that governs this project's other schemas applies here. A ledger entry records an observed fact at the moment it was actually knowable. It does not interpret whether a pattern of calls is safe over time — that judgment belongs to the enforcement code operating under the contract's limits, and ultimately to human review of those limits. §4 below exists because v1.0 of this document did not fully honor that discipline — it let one entry imply knowledge that could not yet exist at write time.

\---

\## 3. Location and Format

Location:

`logs/quota_ledger.jsonl`

Format:

JSONL — one JSON object per line, newline-terminated. Not a single JSON document, and not a JSON array.

This directory is already gitignored \(`.gitignore` contains `logs/`\), consistent with the existing collection logs and discovery logs already stored there.

A single rolling file is used, not daily-rotated files, unchanged from v1.0. The governing daily budget \(Quota Governance Contract §5.2\) is a rolling 24-hour window, and a single file answers a rolling-window query with a plain timestamp filter rather than requiring cross-file boundary logic near midnight.

\---

\## 4. Entry Lifecycle — Resolving the Pre/Post-Call Design Issue

\### 4.1 The problem

`pre_call_check` \(the budget check and allow/deny decision\) is knowable before an API call executes. `outcome` and `error` are knowable only after the call returns, or after it fails. v1.0 of this schema put both on a single entry. Because the ledger is append-only, that single entry can only be written once — either before the call \(when `outcome`/`error` do not exist yet\) or after it \(when the call itself already happened, unrecorded, during the gap between deciding to proceed and writing the entry\). Neither timing lets one immutable entry honestly hold both halves of the story.

\### 4.2 Option A — two append-only events per call, linked by a stable ID

A pre-call event is written the moment a decision is made, before the API call executes: it records the check performed and whether the call was allowed or denied. If allowed, the API call is made, and a second, separate post-call event is written afterward: it records the outcome and any error. The two events are linked by a `call_id` shared between them \(§6\). Both writes remain pure appends — the pre-call event is never edited or rewritten once the post-call event exists.

\### 4.3 Option B — one post-call entry only, gap documented

Write a single entry, only after the call completes \(or fails\), exactly as v1.0 did. If the process crashes after the real API call succeeds but before that entry is written, the call happened, quota was genuinely consumed, and the ledger will never show it. The document would simply state that this gap exists.

\### 4.4 Recommendation: Option A

Reasoning, against the four things this decision should be reasoned from:

\*\*Evidence discipline.\*\* A pre-call event and a post-call event are two separate, honestly-timestamped observations, each asserting only what was actually known at the moment it was written. Option B's single post-call entry, if it existed, would be fine as far as it goes — but the gap is not a documentation problem, it is a period during which a real, quota-consuming event has no corresponding observation at all. Option A ensures a record exists before the risky operation \(the call itself\), not only after it.

\*\*Missing ≠ Zero.\*\* Under Option B, a crash after a successful call and a call that never happened produce the identical ledger state: nothing. That is the Missing ≠ Zero failure mode in its purest form — real consumption reads as zero consumption, and nothing distinguishes the two cases even in principle. Under Option A, an "allowed" pre-call event with no matching post-call event is visibly different from no event at all. The system can tell the difference between silence-because-nothing-was-attempted and silence-because-the-result-was-lost, which is the same distinction the project's four-state \(missing / unavailable / not collected / API failure\) thinking already insists on elsewhere.

\*\*Fail-closed governance.\*\* Option A gives a budget-checking reader something principled to fail closed on. As detailed in §10, the budget arithmetic counts every "allowed" pre-call event within the rolling window, whether or not a post-call event ever follows — an unresolved \("orphaned"\) attempt is automatically treated as having consumed its estimated cost, not as though it never happened. Option B gives the reader nothing to even recognize as ambiguous; the crash case and the never-happened case are indistinguishable, so there is no ambiguity left to fail closed on — the failure already happened silently, upstream of any check.

\*\*Append-only requirement.\*\* Option A satisfies this directly: two independently-complete, immutable events, correlated by `call_id`, neither ever rewritten. Solving Option B's gap by writing the entry pre-call and then updating it post-call would violate append-only outright \(exactly the whole-file-rewrite risk JSONL was chosen to avoid in v1.0 §3\); leaving the gap undocumented-but-real, as literally proposed, satisfies append-only only by leaving the actual problem unsolved.

Option A is the recommendation. Its cost is real but small: roughly double the write volume of v1.0's design, which remains negligible at this project's current and near-term call volume \(unchanged reasoning from v1.0 §\[Design comparison\]\).

\---

\## 5. Write Behavior

Every write is a pure append: open the file in append mode, write one complete JSON object followed by a single newline, close. This is unchanged from v1.0 and holds for both event types.

An \*\*allowed\*\* call produces two appends over its lifetime: one pre-call event at decision time, one post-call event after the API call returns or fails. Both are independent, complete writes — the second is never a rewrite of the first.

A \*\*denied\*\* call produces exactly one append: the pre-call event alone. No post-call event is ever written for it, because no API call was ever made \(§7\).

No existing bytes in the file are ever read, modified, or rewritten by a normal write, for either event type. At most the newest, final line can be left incomplete by an interrupted write; every prior line is unaffected \(§10\).

\---

\## 6. Entry Fields

\### 6.1 Fields common to both event types

`ledger_schema_version` — string, e.g. `"1.2"`.

`entry_id` — string, UUID4. Unique to this specific line/event.

`call_id` — string, UUID4. Generated once, at pre-call time, and shared by the pre-call event and its corresponding post-call event \(if one is ever written\). This is the join key between the two halves of one call attempt. A denied call's pre-call event still has a `call_id`, even though no post-call event will ever reference it.

`event_type` — string: `"pre_call_check"` or `"post_call_result"`.

`timestamp_utc` — string, ISO 8601, UTC. The time this specific event was written \(not the time of the other event in the pair\).

\### 6.2 Pre-call event \(`event_type: "pre_call_check"`\)

`script` — string, e.g. `"video_inventory.py"`.

`operation` — string, e.g. `"playlistItems.list"` or `"reports.query"`.

`collection_id` — string \(UUID4\) or `null`. Same nullable pattern already used on snapshots.

`cost_model` — string: `"known"` or `"dynamic"`, per Quota Governance Contract §4.1/§4.3.

`estimated_cost_units` — integer or `null`. `1` for known-cost operations. `null` for the dynamic-cost Analytics operation — never a guessed value.

`pre_call_check` — object. Its shape depends on which policy governs the operation \(Contract §6\):

For a known-cost, shared-pool operation \(`channels.list`, `playlists.list`, `playlistItems.list`, `videos.list`\):

\- `remaining_run_ceiling_before_call` — integer, units remaining under Contract §5.1 before this call.

\- `remaining_daily_budget_before_call` — integer, units remaining under Contract §5.2 before this call.

\- `cooldown_ok` — boolean, whether Contract §5.3's cooldown is satisfied.

\- `binding` — string or `null`. Names the one check that caused a denial: `"run_ceiling"`, `"daily_budget"`, or `"cooldown"`. `null` when `decision` is `"allowed"`.

\- `decision` — `"allowed"` or `"denied"`.

For `search.list` \(known-cost, not shared-pool — Contract §5, §6, §8\):

\- `remaining_run_ceiling_before_call` — integer, units remaining under Contract §5.1 before this call.

\- `remaining_search_allocation_before_call` — integer, calls remaining under Contract §8's rolling-24h search allocation before this call.

\- `cooldown_ok` — boolean, whether Contract §5.3's cooldown is satisfied.

\- `binding` — string or `null`: `"run_ceiling"`, `"search_allocation"`, or `"cooldown"`. `null` when `decision` is `"allowed"`.

\- `decision` — `"allowed"` or `"denied"`.

\- No `remaining_daily_budget_before_call` field is present on this shape — per Contract §6, this operation is never checked against §5.2.

For the dynamic-cost Analytics operation \(`reports.query`, Contract §5.4\):

\- `policy` — string, e.g. `"analytics_call_frequency_v1"` \(unchanged from v1.1\).

\- `invocations_remaining_in_window` — integer, remaining invocations under §5.4's 12-per-rolling-24h ceiling.

\- `cooldown_ok` — boolean, whether §5.4's 5-minute cooldown is satisfied.

\- `binding` — string or `null`: `"per_invocation_limit"`, `"invocation_ceiling"`, or `"cooldown"`. `null` when `decision` is `"allowed"`.

\- `decision` — `"allowed"` or `"denied"`.

\- §5.4's third component — maximum one `reports.query()` call per invocation — is enforced as process-local state within the single running script invocation, not derived from a ledger read, and has no dedicated remaining-count field here. If it is the reason a call is denied, `binding` records `"per_invocation_limit"`, so the decision is still visible in the ledger even though nothing was read from the ledger to make it.

\### 6.3 Post-call event \(`event_type: "post_call_result"`\)

`call_id` — required \(already listed in 6.1\); this is how a post-call event is matched back to its pre-call event.

`outcome` — string: `"success"` or `"failure"`.

`error` — string or `null`. Populated when `outcome` is `"failure"`; `null` otherwise.

`actual_cost_units` — integer or `null`. `null` on every entry until it is independently verified whether Google's API responses expose actually-consumed quota in a client-visible way — unchanged from v1.0, and still unverified.

A post-call event intentionally does not repeat `script`, `operation`, `collection_id`, or `cost_model`. Those are owned by the pre-call event; a reader that needs them looks them up via `call_id`. This keeps each field single-sourced rather than duplicated and possibly-inconsistent across two lines.

A post-call event must be written whether the call succeeded or failed — a failed call may still have consumed quota, and even where it did not, an honest record of what was attempted requires the failure to be recorded, not just successes.

\---

\## 7. How Denied Calls Are Represented

A denied call is not an API call — it is a decision not to make one. It is represented entirely by a single pre-call event with `pre_call_check.decision: "denied"`.

No post-call event is ever written for a denied call, and none should ever be expected. This is a different kind of absence from an orphaned allowed attempt \(§10\): it is the complete, correct, terminal record of that `call_id`, not a gap. A reader distinguishes the two purely by `pre_call_check.decision` on the pre-call event — `"denied"` means no post-call event is coming, ever, by design; `"allowed"` means one is expected eventually, and its absence after some time is the orphan case §10 addresses.

\---

\## 8. Examples

\### 8.1 Known-cost call, allowed, succeeded \(a linked pair\)

```json
{"ledger_schema_version": "1.2", "entry_id": "a1111111-0000-4000-8000-000000000001", "call_id": "c1000000-0000-4000-8000-000000000001", "event_type": "pre_call_check", "timestamp_utc": "2026-08-12T18:03:11Z", "script": "video_inventory.py", "operation": "playlistItems.list", "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", "cost_model": "known", "estimated_cost_units": 1, "pre_call_check": {"remaining_run_ceiling_before_call": 46, "remaining_daily_budget_before_call": 947, "cooldown_ok": true, "binding": null, "decision": "allowed"}}
```

```json
{"ledger_schema_version": "1.2", "entry_id": "a2222222-0000-4000-8000-000000000002", "call_id": "c1000000-0000-4000-8000-000000000001", "event_type": "post_call_result", "timestamp_utc": "2026-08-12T18:03:12Z", "outcome": "success", "error": null, "actual_cost_units": null}
```

\### 8.2 Dynamic-cost Analytics call, allowed, succeeded \(a linked pair\)

```json
{"ledger_schema_version": "1.2", "entry_id": "a3333333-0000-4000-8000-000000000003", "call_id": "c2000000-0000-4000-8000-000000000002", "event_type": "pre_call_check", "timestamp_utc": "2026-08-12T18:03:14Z", "script": "analytics_snapshot.py", "operation": "reports.query", "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", "cost_model": "dynamic", "estimated_cost_units": null, "pre_call_check": {"policy": "analytics_call_frequency_v1", "invocations_remaining_in_window": 11, "cooldown_ok": true, "binding": null, "decision": "allowed"}}
```

```json
{"ledger_schema_version": "1.2", "entry_id": "a4444444-0000-4000-8000-000000000004", "call_id": "c2000000-0000-4000-8000-000000000002", "event_type": "post_call_result", "timestamp_utc": "2026-08-12T18:03:16Z", "outcome": "success", "error": null, "actual_cost_units": null}
```

\### 8.3 Denied call \(pre-call event only — no post-call event follows, ever\)

```json
{"ledger_schema_version": "1.2", "entry_id": "a5555555-0000-4000-8000-000000000005", "call_id": "c3000000-0000-4000-8000-000000000003", "event_type": "pre_call_check", "timestamp_utc": "2026-08-12T18:05:00Z", "script": "youtube_discovery.py", "operation": "search.list", "collection_id": null, "cost_model": "known", "estimated_cost_units": 1, "pre_call_check": {"remaining_run_ceiling_before_call": 46, "remaining_search_allocation_before_call": 0, "cooldown_ok": true, "binding": "search_allocation", "decision": "denied"}}
```

A reader must never sum `estimated_cost_units` across `cost_model: "known"` and `cost_model: "dynamic"` pre-call events as a single number, and must never count a `"denied"` pre-call event toward consumed budget — unchanged from v1.0's known/dynamic separation, now stated in terms of pre-call events specifically. A reader must also never sum a `search.list` pre-call event's `estimated_cost_units` into the shared-pool known-cost total — see §10.1.

\---

\## 9. snapshot\_id Linkage \(Indirect, Not a Field\)

Unchanged from v1.0. `snapshot_id` is not a field on any ledger event. A snapshot's `snapshot_id` does not exist until the snapshot builder finishes, after that script's API calls are already complete — attaching it to any ledger event would require rewriting an already-appended line, which the append-only design \(§4, §5\) exists to avoid.

Where a specific call's associated snapshot needs to be identified, the path is: pre-call event → `collection_id` → the matching `logs/collection_<timestamp>.json` record → that component's `produced_snapshot_id` \(already present per the collection-linkage work committed at `534c71c`\).

Standalone entries \(`collection_id: null`\) have no collection log to join to, and therefore no recoverable `snapshot_id` — consistent with how standalone snapshots already behave today.

The same `collection_id` linkage also supports the reverse lookup: given a collection log entry for one component, a reader can find every ledger event recorded for that `collection_id` and that component's `script`/`operation`, including any `"denied"` pre-call event — see Quota Governance Contract §9.3, which defines the resulting `quota_denied` field on each collection log entry.

\---

\## 10. Read Behavior, Orphan Handling, and Failure Handling

\### 10.1 Budget and frequency arithmetic reads pre-call events only

A reader computing current usage for a pre-call check considers only events where `event_type` is `"pre_call_check"` and `pre_call_check.decision` is `"allowed"`, filtered to `timestamp_utc` within the applicable rolling 24-hour window \(Quota Governance Contract §5.2\), not by calendar day.

For known-cost, shared-pool usage: sum `estimated_cost_units` across those filtered events, excluding `search.list` — `search.list` draws from a separate Google-side allocation \(Quota Governance Contract §4.1\) and must never be added into the shared-pool sum this section computes \(Quota Governance Contract §2, §5.2\). A reader computing `search.list`'s own usage does so separately: count pre-call-allowed events where `operation` is `"search.list"`, within the same rolling 24-hour window, using the same allowed-only pre-call-event filter as this section's other computations.

For the Analytics call-frequency policy \(Contract §5.4\): count those filtered events for `analytics_snapshot.py` / `reports.query`, and separately check the most recent such event's `timestamp_utc` against the 5-minute cooldown.

A `"denied"` pre-call event is excluded from both calculations — a denied call consumed no real quota and made no real attempt against the frequency ceiling.

\### 10.2 Orphan handling falls out of 10.1 automatically

An "allowed" pre-call event with no matching post-call event \(because the process crashed after the real API call, before the result could be written\) is still counted by 10.1, because 10.1 never looks for a post-call event in the first place — it only ever reads pre-call events. This is the fail-closed property the project's principles require, and it requires no separate orphan-detection mechanism: the arithmetic that already has to run for every ordinary call is what makes an orphaned attempt count.

Because the budget window is rolling \(§3\), an orphaned attempt's effect is also automatically bounded — it stops counting once its timestamp ages out of the trailing 24 hours, the same as any other entry, with no separate expiry rule needed.

Post-call events remain useful as an audit trail — did the call actually succeed, what was the error — but nothing in the enforcement arithmetic depends on one existing.

\### 10.3 Tolerate an incomplete final line

Unchanged from v1.0. The last line of the file may be incomplete if a write was interrupted mid-append. A reader skips an unparseable final line rather than failing the entire read. Every line before it was fully written by a prior, completed append and is trustworthy — this applies identically to pre-call and post-call events.

\### 10.4 Fail closed if the ledger cannot be read at all

Unchanged from v1.0. If the file is missing, unreadable, or otherwise inaccessible, the pre-call check must deny the call. Treating unreadable usage as zero usage would be a Missing ≠ Zero violation.

\### 10.5 Post-call write failure

If the API call succeeds \(or fails\) but the subsequent post-call write itself fails, the calling code must surface this clearly, consistent with the Quota Governance Contract's §10 fail-fast principle, rather than silently continuing as though the result had been recorded. Note that this specific failure mode no longer hides whether the call was attempted at all — the pre-call event already exists on disk by this point, per §4 through §5. What could be lost is only the outcome detail, not the fact of the attempt.

\### 10.6 Pre-call write failure

If the pre-call event itself cannot be written — the same class of reasons §10.4 treats as fail-closed for reads \(the ledger file or its containing directory is missing, unreadable, or otherwise inaccessible\) — the calling code must not proceed to make the API call. This is symmetric with §10.4: an unreadable ledger must deny a call rather than treat unreadable usage as zero; an unwritable ledger must equally deny a call rather than make an API call that could never be recorded, not even as an orphaned attempt \(§10.2\). An orphaned attempt still has a pre-call event for the arithmetic in §10.1 to count; a call made despite a failed pre-call write would have no event at all — a strictly worse gap than any this schema otherwise tolerates.

\---

\## 11. Implementation Note

Stage B1 implemented 2026-08-13: `src/quota_ledger.py`, per this schema exactly, with unit tests in `tests/test_quota_ledger.py`. No change to API-calling behavior — nothing in `channel_snapshot.py`, `video_inventory.py`, `analytics_snapshot.py`, `youtube_discovery.py`, or `collector.py` calls this module yet.

Two implementation decisions went beyond this document's literal text and were flagged for confirmation rather than silently assumed; see the human-facing delivery report for full reasoning:

\- A ledger file that has never been created is treated as zero prior entries \(not a §10.4 fail-closed case\), to avoid a bootstrap deadlock where the first-ever call could never succeed in creating the first entry. A ledger that exists but cannot be read remains a §10.4 fail-closed case.

\- A malformed line that is \*\*not\*\* the final line raises a read error rather than being silently skipped, since §10.3's tolerance is specifically for an interrupted final write, not unexplained mid-file corruption.

Stage B2.1 \(2026-08-13\) revised this schema from v1.1 to v1.2: §6.2's `pre_call_check` shape now records every applicable ceiling's remaining value plus a `binding` field instead of one undifferentiated `remaining_budget_before_call`; §10.1 excludes `search.list` from the shared-pool known-cost sum; §10.6 adds pre-call write failure handling. Stage B1's committed `write_pre_call_event()` still implements v1.1's single-field shape, and `compute_known_cost_usage()` still includes `search.list` in its sum — both now need a follow-up code change to match this schema. That code change is separate, future work requiring its own explicit approval, not carried out as part of this reconciliation pass.

Stage B2 \(integration into the four API-calling scripts, and actual enforcement of the Sec 5 policy limits\) is separate, future work requiring its own explicit approval, per the Quota Governance Contract §12.
