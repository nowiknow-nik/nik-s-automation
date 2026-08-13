from pathlib import Path
import sys
import json
from datetime import datetime, timezone, timedelta

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import get_credentials
import quota_ledger


CHANNEL_ID = "UCn4OmZFMasYBkmCx6Q2oUBQ"

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
OUTPUT_FILE = LOG_DIR / "youtube_capability_discovery.json"


# ---------------------------------------------------------
# QUOTA GOVERNANCE (Stage B2.2d)
# ---------------------------------------------------------

# NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md Sec 5.1, Sec 5.3, Sec 8
# policy values. quota_ledger.py supplies usage facts only, not policy
# -- "this module does not decide whether to allow or deny a call" is
# its own module docstring's wording -- so comparing those facts
# against these ceilings belongs here, in the calling script, exactly
# as in channel_snapshot.py/analytics_snapshot.py. Local to this file
# for now -- see the B2.2d plan Sec 5.7: this makes
# _evaluate_known_cost_pre_call_check's logic a second copy and
# QuotaDeniedError a third; centralizing was deliberately deferred to
# a dedicated future stage rather than folded into this one.
RUN_CEILING_UNITS = 50
DAILY_BUDGET_UNITS = 1000
COOLDOWN = timedelta(minutes=5)
SEARCH_ALLOCATION_PER_24H = 100


class QuotaDeniedError(Exception):
    """
    A pre-call check denied this API call (Contract Sec 6). Per Sec
    7.3 / Sec 10 this must propagate uncaught so the script exits
    without producing output -- it must never be caught and degraded
    to a partial result.
    """


def _compute_invocation_cooldown_ok(path, now):
    """
    Whether Contract Sec 5.3's 5-minute cooldown is satisfied for this
    script, as of `now`. Reads the ledger once.

    FLAGGED DESIGN DECISION (B2.2d plan Sec 5.1, approved): this is
    called exactly once by main(), before any of this invocation's own
    four calls are made, and the single result is reused across all
    four pre-call checks below -- it is deliberately NOT recomputed
    per call the way channel_snapshot.py/analytics_snapshot.py derive
    cooldown_ok fresh inside their own (single) pre-call check, because
    those two scripts only ever make one governed call per invocation.
    This script makes four, sequentially, in one process. Deriving
    cooldown_ok fresh per call would make call 2's check see call 1's
    own pre-call event -- written moments earlier in this same
    process -- and spuriously deny itself on cooldown grounds, every
    run. Sec 5.3 itself is framed as spacing between separate
    invocations of a script, not between one invocation's own internal
    sequence of calls, which is what makes computing it once, up
    front, and reusing it the correct reading rather than a shortcut.
    """
    entries = quota_ledger.read_entries(path=path)
    last_invocation = quota_ledger.most_recent_invocation_timestamp(
        entries, "youtube_discovery.py"
    )
    return last_invocation is None or (now - last_invocation) >= COOLDOWN


def _evaluate_known_cost_pre_call_check(
    run_ceiling_used, cooldown_ok, path=quota_ledger.LEDGER_PATH, now=None
):
    # Builds and evaluates the v1.2 pre_call_check dict (Ledger Schema
    # Sec 6.2) for a known-cost, shared-pool operation -- channels.list,
    # playlists.list, playlistItems.list. Checks the run ceiling, then
    # the daily budget, then the cooldown -- Contract Sec 6's own
    # (a)/(b)/(c) order for this cost model, same as
    # channel_snapshot.py.
    #
    # run_ceiling_used is process-local (Contract Sec 5.1), same as
    # channel_snapshot.py/analytics_snapshot.py's process-local
    # counters -- but unlike those two, this file actively threads and
    # increments a single running count across all four of its own
    # calls (see main()), since this is the first script making more
    # than one governed call per invocation.
    #
    # cooldown_ok is NOT derived here from the ledger -- it is computed
    # once by main() (see _compute_invocation_cooldown_ok's docstring)
    # and passed in as a plain value. There is deliberately no `script`
    # parameter on this function: nothing in its body needs it, since
    # cooldown is supplied rather than looked up, and
    # compute_known_cost_usage() is intentionally not script-scoped
    # (Contract Sec 5.2's budget is shared across every known-cost,
    # shared-pool caller, not per-script).
    #
    # entries/now are still resolved fresh on every call, unlike
    # cooldown_ok -- the daily budget is supposed to accumulate across
    # this invocation's own prior calls, which requires seeing each
    # prior call's own just-written pre-call event. Freezing this
    # alongside cooldown_ok would silently undercount it.
    now = now or quota_ledger.utc_now()
    entries = quota_ledger.read_entries(path=path)

    remaining_run_ceiling = RUN_CEILING_UNITS - run_ceiling_used
    remaining_daily_budget = DAILY_BUDGET_UNITS - quota_ledger.compute_known_cost_usage(
        entries, now - timedelta(hours=24), now
    )

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


def _evaluate_search_pre_call_check(
    run_ceiling_used, cooldown_ok, path=quota_ledger.LEDGER_PATH, now=None
):
    # Builds and evaluates the v1.2 pre_call_check dict (Ledger Schema
    # Sec 6.2) for search.list specifically -- known-cost, but
    # deliberately NOT part of the shared daily-budget pool (Contract
    # Sec 4.1, Sec 4.5, Sec 6). Checks the run ceiling, then
    # search.list's own rolling-24h allocation (Contract Sec 8), then
    # the cooldown -- Sec 6's explicit (a)/(b)/(c) order for this
    # operation. Sec 5.2's daily budget must never be checked here
    # (Sec 6: "must never be checked against the daily budget... doing
    # so would be exactly the silent conflation Sec 2 prohibits") --
    # there is no remaining_daily_budget_before_call field on this
    # shape at all (Ledger Schema Sec 6.2).
    #
    # cooldown_ok is the same invocation-level value used by
    # _evaluate_known_cost_pre_call_check above, for the same reason.
    now = now or quota_ledger.utc_now()
    entries = quota_ledger.read_entries(path=path)

    remaining_run_ceiling = RUN_CEILING_UNITS - run_ceiling_used
    remaining_search_allocation = SEARCH_ALLOCATION_PER_24H - quota_ledger.compute_search_usage(
        entries, now - timedelta(hours=24), now
    )

    if remaining_run_ceiling <= 0:
        binding, decision = "run_ceiling", quota_ledger.DENIED
    elif remaining_search_allocation <= 0:
        binding, decision = "search_allocation", quota_ledger.DENIED
    elif not cooldown_ok:
        binding, decision = "cooldown", quota_ledger.DENIED
    else:
        binding, decision = None, quota_ledger.ALLOWED

    return {
        "remaining_run_ceiling_before_call": remaining_run_ceiling,
        "remaining_search_allocation_before_call": remaining_search_allocation,
        "cooldown_ok": cooldown_ok,
        "binding": binding,
        "decision": decision,
    }


# ---------------------------------------------------------
# CHANNEL
# ---------------------------------------------------------

def discover_channel(
    youtube, run_ceiling_used, cooldown_ok, collection_id=None, path=quota_ledger.LEDGER_PATH
):
    pre_call_check = _evaluate_known_cost_pre_call_check(
        run_ceiling_used, cooldown_ok, path=path
    )

    call_id = quota_ledger.write_pre_call_event(
        script="youtube_discovery.py",
        operation="channels.list",
        collection_id=collection_id,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check=pre_call_check,
        path=path,
    )

    if pre_call_check["decision"] == quota_ledger.DENIED:
        # Contract Sec 7.3 / Sec 10: propagate uncaught, no output
        # produced -- this must not be caught and degraded.
        raise QuotaDeniedError(
            "channels.list denied by quota governance "
            f"(binding={pre_call_check['binding']!r})"
        )

    # Authorized: this call now counts against the run ceiling even if
    # .execute() below subsequently fails -- an authorized call must
    # not leave the invocation's safety budget looking unconsumed just
    # because the API call itself then failed.
    run_ceiling_used += 1

    try:
        response = youtube.channels().list(
            part="snippet,contentDetails,statistics,brandingSettings",
            id=CHANNEL_ID,
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

    return response, run_ceiling_used


# ---------------------------------------------------------
# PLAYLISTS
# ---------------------------------------------------------

def discover_playlists(
    youtube, run_ceiling_used, cooldown_ok, collection_id=None, path=quota_ledger.LEDGER_PATH
):
    pre_call_check = _evaluate_known_cost_pre_call_check(
        run_ceiling_used, cooldown_ok, path=path
    )

    call_id = quota_ledger.write_pre_call_event(
        script="youtube_discovery.py",
        operation="playlists.list",
        collection_id=collection_id,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check=pre_call_check,
        path=path,
    )

    if pre_call_check["decision"] == quota_ledger.DENIED:
        raise QuotaDeniedError(
            "playlists.list denied by quota governance "
            f"(binding={pre_call_check['binding']!r})"
        )

    run_ceiling_used += 1

    try:
        response = youtube.playlists().list(
            part="snippet,contentDetails,status",
            channelId=CHANNEL_ID,
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

    return response, run_ceiling_used


# ---------------------------------------------------------
# UPLOADS PLAYLIST ITEMS
# ---------------------------------------------------------

def discover_playlist_items(
    youtube, playlist_id, run_ceiling_used, cooldown_ok, collection_id=None,
    path=quota_ledger.LEDGER_PATH,
):
    pre_call_check = _evaluate_known_cost_pre_call_check(
        run_ceiling_used, cooldown_ok, path=path
    )

    call_id = quota_ledger.write_pre_call_event(
        script="youtube_discovery.py",
        operation="playlistItems.list",
        collection_id=collection_id,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check=pre_call_check,
        path=path,
    )

    if pre_call_check["decision"] == quota_ledger.DENIED:
        raise QuotaDeniedError(
            "playlistItems.list denied by quota governance "
            f"(binding={pre_call_check['binding']!r})"
        )

    run_ceiling_used += 1

    try:
        response = youtube.playlistItems().list(
            part="snippet,contentDetails,status",
            playlistId=playlist_id,
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

    return response, run_ceiling_used


# ---------------------------------------------------------
# SEARCH CAPABILITY
# ---------------------------------------------------------

def discover_search_results(
    youtube, run_ceiling_used, cooldown_ok, collection_id=None, path=quota_ledger.LEDGER_PATH
):
    pre_call_check = _evaluate_search_pre_call_check(
        run_ceiling_used, cooldown_ok, path=path
    )

    call_id = quota_ledger.write_pre_call_event(
        script="youtube_discovery.py",
        operation="search.list",
        collection_id=collection_id,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check=pre_call_check,
        path=path,
    )

    if pre_call_check["decision"] == quota_ledger.DENIED:
        raise QuotaDeniedError(
            "search.list denied by quota governance "
            f"(binding={pre_call_check['binding']!r})"
        )

    run_ceiling_used += 1

    try:
        response = youtube.search().list(
            part="snippet",
            channelId=CHANNEL_ID,
            type="video",
            maxResults=10,
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

    return response, run_ceiling_used


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    print("===== NIK YOUTUBE CAPABILITY DISCOVERY =====")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    # Quota governance (Stage B2.2d). path/now/cooldown_ok are each
    # resolved once, here, before any of this invocation's own four
    # calls -- see _compute_invocation_cooldown_ok's docstring for why
    # cooldown specifically must not be re-derived per call.
    path = quota_ledger.LEDGER_PATH
    now = quota_ledger.utc_now()
    cooldown_ok = _compute_invocation_cooldown_ok(path, now)

    # run_ceiling_used is this invocation's own process-local count of
    # API calls already authorized (pre-call check passed), not merely
    # of calls that went on to succeed -- see discover_channel()'s own
    # comment. Threaded through and incremented across all four calls
    # below, including search.list (Contract Sec 5.1, Sec 6).
    run_ceiling_used = 0

    # --------------------------------------------------
    # CHANNEL
    # --------------------------------------------------

    channel_response, run_ceiling_used = discover_channel(
        youtube, run_ceiling_used, cooldown_ok, path=path
    )

    channel = channel_response.get("items", [])

    # --------------------------------------------------
    # PLAYLISTS
    # --------------------------------------------------

    playlist_response, run_ceiling_used = discover_playlists(
        youtube, run_ceiling_used, cooldown_ok, path=path
    )

    playlists = playlist_response.get("items", [])

    # --------------------------------------------------
    # UPLOADS PLAYLIST
    # --------------------------------------------------

    uploads_playlist_id = None

    if channel:
        uploads_playlist_id = (
            channel[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )

    videos = []

    if uploads_playlist_id:
        playlist_items_response, run_ceiling_used = discover_playlist_items(
            youtube, uploads_playlist_id, run_ceiling_used, cooldown_ok, path=path
        )

        videos = playlist_items_response.get("items", [])

    # --------------------------------------------------
    # SEARCH CAPABILITY
    # --------------------------------------------------

    search_response, run_ceiling_used = discover_search_results(
        youtube, run_ceiling_used, cooldown_ok, path=path
    )

    search_results = search_response.get("items", [])

    # --------------------------------------------------
    # RESULT
    # --------------------------------------------------

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel_id": CHANNEL_ID,

        "capabilities_tested": {
            "channel": True,
            "playlists": True,
            "uploads_playlist": bool(uploads_playlist_id),
            "videos": True,
            "search": True,
        },

        "channel": channel,
        "playlists": playlists,
        "uploads_playlist_id": uploads_playlist_id,
        "videos": videos,
        "search_results": search_results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print()
    print("DISCOVERY: SUCCESS")
    print("CHANNEL FOUND:", bool(channel))
    print("PLAYLISTS:", len(playlists))
    print("VIDEOS FOUND:", len(videos))
    print("SEARCH RESULTS:", len(search_results))
    print()
    print("OUTPUT:")
    print(OUTPUT_FILE)
    print()
    print("============================================")


if __name__ == "__main__":
    main()