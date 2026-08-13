from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import os
import sys
import uuid

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_credentials
import quota_ledger


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "analytics"


def get_channel_id():
    snapshot_dir = BASE_DIR / "data" / "snapshots"

    files = sorted(
        snapshot_dir.glob("channel_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            "No channel snapshot found. Run channel_snapshot.py first."
        )

    with files[0].open("r", encoding="utf-8") as f:
        data = json.load(f)

    return data["channel"]["channel_id"]


def get_date_range():
    """
    Analytics reports require a start and end date.

    We use the previous 7 complete calendar days so that
    the initial snapshot has a stable reporting window.
    """

    today = datetime.now(timezone.utc).date()

    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=6)

    return (
        start_date.isoformat(),
        end_date.isoformat(),
    )


# NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md Sec 5.4 policy values.
# Analytics has no unit cost (Sec 4.3) -- these are call-frequency
# limits, not the 50-unit/1,000-unit policy in Sec 5.1/5.2, and must
# never be checked against RUN_CEILING_UNITS/DAILY_BUDGET_UNITS or
# compute_known_cost_usage (Sec 6). Local to this file for the same
# reason channel_snapshot.py's Sec 5.1-5.3 constants are local to it.
MAX_CALLS_PER_INVOCATION = 1
COOLDOWN = timedelta(minutes=5)
MAX_INVOCATIONS_PER_24H = 12
ANALYTICS_POLICY_NAME = "analytics_call_frequency_v1"


class QuotaDeniedError(Exception):
    """
    A pre-call check denied this API call (Contract Sec 6). Per Sec
    7.3 / Sec 10 this must propagate uncaught so the script exits
    without producing a snapshot -- it must never be caught and
    degraded to a partial result.
    """


def _evaluate_analytics_pre_call_check(
    calls_made_this_invocation,
    script="analytics_snapshot.py",
    path=quota_ledger.LEDGER_PATH,
    now=None,
):
    # Builds and evaluates the v1.2 pre_call_check dict (Ledger Schema
    # Sec 6.2) for the dynamic-cost Analytics operation. Checks the
    # per-invocation limit, then the cooldown, then the rolling-24h
    # invocation ceiling -- Sec 5.4's own listed order -- and reports
    # whichever binds first if more than one would deny.
    #
    # calls_made_this_invocation is process-local by design (Sec 5.4's
    # first component; Ledger Schema Sec 6.2's own note that this
    # component "has no dedicated remaining-count field" and "is
    # enforced as process-local state"). Never read from the ledger's
    # persisted history -- the same process-local pattern already used
    # for channel_snapshot.py's run_ceiling_used (Contract Sec 5.1).
    now = now or quota_ledger.utc_now()
    entries = quota_ledger.read_entries(path=path)

    invocations_used = quota_ledger.compute_analytics_call_count(
        entries, now - timedelta(hours=24), now, script=script
    )
    invocations_remaining = MAX_INVOCATIONS_PER_24H - invocations_used

    last_invocation = quota_ledger.most_recent_invocation_timestamp(entries, script)
    cooldown_ok = last_invocation is None or (now - last_invocation) >= COOLDOWN

    if calls_made_this_invocation >= MAX_CALLS_PER_INVOCATION:
        binding, decision = "per_invocation_limit", quota_ledger.DENIED
    elif not cooldown_ok:
        binding, decision = "cooldown", quota_ledger.DENIED
    elif invocations_remaining <= 0:
        binding, decision = "invocation_ceiling", quota_ledger.DENIED
    else:
        binding, decision = None, quota_ledger.ALLOWED

    return {
        "policy": ANALYTICS_POLICY_NAME,
        "invocations_remaining_in_window": invocations_remaining,
        "cooldown_ok": cooldown_ok,
        "binding": binding,
        "decision": decision,
    }


def fetch_channel_analytics(
    youtube_analytics,
    channel_id,
    start_date,
    end_date,
    collection_id=None,
    calls_made_this_invocation=0,
    path=quota_ledger.LEDGER_PATH,
):
    pre_call_check = _evaluate_analytics_pre_call_check(
        calls_made_this_invocation, path=path
    )

    call_id = quota_ledger.write_pre_call_event(
        script="analytics_snapshot.py",
        operation="reports.query",
        collection_id=collection_id,
        cost_model=quota_ledger.DYNAMIC_COST_MODEL,
        estimated_cost_units=None,
        pre_call_check=pre_call_check,
        path=path,
    )

    if pre_call_check["decision"] == quota_ledger.DENIED:
        # Contract Sec 7.3 / Sec 10: propagate uncaught, no snapshot
        # produced -- this must not be caught and degraded.
        raise QuotaDeniedError(
            "reports.query denied by quota governance "
            f"(binding={pre_call_check['binding']!r})"
        )

    metrics = ",".join(
        [
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "subscribersGained",
            "subscribersLost",
            "likes",
            "comments",
            "shares",
        ]
    )

    try:
        response = (
            youtube_analytics.reports()
            .query(
                ids=f"channel=={channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics=metrics,
            )
            .execute()
        )
    except Exception as exc:
        # Ledger Schema Sec 6.3: a post-call event is written on
        # failure too, then the original exception still propagates.
        quota_ledger.write_post_call_event(
            call_id=call_id,
            outcome="failure",
            error=str(exc),
            path=path,
        )
        raise

    quota_ledger.write_post_call_event(
        call_id=call_id,
        outcome="success",
        error=None,
        path=path,
    )

    return response


def main():
    print("===== NIK YOUTUBE ANALYTICS SNAPSHOT =====")

    collection_id = os.environ.get("NIK_COLLECTION_ID")

    credentials = get_credentials()

    youtube_analytics = build(
        "youtubeAnalytics",
        "v2",
        credentials=credentials,
    )

    channel_id = get_channel_id()

    start_date, end_date = get_date_range()

    analytics_response = fetch_channel_analytics(
        youtube_analytics,
        channel_id,
        start_date,
        end_date,
        collection_id=collection_id,
    )

    snapshot = {
        "schema_version": "1.0",
        "snapshot_type": "youtube_channel_analytics",
        "snapshot_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source": "youtube_analytics_api",
        "api_version": "v2",

        # Provenance (collection linkage pass). None when this builder
        # runs standalone, outside collector.py.
        "collection_id": collection_id,

        "channel_id": channel_id,

        # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §7). A single
        # reports().query() call, no pagination concept, so
        # pagination_completed is None rather than True/False.
        # No "evidence.raw_response" block is added below — the
        # existing "analytics" field already holds the complete,
        # untouched API response and would otherwise be duplicated.
        "retrieval_metadata": {
            "retrieved_resources": ["youtubeAnalytics#resultTable"],
            "pagination_completed": None,
            "errors": [],
            "warnings": [],
        },

        "reporting_period": {
            "start_date": start_date,
            "end_date": end_date,
        },

        "metrics_requested": [
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "subscribersGained",
            "subscribersLost",
            "likes",
            "comments",
            "shares",
        ],

        "analytics": analytics_response,
    }

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    output_file = (
        OUTPUT_DIR
        / f"channel_analytics_{timestamp}.json"
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            snapshot,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("ANALYTICS: SUCCESS")
    print("CHANNEL ID:", channel_id)
    print("PERIOD:", start_date, "to", end_date)

    rows = analytics_response.get("rows", [])

    if rows:
        print("ANALYTICS ROW:", rows[0])
    else:
        print("ANALYTICS ROWS: 0")

    print()
    print("OUTPUT:")
    print(output_file.resolve())
    print()
    print("============================================")


if __name__ == "__main__":
    main()
