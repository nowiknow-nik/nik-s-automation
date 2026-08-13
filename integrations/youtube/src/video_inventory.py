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
OUTPUT_DIR = BASE_DIR / "data" / "snapshots" / "videos"

CHANNEL_SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"


# ---------------------------------------------------------
# QUOTA GOVERNANCE (Stage B2.2e)
# ---------------------------------------------------------

# NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md Sec 5.1, Sec 5.3, Sec 7
# policy values, evaluated here rather than in quota_ledger.py -- same
# division of responsibility as channel_snapshot.py/youtube_discovery.py
# ("this module does not decide whether to allow or deny a call" is
# quota_ledger.py's own module docstring). Local to this file for now
# -- per the B2.2e plan Sec 5.7 and the B2.2e approval's decision 10,
# cross-file centralization is deliberately deferred to a dedicated
# future stage, not folded into this one. This makes QuotaDeniedError
# a fourth copy and RUN_CEILING_UNITS/DAILY_BUDGET_UNITS/COOLDOWN a
# third copy each -- B2.2d already flagged B2.2e as the natural point
# to reconsider centralization; that reconsideration is still deferred.
RUN_CEILING_UNITS = 50
DAILY_BUDGET_UNITS = 1000
COOLDOWN = timedelta(minutes=5)

# Contract Sec 7.1/7.2: 20 pages max for playlistItems.list pagination,
# and 20 batches max for videos.list batching. Sec 7.2 is explicit that
# the batch ceiling is *derived* from 7.1, not an independently
# configured number of its own ("this contract does not propose a
# second, independent batch ceiling -- doing so risks the two numbers
# drifting out of sync"), so there is deliberately only one constant
# here, reused by both loops below via their own separate, live
# process-local counters (fetch_video_inventory()'s page_count and
# enrich_video_statistics()'s batch_count) -- not a second constant.
PAGINATION_CEILING = 20


class QuotaDeniedError(Exception):
    """
    A pre-call check denied this API call (Contract Sec 6/Sec 7). Per
    Sec 7.3 / Sec 10 this must propagate uncaught so the script exits
    without producing a snapshot -- it must never be caught and
    degraded to a partial snapshot built from whatever pages or
    batches were already fetched.
    """


def _compute_invocation_cooldown_ok(path, now):
    """
    Whether Contract Sec 5.3's 5-minute cooldown is satisfied for this
    script, as of `now`. Reads the ledger once.

    Same B2.2d resolution, approved unchanged for B2.2e (decision 4):
    called exactly once by main(), before either of this invocation's
    two loops makes any call, and the single result is reused across
    every pre-call check below -- deliberately NOT recomputed per call.
    This script can make many sequential calls across two loops in one
    process; deriving cooldown_ok fresh per call would make call 2
    onward see call 1's own pre-call event -- written moments earlier
    in this same process -- and spuriously deny itself on cooldown
    grounds, every run. Sec 5.3 itself is framed as spacing between
    separate invocations of a script, not between one invocation's own
    internal sequence of calls, which is what makes computing it once,
    up front, and reusing it the correct reading rather than a
    shortcut.
    """
    entries = quota_ledger.read_entries(path=path)
    last_invocation = quota_ledger.most_recent_invocation_timestamp(
        entries, "video_inventory.py"
    )
    return last_invocation is None or (now - last_invocation) >= COOLDOWN


def _evaluate_known_cost_pre_call_check(
    run_ceiling_used, pagination_used, cooldown_ok,
    path=quota_ledger.LEDGER_PATH, now=None,
):
    # Builds and evaluates the v1.2 pre_call_check dict (Ledger Schema
    # Sec 6.2, amended Stage B2.2e to add
    # remaining_pagination_ceiling_before_call) for this file's two
    # known-cost, shared-pool, paginated/batched operations --
    # playlistItems.list and videos.list. Both call sites in this file
    # are subject to Contract Sec 7's pagination/batch ceiling, so this
    # function always returns a real integer for
    # remaining_pagination_ceiling_before_call, never null -- the
    # schema's null case is for known-cost operations this ceiling does
    # not apply to (channels.list, playlists.list), which this file
    # never calls.
    #
    # Check order (B2.2e approval, decision 2): run ceiling, then the
    # pagination/batch ceiling, then the daily budget, then the
    # cooldown. Contract Sec 6's own (a)/(b)/(c) text predates Sec 7 and
    # does not say where pagination/batch fits; this order is this
    # stage's resolution, not yet reflected back into the Contract's
    # own text (see the Ledger Schema Sec 11 note this stage added).
    #
    # pagination_used is the caller's own live, process-local page or
    # batch count -- NOT run_ceiling_used, and not shared between the
    # two loops (decision 3: enrich_video_statistics() has its own
    # counter, fetch_video_inventory() has its own; neither resets or
    # continues the other). A page denial and a batch denial are both
    # recorded with binding "pagination_ceiling" -- decision 3
    # deliberately does not add a separate "batch_ceiling" value, since
    # the "operation" field (playlistItems.list vs videos.list) already
    # distinguishes which loop actually denied.
    #
    # run_ceiling_used, by contrast, IS shared across both loops
    # (decision 5) -- it is threaded through by the caller (main()),
    # not tracked locally here.
    #
    # cooldown_ok is NOT derived here from the ledger -- it is computed
    # once by main() (see _compute_invocation_cooldown_ok's docstring)
    # and passed in as a plain value, same as youtube_discovery.py.
    #
    # entries/now are still resolved fresh on every call, unlike
    # cooldown_ok -- the daily budget is supposed to accumulate across
    # this invocation's own prior calls, which requires seeing each
    # prior call's own just-written pre-call event. Freezing this
    # alongside cooldown_ok would silently undercount it.
    now = now or quota_ledger.utc_now()
    entries = quota_ledger.read_entries(path=path)

    remaining_run_ceiling = RUN_CEILING_UNITS - run_ceiling_used
    remaining_pagination_ceiling = PAGINATION_CEILING - pagination_used
    remaining_daily_budget = DAILY_BUDGET_UNITS - quota_ledger.compute_known_cost_usage(
        entries, now - timedelta(hours=24), now
    )

    if remaining_run_ceiling <= 0:
        binding, decision = "run_ceiling", quota_ledger.DENIED
    elif remaining_pagination_ceiling <= 0:
        binding, decision = "pagination_ceiling", quota_ledger.DENIED
    elif remaining_daily_budget <= 0:
        binding, decision = "daily_budget", quota_ledger.DENIED
    elif not cooldown_ok:
        binding, decision = "cooldown", quota_ledger.DENIED
    else:
        binding, decision = None, quota_ledger.ALLOWED

    return {
        "remaining_run_ceiling_before_call": remaining_run_ceiling,
        "remaining_pagination_ceiling_before_call": remaining_pagination_ceiling,
        "remaining_daily_budget_before_call": remaining_daily_budget,
        "cooldown_ok": cooldown_ok,
        "binding": binding,
        "decision": decision,
    }


def get_latest_channel_snapshot():
    files = sorted(
        CHANNEL_SNAPSHOT_DIR.glob("channel_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            "No channel snapshot found. Run channel_snapshot.py first."
        )

    with files[0].open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_video_inventory(
    youtube, uploads_playlist_id, run_ceiling_used, cooldown_ok,
    collection_id=None, path=quota_ledger.LEDGER_PATH,
):
    videos = []
    next_page_token = None
    page_count = 0

    while True:
        pre_call_check = _evaluate_known_cost_pre_call_check(
            run_ceiling_used, page_count, cooldown_ok, path=path
        )

        call_id = quota_ledger.write_pre_call_event(
            script="video_inventory.py",
            operation="playlistItems.list",
            collection_id=collection_id,
            cost_model=quota_ledger.KNOWN_COST_MODEL,
            estimated_cost_units=1,
            pre_call_check=pre_call_check,
            path=path,
        )

        if pre_call_check["decision"] == quota_ledger.DENIED:
            # Contract Sec 7.3 / Sec 10: propagate uncaught, no
            # snapshot produced -- must not be caught and degraded to
            # a partial result built from whatever pages were already
            # fetched.
            raise QuotaDeniedError(
                "playlistItems.list denied by quota governance "
                f"(binding={pre_call_check['binding']!r})"
            )

        # Authorized: counts against both ceilings now even if
        # .execute() below subsequently fails -- an authorized call
        # must not leave either safety counter looking unconsumed just
        # because the API call itself then failed.
        run_ceiling_used += 1
        page_count += 1

        try:
            response = youtube.playlistItems().list(
                part="snippet,contentDetails,status",
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token,
            ).execute()
        except Exception as exc:
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

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            status = item.get("status", {})

            videos.append(
                {
                    "playlist_item_id": item.get("id"),
                    "video_id": content_details.get("videoId"),
                    "title": snippet.get("title"),
                    "description": snippet.get("description"),
                    "published_at": snippet.get("publishedAt"),
                    "channel_id": snippet.get("channelId"),
                    "channel_title": snippet.get("channelTitle"),
                    "position": snippet.get("position"),
                    "resource_id": snippet.get("resourceId"),
                    "status": status,
                }
            )

        next_page_token = response.get("nextPageToken")

        if not next_page_token:
            break

    return videos, run_ceiling_used


def enrich_video_statistics(
    youtube, videos, run_ceiling_used, cooldown_ok,
    collection_id=None, path=quota_ledger.LEDGER_PATH,
):
    if not videos:
        return videos, run_ceiling_used

    video_ids = [
        video["video_id"]
        for video in videos
        if video.get("video_id")
    ]

    batch_count = 0

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]

        pre_call_check = _evaluate_known_cost_pre_call_check(
            run_ceiling_used, batch_count, cooldown_ok, path=path
        )

        call_id = quota_ledger.write_pre_call_event(
            script="video_inventory.py",
            operation="videos.list",
            collection_id=collection_id,
            cost_model=quota_ledger.KNOWN_COST_MODEL,
            estimated_cost_units=1,
            pre_call_check=pre_call_check,
            path=path,
        )

        if pre_call_check["decision"] == quota_ledger.DENIED:
            raise QuotaDeniedError(
                "videos.list denied by quota governance "
                f"(binding={pre_call_check['binding']!r})"
            )

        run_ceiling_used += 1
        batch_count += 1

        try:
            response = youtube.videos().list(
                part="snippet,contentDetails,statistics,status",
                id=",".join(batch),
                maxResults=50,
            ).execute()
        except Exception as exc:
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

        by_id = {
            item["id"]: item
            for item in response.get("items", [])
        }

        for video in videos:
            video_id = video.get("video_id")

            if video_id in by_id:
                item = by_id[video_id]

                # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §8): store
                # the untouched videos().list() item rather than a
                # hand-picked subset, so kind/etag/id travel with it too.
                # Strictly more complete than the previous reshaped dict;
                # nothing that read the old four keys is removed.
                video["video_details"] = item

    return videos, run_ceiling_used


def main():
    print("===== NIK YOUTUBE VIDEO INVENTORY =====")

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    # Quota governance (Stage B2.2e). path/now/cooldown_ok are each
    # resolved once, here, before either of this invocation's two
    # loops makes any call -- see _compute_invocation_cooldown_ok's
    # docstring for why cooldown specifically must not be re-derived
    # per call. collection_id is likewise read once here (decision 6)
    # and reused for both governed calls and the final snapshot, rather
    # than re-reading the environment variable at snapshot-build time.
    path = quota_ledger.LEDGER_PATH
    now = quota_ledger.utc_now()
    cooldown_ok = _compute_invocation_cooldown_ok(path, now)
    collection_id = os.environ.get("NIK_COLLECTION_ID")

    # run_ceiling_used is this invocation's own process-local count of
    # API calls already authorized (pre-call check passed), not merely
    # of calls that went on to succeed -- see fetch_video_inventory()'s
    # own comment. Threaded through and incremented across BOTH loops
    # below (decision 5) -- it is not reset between them.
    run_ceiling_used = 0

    channel_snapshot = get_latest_channel_snapshot()

    channel = channel_snapshot["channel"]

    channel_id = channel["channel_id"]
    uploads_playlist_id = channel["uploads_playlist_id"]

    videos, run_ceiling_used = fetch_video_inventory(
        youtube,
        uploads_playlist_id,
        run_ceiling_used,
        cooldown_ok,
        collection_id=collection_id,
        path=path,
    )

    videos, run_ceiling_used = enrich_video_statistics(
        youtube,
        videos,
        run_ceiling_used,
        cooldown_ok,
        collection_id=collection_id,
        path=path,
    )

    snapshot = {
        "schema_version": "1.0",
        "snapshot_type": "youtube_video_inventory",
        "snapshot_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source": "youtube_data_api",
        "api_version": "v3",

        # Provenance (collection linkage pass). None when this builder
        # runs standalone, outside collector.py. Read once above
        # (Stage B2.2e decision 6), not re-read here.
        "collection_id": collection_id,

        "channel_id": channel_id,

        # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §7). Reaching this
        # point means fetch_video_inventory()'s pagination loop and
        # enrich_video_statistics()'s batch loop both actually ran to
        # completion -- a ceiling denial or any other quota-governance
        # denial (Stage B2.2e) raises QuotaDeniedError before this
        # point is ever reached, same as any other uncaught exception,
        # so True remains accurate for any snapshot that gets this far,
        # not an assumption.
        "retrieval_metadata": {
            "retrieved_resources": ["youtube#playlistItem", "youtube#video"],
            "pagination_completed": True,
            "errors": [],
            "warnings": [],
        },

        "uploads_playlist_id": uploads_playlist_id,

        "video_count": len(videos),

        "videos": videos,
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
        / f"videos_{timestamp}.json"
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
    print("INVENTORY: SUCCESS")
    print("CHANNEL ID:", channel_id)
    print("UPLOADS PLAYLIST:", uploads_playlist_id)
    print("VIDEOS FOUND:", len(videos))
    print()
    print("OUTPUT:")
    print(output_file.resolve())
    print()
    print("========================================")


if __name__ == "__main__":
    main()