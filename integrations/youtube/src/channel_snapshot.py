import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "snapshots"

sys.path.insert(0, str(BASE_DIR / "src"))

from auth import get_credentials
import quota_ledger


# ---------------------------------------------------------
# QUOTA GOVERNANCE (Stage B2.2b)
# ---------------------------------------------------------

# NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md Sec 5.1-5.3 policy values.
# quota_ledger.py supplies usage facts only, not policy -- "this
# module does not decide whether to allow or deny a call" is its own
# module docstring's wording -- so comparing those facts against these
# ceilings belongs here, in the calling script. Local to this file for
# now: if video_inventory.py, analytics_snapshot.py, and
# youtube_discovery.py end up needing the identical known-cost/
# shared-pool comparison verbatim, centralizing it is a well-motivated
# small refactor once that duplication actually exists, not before.
RUN_CEILING_UNITS = 50
DAILY_BUDGET_UNITS = 1000
COOLDOWN = timedelta(minutes=5)


class QuotaDeniedError(Exception):
    """
    A pre-call check denied this API call (Contract Sec 6). Per Sec
    7.3 / Sec 10 this must propagate uncaught so the script exits
    without producing a snapshot -- it must never be caught and
    degraded to a partial result.
    """


def _evaluate_known_cost_pre_call_check(
    run_ceiling_used, script, path=quota_ledger.LEDGER_PATH, now=None
):
    # Builds and evaluates the v1.2 pre_call_check dict (Ledger Schema
    # Sec 6.2) for a known-cost, shared-pool operation. Checks the run
    # ceiling, then the daily budget, then the cooldown -- Contract
    # Sec 6's own (a)/(b)/(c) order -- and reports whichever binds
    # first if more than one would deny.
    #
    # run_ceiling_used is process-local by design (Contract Sec 5.1,
    # clarified 2026-08-13): the per-run ceiling is scoped per
    # individual script invocation, never read from the ledger's
    # persisted history and never aggregated across a collector.py
    # collection's other subprocesses -- the same process-local
    # pattern already used for the Sec 5.4 Analytics per-invocation
    # limit.
    now = now or quota_ledger.utc_now()
    entries = quota_ledger.read_entries(path=path)

    remaining_run_ceiling = RUN_CEILING_UNITS - run_ceiling_used
    remaining_daily_budget = DAILY_BUDGET_UNITS - quota_ledger.compute_known_cost_usage(
        entries, now - timedelta(hours=24), now
    )
    last_invocation = quota_ledger.most_recent_invocation_timestamp(entries, script)
    cooldown_ok = last_invocation is None or (now - last_invocation) >= COOLDOWN

    if remaining_run_ceiling <= 0:
        binding, decision = "run_ceiling", quota_ledger.DENIED
    elif remaining_daily_budget <= 0:
        binding, decision = "daily_budget", quota_ledger.DENIED
    elif not cooldown_ok:
        binding, decision = "cooldown", quota_ledger.DENIED
    else:
        binding, decision = None, quota_ledger.ALLOWED

    return {
        "remaining_run_ceiling_before_call": remaining_run_ceiling,
        "remaining_daily_budget_before_call": remaining_daily_budget,
        "cooldown_ok": cooldown_ok,
        "binding": binding,
        "decision": decision,
    }


# ---------------------------------------------------------
# CHANNEL
# ---------------------------------------------------------

def get_channel(youtube, collection_id=None, run_ceiling_used=0, path=quota_ledger.LEDGER_PATH):
    pre_call_check = _evaluate_known_cost_pre_call_check(
        run_ceiling_used, script="channel_snapshot.py", path=path
    )

    call_id = quota_ledger.write_pre_call_event(
        script="channel_snapshot.py",
        operation="channels.list",
        collection_id=collection_id,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check=pre_call_check,
        path=path,
    )

    if pre_call_check["decision"] == quota_ledger.DENIED:
        # Contract Sec 7.3 / Sec 10: propagate uncaught, no snapshot
        # produced -- this must not be caught and degraded.
        raise QuotaDeniedError(
            "channels.list denied by quota governance "
            f"(binding={pre_call_check['binding']!r})"
        )

    try:
        response = youtube.channels().list(
            part="snippet,statistics,contentDetails,brandingSettings",
            mine=True,
        ).execute()
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

    items = response.get("items", [])

    if not items:
        raise RuntimeError("No YouTube channel was found for the authenticated account.")

    return items[0]


# ---------------------------------------------------------
# SNAPSHOT
# ---------------------------------------------------------

def build_snapshot(channel, collection_id=None):
    snippet = channel.get("snippet", {})
    statistics = channel.get("statistics", {})
    content_details = channel.get("contentDetails", {})
    branding = channel.get("brandingSettings", {})

    return {
        "schema_version": "1.0",
        "snapshot_type": "youtube_channel",
        "snapshot_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "youtube_data_api",
        "api_version": "v3",

        # Provenance (collection linkage pass). None when this builder
        # runs standalone, outside collector.py -- collector.py is the
        # only thing that sets NIK_COLLECTION_ID before invoking it.
        "collection_id": collection_id,

        "channel_id": channel.get("id"),

        # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §7). A single,
        # non-paginated lookup: pagination_completed is None (not
        # applicable) rather than True, so it can't be misread as
        # "pagination was attempted and finished." errors/warnings stay
        # empty under the current architecture, since a failed API call
        # raises and prevents a snapshot from being written at all — see
        # the schema doc's Implementation Note.
        "retrieval_metadata": {
            "retrieved_resources": ["youtube#channel"],
            "pagination_completed": None,
            "errors": [],
            "warnings": [],
        },

        "channel": {
            "channel_id": channel.get("id"),

            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "custom_url": snippet.get("customUrl"),

            "published_at": snippet.get("publishedAt"),
            "country": snippet.get("country"),

            "statistics": {
                "view_count": int(statistics.get("viewCount", 0)),
                "subscriber_count": int(
                    statistics.get("subscriberCount", 0)
                ),
                "video_count": int(
                    statistics.get("videoCount", 0)
                ),
                "hidden_subscriber_count": statistics.get(
                    "hiddenSubscriberCount",
                    False,
                ),
            },

            "uploads_playlist_id": (
                content_details
                .get("relatedPlaylists", {})
                .get("uploads")
            ),

            "branding": branding,
        },

        # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §8). The reshaped
        # "channel" block above already existed and is left exactly as
        # it was — this preserves the untouched API resource alongside
        # it, so fields it doesn't carry forward (etag, full thumbnail
        # set, localized, other relatedPlaylists) aren't silently lost.
        "evidence": {
            "raw_response": channel,
        },
    }


# ---------------------------------------------------------
# SAVE
# ---------------------------------------------------------

def save_snapshot(snapshot):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )

    output_path = DATA_DIR / f"channel_{timestamp}.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            snapshot,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return output_path


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    print("===== NIK YOUTUBE CHANNEL SNAPSHOT =====")

    collection_id = os.environ.get("NIK_COLLECTION_ID")

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    channel = get_channel(youtube, collection_id=collection_id)

    snapshot = build_snapshot(channel, collection_id=collection_id)

    output_path = save_snapshot(snapshot)

    channel_data = snapshot["channel"]
    statistics = channel_data["statistics"]

    print()
    print("SNAPSHOT: SUCCESS")
    print(f"CHANNEL ID: {channel_data['channel_id']}")
    print(f"CHANNEL NAME: {channel_data['title']}")
    print(f"SUBSCRIBERS: {statistics['subscriber_count']}")
    print(f"VIDEOS: {statistics['video_count']}")
    print(f"VIEWS: {statistics['view_count']}")
    print()
    print(f"OUTPUT:")
    print(output_path)
    print()
    print("========================================")


if __name__ == "__main__":
    main()