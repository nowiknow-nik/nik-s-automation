\# NIK YouTube Quota Governance Contract

\*\*Version:\*\* 1.4

\*\*Status:\*\* Policy Approved for Implementation Planning; Ledger Module Implemented \(Stage B1\); Contract/Schema Reconciliation Complete \(Stage B2.1\) — Enforcement Integration Not Yet Authorized \(Google-published facts verified in §4; NIK policy values in §5, including the Analytics policy in §5.4, are approved as policy; the quota ledger module itself is implemented per §9.2 but not yet integrated into any API-calling script, and no API-calling behavior has changed; §6, §7.3, §8, §9.2, §9.3, and §10 were revised 2026-08-13 to correct how `search().list()` is accounted for and to codify pagination-ceiling and pre-call-write failure behavior ahead of Stage B2 — see §11 and §12\)

\*\*System:\*\* NIK YouTube Integration

\---

\## 1. Purpose

This contract defines how the NIK YouTube integration governs its consumption of YouTube API quota.

The purpose is to ensure that:

\- API usage remains within YouTube's own assigned limits

\- API usage remains within NIK's own, separately-defined internal safety limits

\- search and pagination behavior stays bounded and deliberate, never open-ended

\- quota and call usage is observable, not just success or failure

This layer governs API consumption. It does not govern what the collected data means.

\---

\## 2. Core Principle

The system must distinguish between:

1\. YOUTUBE-ASSIGNED QUOTA COST

2\. NIK-ASSIGNED INTERNAL SAFETY LIMITS

YouTube-assigned quota cost is fixed by Google and is now verified against Google's own current developer documentation \(§4\). It is not estimated or invented in this contract.

NIK-assigned internal safety limits are additional constraints this project chooses to enforce on itself, independent of, and deliberately stricter than, YouTube's own limits. NIK policy values appear in §5 \(including §5.4\) and §7, each explicitly marked as a NIK policy decision, not a Google requirement.

These two must never be silently conflated. A NIK-assigned limit is not evidence of YouTube's actual quota cost, and a verified YouTube-assigned cost does not itself set NIK's internal ceiling — NIK's ceiling is deliberately more conservative and is a separate decision.

\---

\## 3. Scope

This contract governs:

\- `channel_snapshot.py` — `channels().list()`

\- `video_inventory.py` — `playlistItems().list()`, `videos().list()`

\- `analytics_snapshot.py` — `reports().query()` \(YouTube Analytics API\)

\- `youtube_discovery.py` — `channels().list()`, `playlists().list()`, `playlistItems().list()`, `search().list()`

\- any future code that calls a YouTube Data API or YouTube Analytics API operation

`collector.py` makes no direct API calls itself — it orchestrates the three scripts above as subprocesses — and is in scope only insofar as it is the enforcement point for run-level and daily limits \(§5\).

`change_detection.py` makes no API calls at all and is out of scope entirely.

\---

\## 4. Cost Classification

\### 4.1 YouTube-Assigned Quota Cost \(External — Google-Defined, Verified\)

Verified against two official Google sources: the \[quota cost table\]\(https://developers.google.com/youtube/v3/determine\_quota\_cost\) and the \[YouTube Data API overview\]\(https://developers.google.com/youtube/v3/getting-started\), both fetched and cross-checked on 2026-08-12, and independently re-checked by human review against Google's `search.list` reference page and quota calculator on the same date.

Operation: `channels().list()`

Called by: `channel_snapshot.py` → `get_channel()`; `youtube_discovery.py` → `main()`

Verified YouTube quota cost: \*\*1 unit per call.\*\* Source: Quota costs for API requests table \(determine\_quota\_cost\).

\---

Operation: `playlists().list()`

Called by: `youtube_discovery.py` → `main()`

Verified YouTube quota cost: \*\*1 unit per call.\*\* Source: same table.

\---

Operation: `playlistItems().list()`

Called by: `video_inventory.py` → `fetch_video_inventory()` \(paginated loop\); `youtube_discovery.py` → `main()` \(single call\)

Verified YouTube quota cost: \*\*1 unit per call.\*\* Source: same table. Because this call site is paginated, the true per-run cost is `1 unit × number of pages fetched`, not a fixed number — this is exactly why §7 requires an explicit page ceiling regardless of the low per-call cost.

\---

Operation: `videos().list()`

Called by: `video_inventory.py` → `enrich_video_statistics()` \(batched loop, 50 IDs per call\)

Verified YouTube quota cost: \*\*1 unit per call\*\* \(each call can request up to 50 video IDs at once — the batch size does not change the per-call unit cost\). Source: same table. Same pagination caveat as above applies to total batches per run.

\---

Operation: `search().list()`

Called by: `youtube_discovery.py` → `main()`

Verified YouTube quota cost: \*\*1 unit per call\*\*, but governed by a \*\*separate daily allocation of 100 calls\*\*, distinct from the shared 10,000-unit daily pool that covers every other operation in this table. Source: both the quota cost table and the API overview page state this explicitly \("Projects that enable the YouTube Data API have a default quota allocation of 100 `search.list` calls ... and 10,000 units per day combined for all other endpoints"\). Independently confirmed by human review: Google's current `search.list` reference states directly that quota impact is "100 calls per day" with "each call has a quota cost of 1 unit."

\*\*Correction against a common misconception:\*\* several third-party blog sources found during this research describe `search.list` as costing 100 units per call. Google's own documentation does not say this — it states each `search.list` call costs 1 unit, drawn from its own 100-call/day bucket, not from a 100-unit-per-call charge against the shared pool. This contract follows Google's own primary documentation, not the secondary sources, and flags the discrepancy so it isn't silently repeated.

\### 4.2 Default Daily Allocation \(External — Google-Defined\)

Per the same two sources: a project enabling the YouTube Data API v3 receives, by default, \*\*10,000 units per day\*\* combined for all endpoints other than `search.list` and `videos.insert`, plus a separate \*\*100 calls per day\*\* specifically for `search.list` \(and a separate 100 calls/day for `videos.insert`, not currently used by this project\).

Requesting quota above the default requires a compliance audit \(Capability Map cross-reference: this project currently operates entirely within read-only scopes and has not requested any quota increase\). Source: \[Quota and Compliance Audits\]\(https://developers.google.com/youtube/v3/guides/quota\_and\_compliance\_audits\).

\### 4.3 YouTube Analytics API — `reports().query()` \(External — Google-Defined, Verified As Unpublished/Dynamic\)

Called by: `analytics_snapshot.py` → `fetch_channel_analytics()`

This operation is explicitly \*\*not\*\* assigned an invented fixed unit cost in this contract, per instruction. Research findings, checked against four official pages — the \[YouTube Analytics API quota introduction\]\(https://developers.google.com/youtube/analytics/v1/quota\), the \[reports.query reference\]\(https://developers.google.com/youtube/analytics/reference/reports/query\), the \[API overview\]\(https://developers.google.com/youtube/analytics\), and the \[data model page\]\(https://developers.google.com/youtube/analytics/data\_model\) — found no fixed per-call unit cost published anywhere.

The quota introduction page states directly: \*"The API server evaluates each query to determine its quota cost."\* This confirms Google evaluates cost dynamically, per query, rather than publishing a static number the way it does for the Data API's list methods.

Classification per instruction: `reports().query()` is a \*\*separately governed Analytics API operation with cost/limit semantics that require runtime/API-project monitoring, not a fixed unit value.\*\* Any quota governance logic covering this operation must treat its cost as unknown-until-observed at call time, not as a constant that can be budgeted against in advance the way Data API calls can. Because no unit cost exists for this operation, it is governed separately by call frequency instead — see §5.4.

\### 4.4 Data API / Analytics API Pool Relationship \(Verified With Reasonable Confidence, Not a Single Explicit Statement\)

No single official sentence found during this research states outright "these two APIs have separate quota pools." What was found, and is being relied on instead:

\- The YouTube Data API v3 and YouTube Analytics API are registered as two distinct, independently-enabled Google Cloud API services — `youtube.googleapis.com` and `youtubeanalytics.googleapis.com` respectively \(confirmed via the Google Cloud Console API library listing for the Analytics API\). Distinct API services in Google Cloud are independently quota-managed by construction of the platform.

\- Every quota figure found for the Data API \(10,000 units/day, 100 `search.list` calls/day\) appears only on Data API documentation pages and is never mentioned on any Analytics API page checked.

\- The Analytics API's own quota page describes a wholly different model \(dynamic per-query evaluation\) with no reference to the Data API's unit system at all.

Conclusion: these are governed separately, with reasonable confidence, based on structural evidence rather than one explicit confirming sentence. This is marked as resolved-with-caveat rather than fully resolved, and human review has explicitly confirmed this labeling should stand rather than be upgraded to "verified fact" — see §12.

\### 4.5 NIK-Assigned Safety Classification \(Internal — Separate From 4.1–4.4\)

Independent of the now-verified Google costs above, this project continues to treat `reports().query()` \(unpublished, dynamic cost\) and `search().list()` \(separately-bucketed, most restrictive daily allocation of any operation in scope — 100 calls versus 10,000 units shared across everything else\) as the two highest-priority operations for internal restriction. This was the working assumption in the prior draft \(§4.2 of v1.0\); the verified numbers in §4.1–4.4 now support it directly rather than as a precaution against the unknown.

\---

\## 5. Internal Safety Limits \(NIK-Defined, Distinct From §4.1–4.4\)

Every value in this section is a \*\*NIK policy decision\*\*, not a Google requirement. None of these numbers appear anywhere in Google's documentation.

The values in 5.1 through 5.4 were approved for implementation planning on 2026-08-12. Approval of a policy value is not approval of enforcement code. Enforcement is separate, staged, future work \(§11\), and each stage requires its own explicit approval before implementation begins.

\### 5.1 Per-Run Ceiling — 50 units per script invocation

Reasoning: a full `collector.py` run today makes on the order of 3–6 Data API calls total \(1 `channels.list`, 1–2 `playlistItems.list` pages, 1 `videos.list` batch — the channel currently has 0 published videos per Capability Map §11\) plus 1 Analytics `reports().query()` call. 50 units gives roughly an order of magnitude of headroom for legitimate channel growth while still being small enough to catch a runaway loop long before it could approach the 10,000-unit daily pool.

Status: Approved for implementation planning, 2026-08-12. Not yet implemented in code.

\### 5.2 Daily NIK Safety Budget — 1,000 units per rolling 24-hour period

Reasoning: this is 10% of Google's verified 10,000-unit default daily allocation \(§4.2\). Deliberately conservative — it leaves 90% headroom against the actual Google ceiling for margin of error, leaves room if the same Google Cloud project is ever used for anything else, and still comfortably covers many multiples of today's actual per-run usage even if the collection were run several times a day.

Status: Approved for implementation planning, 2026-08-12. Not yet implemented in code. Google's own ceiling \(§4.2\) is not being treated as NIK's ceiling — this is deliberately far below it, per §2's core principle.

\### 5.3 Rate Limiting / Cooldown — 5-minute minimum between invocations of the same script

Reasoning: nothing about this project's current, manually-run stage requires channel or analytics data more often than every few minutes. A 5-minute floor is generous enough not to interfere with legitimate manual re-runs \(for example, re-running after fixing a credential issue\) while still preventing an accidental tight loop — human or, later, scheduled — from burning quota rapidly.

Status: Approved for implementation planning, 2026-08-12. Not yet implemented in code.

\### 5.4 Analytics-Specific Safety Policy — Call-Frequency Based, Not Unit-Based

`reports().query()` \(§4.3\) has no fixed, published Google quota cost — Google evaluates its cost dynamically, per query. It therefore cannot be governed by the unit-based budgets in 5.1 or 5.2, which require a countable cost value this operation does not have.

This policy governs call frequency instead of quota units. It is explicitly a NIK-imposed safety limit, not a claim about any Google-defined quota — consistent with §2's core principle that a NIK-assigned limit must never be presented as though it were a YouTube-assigned one.

Approved policy, 2026-08-12:

\- Maximum \*\*1\*\* `reports().query()` call per `analytics_snapshot.py` invocation.

\- Minimum \*\*5-minute\*\* cooldown between `analytics_snapshot.py` invocations \(the same value as the general §5.3 cooldown, applied specifically to this script\).

\- Maximum \*\*12\*\* `analytics_snapshot.py` invocations in any rolling 24-hour period.

Reasoning, per human review: this is a call-frequency ceiling adopted while the project is still learning the Analytics API's actual dynamic-cost behavior, not a value derived from any unit budget — no such budget exists for this operation. Twelve invocations per rolling 24 hours is a hard, simple bound chosen for this stage of the project, not a calculated figure.

Status: Approved for implementation planning, 2026-08-12. Not yet implemented in code.

\---

\## 6. Pre-Call Enforcement Rule

Enforcement branches by cost model, per §4.5's known/dynamic distinction. It is not one rule.

For any known-cost, shared-pool operation \(§4.1: `channels.list`, `playlists.list`, `playlistItems.list`, `videos.list`\), the calling code must be able to demonstrate that the call is within:

\(a\) the per-run ceiling \(§5.1\)

\(b\) the daily budget \(§5.2\)

\(c\) any applicable cooldown requirement \(§5.3\)

For `search.list` \(§4.1\), which draws from Google's own separate rolling allocation rather than the shared pool \(§4.1, §4.5\), the calling code must instead be able to demonstrate that the call is within:

\(a\) the per-run ceiling \(§5.1\)

\(b\) its own controlled-search policy \(§8\)

`search.list` must never be checked against the daily budget in §5.2 — that budget is sized against the shared pool `search.list` does not draw from, and checking it there would be exactly the silent conflation §2 prohibits.

For the dynamic-cost Analytics operation \(§4.3: `reports().query()`\), the calling code must instead be able to demonstrate that the call is within the Analytics-specific call-frequency policy \(§5.4\). This operation must never be checked against the unit-based budgets in 5.1 or 5.2 — it has no unit value to check against them.

In all cases: no operation may be called solely because the calling script reached that line of code — the call must be shown to be within its applicable policy first.

This directly implements the Capability Map §6 agent rule: "NO AGENT MAY PERFORM UNBOUNDED SEARCH OR REPETITIVE API POLLING." Today, no code enforces this rule anywhere in the codebase. This contract requires it. Implementing the enforcement itself is separate, future work, gated per §11 and sequenced per the staged implementation plan referenced in §12.

\---

\## 7. Pagination and Batch Bounds

Two call sites currently loop without an explicit ceiling:

\- `playlistItems().list()` pagination in `video_inventory.py`'s `fetch_video_inventory()` — loops on `nextPageToken` until the token is exhausted, with no maximum page count.

\- `videos().list()` batching in `video_inventory.py`'s `enrich_video_statistics()` — loops over every video in batches of 50, with no maximum batch count.

\### 7.1 Pagination Ceiling — 20 pages maximum \(1,000 videos at 50 per page\)

Reasoning: the channel currently has 0 published videos \(Capability Map §11\), so there is no real usage data to size this against. 1,000 videos is chosen as a round, generously large ceiling relative to the channel's current and near-term expected scale — large enough to be very unlikely to interfere with legitimate collection, small enough to guarantee the loop terminates. At 1 unit per page \(§4.1\), the worst case under this ceiling is 20 units for this one call site — well inside both the per-run \(§5.1\) and daily \(§5.2\) budgets.

Status: Approved for implementation planning, 2026-08-12. Not yet implemented in code. The basis for this value remains "generous round number given current channel scale," not usage data, since none exists yet — that basis does not change by being approved.

\### 7.2 Batch Ceiling — Derived From 7.1, Not Independent

Because `enrich_video_statistics()`'s batches are built directly from the video list `fetch_video_inventory()` already collected, a 1,000-video pagination ceiling \(§7.1\) mechanically implies a maximum of 20 batches of 50 \(`videos.list` calls\) for that same run. This contract does not propose a second, independent batch ceiling — doing so risks the two numbers drifting out of sync. If §7.1's value changes, this figure changes with it automatically once implemented correctly.

Status: Approved for implementation planning \(as a consequence of 7.1\), 2026-08-12. Not yet implemented in code.

\### 7.3 Behavior When a Ceiling Is Reached

Reaching the pagination ceiling \(§7.1\) or the batch ceiling \(§7.2\) is a governance failure, not a soft stopping point. The pre-call check for the page or batch that would exceed the ceiling must be denied \(§6\), using the same denial mechanism as any other pre-call check. The calling script must not catch this denial and degrade to emitting a snapshot built from whatever pages or batches were already fetched — it must let the failure propagate and exit without producing a snapshot, per §10. A snapshot must never be emitted as though collection completed when it was actually stopped early by this ceiling — partial data must never be represented as though it were complete data.

Status: Approved 2026-08-13. Not yet implemented in code. Depends on the enforcement mechanism required by §6, which is also not yet implemented.

\---

\## 8. Controlled Search Requirements

`search().list()` \(Capability Map §3.6, §6\) requires a controlled search policy before any expanded use. This section defines what such a policy must satisfy. It does not implement one.

A controlled search policy must:

\- operate under an explicit per-run cap \(§5.1\) — the shared daily budget \(§5.2\) does not govern this operation \(§6\) — and its own controlled-search policy: a maximum of 100 calls per rolling 24-hour period, informed by Google's own separate allocation \(§4.1\) but tracked on NIK's own rolling-window basis, consistent with how §5.2 and §5.4 already measure usage; never an unbounded loop

\- additionally respect Google's own separate 100-call/day bucket for this operation specifically \(§4.1\) — a NIK-internal cap alone is not sufficient, since this operation has a Google-imposed ceiling independent of NIK's own budget

\- not be exposed as a capability any agent can invoke freely or arbitrarily — per Capability Map §3.6's own words, it "should NOT be exposed as an unrestricted agent capability"

\- treat its call parameters \(channel scope, result size, type filter\) as required, not optional — a call issued without an explicit scope and an explicit result-size limit should not be permitted

\- require the same approval gate as any other quota-governance change before its current single, narrowly-scoped call site in `youtube_discovery.py` is expanded to any new call site or broader parameters

This section defines requirements only. Enforcement is future work, gated per §11.

\---

\## 9. Quota and Call Telemetry

Quota governance requires call-level telemetry that does not exist today. Per the inspection, today's logs record success or failure and output provenance — never call counts or cost.

\### 9.1 Storage Model — Decided

Three options were compared: extending the existing collection log; a separate quota ledger; dedicated per-call telemetry records. A separate quota ledger was recommended and is now approved: a dedicated, append-only record that every API-calling script writes to directly, regardless of whether it was invoked via `collector.py` or standalone.

\### 9.2 Ledger Schema — Finalized and Approved \(v1.2\)

The exact ledger schema, field by field, is defined in a companion document: `NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md`. This mirrors the existing relationship between `NIK_YOUTUBE_SNAPSHOT_SCHEMA.md` and `NIK_YOUTUBE_DATA_COLLECTION_CONTRACT.md` — this contract states the governing principles; the schema document states the precise structure.

Summary \(full detail in the schema document, now at v1.2\):

\- Location: `logs/quota_ledger.jsonl`

\- Format: JSONL, append-only. Each call attempt is represented by a pre-call event \(`pre_call_check`\), written before the API call, plus a post-call event \(`post_call_result`\), written after — for a call that was allowed. A denied call has only the pre-call event; no API call was made, so no post-call event exists or is expected. The two events, when both exist, are linked by a shared `call_id`.

\- `collection_id`: nullable, following the same pattern already used on snapshots. Carried on the pre-call event.

\- `snapshot_id`: not attached directly to any ledger event; recoverable via `collection_id` → the matching collection log → that component's `produced_snapshot_id`.

\- Known-cost pre-call events \(§4.1 operations\) carry a numeric `estimated_cost_units`; dynamic-cost pre-call events \(§4.3\) carry `estimated_cost_units: null` — the two must never be summed together. `search.list` events are known-cost but are excluded from the shared-pool sum entirely, per §6 — see the schema document's §10.1.

\- Each pre-call event's `pre_call_check` records every ceiling that actually applies to its operation \(per-run, daily, cooldown, or the search/Analytics-specific equivalents\) as a remaining value, plus a `binding` field naming which one, if any, was the reason for a denial — never a single undifferentiated remaining-budget number.

\- `actual_cost_units`, on a post-call event, is `null` until it is independently verified whether Google's API responses expose actually-consumed quota in a client-visible way.

\- Budget and frequency arithmetic reads pre-call events only, filtered to an `"allowed"` decision — it never waits on or requires a matching post-call event. This is what ensures an interrupted process cannot make a real, quota-consuming API call disappear from quota accounting entirely: an "allowed" pre-call event with no post-call event still counts.

\- A pre-call check that cannot read the ledger must fail closed \(deny the call\), not treat unreadable usage as zero usage.

\- A pre-call check whose own pre-call event cannot be written must also fail closed \(deny the call, and not proceed to the API call\) — see the schema document's §10.6.

\- A reader must tolerate an incomplete final line \(for example, from an interrupted write\) without failing the entire read.

Status: Schema v1.1 approved 2026-08-13, resolving a pre/post-call entry lifecycle issue identified during human review of the original single-entry design \(schema v1.0\). Ledger module implementation \(Stage B1: writes, reads, and policy-calculation helpers, with no integration into any API-calling script\) is approved and was carried out the same date. Schema revised to v1.2 the same date \(Stage B2.1 reconciliation\): `pre_call_check` now records every applicable ceiling plus a `binding` field, `search.list` is excluded from the shared-pool read, and pre-call write failure is codified as fail-closed. Stage B1's committed code implements schema v1.1's shape and requires a follow-up update to match v1.2 — separate, future work, not carried out as part of this reconciliation. Integration into the API-calling scripts \(Stage B2\) remains separately gated — see §11 and the staged implementation sequence referenced in §12.

\### 9.3 Collection-Log Denial Visibility

Per the inspection that opened this section, today's collection log \(written by `collector.py` to `logs/collection_<timestamp>.json`\) records only `success: true/false` and output provenance for each component — it cannot distinguish a component that failed for an external reason \(an API error, a code defect\) from a component that was correctly stopped by this contract's own governance \(a pre-call denial, §6\). Both currently look identical from the collection log alone: a non-zero exit and whatever text landed in `stderr`.

Once enforcement \(§6\) is implemented, each component's entry in the collection log must carry a `quota_denied` field: `true` if any pre-call event for that component's run was denied by governance, `false` otherwise. The recommended mechanism is to reuse the same `collection_id` linkage already used to recover `produced_snapshot_id` \(`NIK_YOUTUBE_SNAPSHOT_SCHEMA.md`'s provenance pass\): after a component subprocess finishes, look up whether any pre-call event for that `collection_id` was recorded with `pre_call_check.decision: "denied"` \(Ledger Schema §6.2, §9\).

`quota_denied` is a boolean signal only. Detailed denial reasoning — which ceiling was binding, what the remaining budget was — is not duplicated into the collection log; it already exists in the quota ledger itself \(Ledger Schema §6.2's `binding` field\) and is reached from a collection log entry via the same `collection_id` lookup, not copied.

Status: Approved 2026-08-13. Not yet implemented in code. Depends on the enforcement mechanism required by §6, which is also not yet implemented.

\---

\## 10. Failure Behavior \(Fail-Fast, No Retry\)

All API-calling code today fails fast: a failed call raises an exception and the invoking script exits without producing a partial snapshot \(see `NIK_YOUTUBE_SNAPSHOT_SCHEMA.md`'s Implementation Note\).

This fail-fast requirement applies identically when a call is stopped by this contract's own governance — a pre-call denial \(§6\), including a denial triggered by the pagination or batch ceiling \(§7.3\) — as when a call fails for an external reason such as an API error. Both must result in the invoking script exiting without producing a partial snapshot. A governance-triggered stop must never be treated as a softer case that is allowed to degrade to partial output.

This contract codifies that as the current required behavior, not merely an observed one. No retry-on-failure logic may be added to any operation in §4.1 or §4.3 without first satisfying this contract's enforcement requirements \(§6\) — a retry loop added before quota governance is in place would directly reintroduce the repetitive-polling risk this contract exists to prevent.

If retry logic is proposed in the future, it requires its own explicit approval, and must be evaluated against §5's limits before being added, not layered on afterward.

\---

\## 11. Automation Readiness Gate

Capability Map §14 item 10 \("NIK Automation integration"\), and any other form of scheduled or triggered execution of `collector.py`, `youtube_discovery.py`, or any script within §3's scope, must not be enabled until:

1\. This contract's open items \(§12\) are resolved and approved.

2\. The enforcement mechanisms required by §6 are implemented.

3\. That implementation is verified working, not merely written — using the same real-environment verification standard already established for the provenance/linkage work: human verification in the actual Windows `.venv`, not a substitute environment alone.

Per the inspection, the only reason excessive API usage hasn't happened so far is that nothing is scheduled at all today. That is an accident of the project's current stage, not a safeguard, and must not be relied upon once automation is introduced.

\---

\## 12. Open Items \(Updated Register\)

\*\*Resolved from authoritative Google sources:\*\*

1\. Per-operation YouTube quota costs \(§4.1\) — all five Data API operations verified at 1 unit per call; `search.list` additionally confirmed to draw from its own separate 100-call/day bucket rather than the shared pool. Independently cross-checked by human review against Google's `search.list` reference and quota calculator, 2026-08-12.

2\. Default daily allocation \(§4.2\) — 10,000 units/day shared pool, plus 100 calls/day each for `search.list` and `videos.insert`.

3\. `reports().query()` cost model \(§4.3\) — confirmed as dynamically evaluated per query by Google's own documentation, with no fixed unit cost published.

\*\*Resolved with reasonable confidence, intentionally not upgraded to "confirmed":\*\*

4\. Data API / Analytics API pool relationship \(§4.4\) — reasoned as separately governed from structural evidence, not from one explicit Google statement. Human review explicitly declined to upgrade this to a verified fact; it stays labeled as reasoned-with-confidence.

\*\*Approved as policy for implementation planning \(not yet implemented in code\):\*\*

5\. Per-run ceiling — 50 units \(§5.1\). Approved 2026-08-12.

6\. Daily NIK safety budget — 1,000 units \(§5.2\). Approved 2026-08-12.

7\. Cooldown between invocations — 5 minutes \(§5.3\). Approved 2026-08-12.

8\. Pagination ceiling — 20 pages / 1,000 videos \(§7.1\); batch ceiling derived automatically \(§7.2\). Approved 2026-08-12.

9\. Analytics-specific call-frequency policy \(§5.4\) — 1 call per invocation, 5-minute cooldown, 12 invocations per rolling 24 hours. Approved 2026-08-12.

10\. Quota ledger architecture — approved 2026-08-12. Schema revised to v1.1 and approved 2026-08-13, resolving a pre/post-call entry lifecycle issue identified during human review \(two linked events per call attempt, rather than one — see `NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md` §4\). Full field-level schema in that document; summarized in §9.2 above.

11\. Quota governance reconciliation \(Stage B2.1\) — `search.list` accounting corrected to exclude it from the shared daily budget while retaining it under the per-run ceiling and defining its own rolling-24h search allocation \(§6, §8\); pagination/batch ceiling behavior codified as a hard governance failure producing no snapshot \(§7.3, §10\); pre-call ledger write failure codified as fail-closed \(§9.2\); a collection-log denial-visibility requirement added \(§9.3, `quota_denied` field\). Approved 2026-08-13. Not yet implemented in code.

\*\*Still genuinely open, not resolved by this revision:\*\*

12\. Whether Google's API responses \(Data API or Analytics API\) expose actually-consumed quota per call in a client-visible way. Unverified. `actual_cost_units` remains `null` in the ledger schema until this is independently checked — this contract does not guess at an answer.

\*\*Not yet authorized regardless of the above:\*\*

Enforcement code implementing any of items 5–11 is separate, future work. Approval of a policy value is not approval to write, test, or run the code that enforces it. Per human review, implementation is staged — a ledger module first, without changing any API behavior; then enforcement integration; then real-environment verification; then commit and push — and each stage requires its own separate, explicit approval before the next begins. Stage B1 \(the ledger module itself: append-only writes, reads, and policy-calculation helpers, with no integration into any API-calling script\) was approved and carried out 2026-08-13, and does not require a further per-item approval to have begun. Stage B2.1 \(contract and ledger schema reconciliation: correcting `search.list`'s accounting, codifying pagination-ceiling and pre-call-write failure behavior, and adding the collection-log denial-visibility requirement\) was also approved and carried out 2026-08-13, revising this contract to v1.4 and the companion ledger schema to v1.2 — it changed no code and authorizes none. Stage B2 \(integration into `channel_snapshot.py`, `video_inventory.py`, `analytics_snapshot.py`, `youtube_discovery.py`, and `collector.py`\) and every stage after it remain separately gated and are not yet approved.
