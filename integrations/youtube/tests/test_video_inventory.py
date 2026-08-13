from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import quota_ledger
import video_inventory
from video_inventory import QuotaDeniedError


# ---------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------

SAMPLE_CHANNEL_SNAPSHOT = {
    "channel": {
        "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
        "uploads_playlist_id": "UUsample000000000000000",
    }
}

SAMPLE_PLAYLIST_ITEMS_PAGE = {
    "items": [
        {
            "id": "playlistitem001",
            "snippet": {
                "title": "Sample Video",
                "description": "A sample video.",
                "publishedAt": "2026-08-01T00:00:00Z",
                "channelId": "UCn4OmZFMasYBkmCx6Q2oUBQ",
                "channelTitle": "Sample Channel",
                "position": 0,
                "resourceId": {"kind": "youtube#video", "videoId": "vid00000001"},
            },
            "contentDetails": {"videoId": "vid00000001"},
            "status": {"privacyStatus": "public"},
        }
    ],
}

SAMPLE_VIDEOS_LIST_RESPONSE = {
    "items": [
        {
            "id": "vid00000001",
            "snippet": {"title": "Sample Video"},
            "contentDetails": {"duration": "PT5M"},
            "statistics": {"viewCount": "100"},
            "status": {"privacyStatus": "public"},
        }
    ]
}


def _playlist_item(video_id):
    return {
        "id": f"playlistitem-{video_id}",
        "snippet": {
            "title": f"Title {video_id}",
            "description": "desc",
            "publishedAt": "2026-08-01T00:00:00Z",
            "channelId": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "channelTitle": "Sample Channel",
            "position": 0,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        },
        "contentDetails": {"videoId": video_id},
        "status": {"privacyStatus": "public"},
    }


def _video_stub(video_id):
    return {"video_id": video_id}


def _fake_youtube(playlist_items=None, videos=None):
    """
    A minimal stand-in for the googleapiclient youtube resource, deep
    enough to support youtube.playlistItems().list(...).execute() and
    youtube.videos().list(...).execute(). Each of playlist_items/videos
    is either: a dict (used as .execute()'s fixed return value), an
    Exception instance (used as .execute()'s side_effect to always
    raise), or a list (used as .execute()'s side_effect sequence, one
    entry consumed per call -- for multi-page/multi-batch scenarios,
    including boundary tests where the list is deliberately shorter
    than the number of calls that *would* happen if a ceiling denial
    failed to stop the loop, so a bug shows up as StopIteration rather
    than silently passing). None leaves that resource unconfigured --
    safe for tests that never reach that call.
    """
    youtube = MagicMock()
    for attr, value in (
        ("playlistItems", playlist_items),
        ("videos", videos),
    ):
        execute = getattr(youtube, attr).return_value.list.return_value.execute
        if isinstance(value, Exception):
            execute.side_effect = value
        elif isinstance(value, list):
            execute.side_effect = value
        elif value is not None:
            execute.return_value = value
    return youtube


def _seed_known_cost_usage(path, estimated_cost_units, script="other_script.py"):
    """
    Appends one allowed known-cost pre_call_check event carrying an
    arbitrary estimated_cost_units, so compute_known_cost_usage() can
    be pushed to a chosen total without writing many individual
    entries. Defaults to a different script than this file's own, so
    it never contaminates a most_recent_invocation_timestamp lookup
    scoped to "video_inventory.py" -- mirrors test_youtube_discovery.py's
    identically-named helper.
    """
    quota_ledger.write_pre_call_event(
        script=script,
        operation="playlistItems.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=estimated_cost_units,
        pre_call_check={
            "remaining_run_ceiling_before_call": 1,
            "remaining_pagination_ceiling_before_call": 1,
            "remaining_daily_budget_before_call": 1,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )


def _patch_main_environment(monkeypatch, tmp_path, youtube, channel_snapshot=None):
    """
    Redirects every external touchpoint main() has to tmp_path / the
    given fake youtube resource: the ledger, the output directory,
    credentials, the googleapiclient build() call, and the latest
    channel snapshot lookup. get_latest_channel_snapshot() itself is
    mocked directly rather than seeding a real file on disk -- it is
    unmodified by B2.2e (no API call, no ledger interaction) and is
    outside this stage's scope. Returns (ledger_path, output_dir).
    """
    ledger_path = tmp_path / "quota_ledger.jsonl"
    output_dir = tmp_path / "snapshots" / "videos"

    monkeypatch.setattr(quota_ledger, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr(video_inventory, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(video_inventory, "get_credentials", lambda: MagicMock())
    monkeypatch.setattr(video_inventory, "build", lambda *a, **kw: youtube)
    monkeypatch.setattr(
        video_inventory,
        "get_latest_channel_snapshot",
        lambda: channel_snapshot or SAMPLE_CHANNEL_SNAPSHOT,
    )

    return ledger_path, output_dir


# ---------------------------------------------------------------------
# _compute_invocation_cooldown_ok
# ---------------------------------------------------------------------

def test_cooldown_ok_when_no_prior_invocation(tmp_path):
    path = tmp_path / "ledger.jsonl"

    assert video_inventory._compute_invocation_cooldown_ok(path, quota_ledger.utc_now()) is True


def test_cooldown_not_ok_when_last_invocation_too_recent(tmp_path):
    path = tmp_path / "ledger.jsonl"
    quota_ledger.write_pre_call_event(
        script="video_inventory.py",
        operation="playlistItems.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check={
            "remaining_run_ceiling_before_call": 49,
            "remaining_pagination_ceiling_before_call": 19,
            "remaining_daily_budget_before_call": 999,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )

    assert video_inventory._compute_invocation_cooldown_ok(path, quota_ledger.utc_now()) is False


def test_cooldown_ok_when_last_invocation_old_enough(tmp_path):
    path = tmp_path / "ledger.jsonl"
    old_time = datetime(2026, 8, 13, 6, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=old_time):
        quota_ledger.write_pre_call_event(
            script="video_inventory.py",
            operation="playlistItems.list",
            collection_id=None,
            cost_model=quota_ledger.KNOWN_COST_MODEL,
            estimated_cost_units=1,
            pre_call_check={
                "remaining_run_ceiling_before_call": 49,
                "remaining_pagination_ceiling_before_call": 19,
                "remaining_daily_budget_before_call": 999,
                "cooldown_ok": True,
                "binding": None,
                "decision": quota_ledger.ALLOWED,
            },
            path=path,
        )

    now = old_time + timedelta(hours=1)
    assert video_inventory._compute_invocation_cooldown_ok(path, now) is True


def test_cooldown_ignores_other_scripts(tmp_path):
    """
    A recent invocation of a *different* script must not hold this
    script's own cooldown down -- most_recent_invocation_timestamp()
    is script-scoped by design.
    """
    path = tmp_path / "ledger.jsonl"
    quota_ledger.write_pre_call_event(
        script="youtube_discovery.py",
        operation="channels.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check={
            "remaining_run_ceiling_before_call": 49,
            "remaining_daily_budget_before_call": 999,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )

    assert video_inventory._compute_invocation_cooldown_ok(path, quota_ledger.utc_now()) is True


# ---------------------------------------------------------------------
# _evaluate_known_cost_pre_call_check
# ---------------------------------------------------------------------

def test_known_cost_allowed_baseline(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, pagination_used=0, cooldown_ok=True, path=path
    )

    assert result == {
        "remaining_run_ceiling_before_call": 50,
        "remaining_pagination_ceiling_before_call": 20,
        "remaining_daily_budget_before_call": 1000,
        "cooldown_ok": True,
        "binding": None,
        "decision": "allowed",
    }


def test_known_cost_denied_run_ceiling(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=50, pagination_used=0, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"
    assert result["remaining_run_ceiling_before_call"] == 0


def test_known_cost_denied_pagination_ceiling(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, pagination_used=20, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "pagination_ceiling"
    assert result["remaining_pagination_ceiling_before_call"] == 0


def test_known_cost_denied_daily_budget(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(path, estimated_cost_units=1000)

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, pagination_used=0, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "daily_budget"
    assert result["remaining_daily_budget_before_call"] == 0


def test_known_cost_denied_cooldown(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, pagination_used=0, cooldown_ok=False, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "cooldown"
    assert result["cooldown_ok"] is False


def test_known_cost_run_ceiling_checked_before_pagination_ceiling(tmp_path):
    """B2.2e approval decision 2: run ceiling before the pagination/batch ceiling."""
    path = tmp_path / "ledger.jsonl"

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=50, pagination_used=20, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"


def test_known_cost_pagination_ceiling_checked_before_daily_budget(tmp_path):
    """B2.2e approval decision 2: pagination/batch ceiling before the daily budget."""
    path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(path, estimated_cost_units=1000)

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, pagination_used=20, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "pagination_ceiling"


def test_known_cost_daily_budget_checked_before_cooldown(tmp_path):
    """B2.2e approval decision 2: daily budget before cooldown."""
    path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(path, estimated_cost_units=1000)

    result = video_inventory._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, pagination_used=0, cooldown_ok=False, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "daily_budget"


# ---------------------------------------------------------------------
# fetch_video_inventory
# ---------------------------------------------------------------------

def test_fetch_video_inventory_single_page_success(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE)

    videos, run_ceiling_used = video_inventory.fetch_video_inventory(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert len(videos) == 1
    assert videos[0]["video_id"] == "vid00000001"
    assert run_ceiling_used == 1
    youtube.playlistItems.return_value.list.return_value.execute.assert_called_once()


def test_fetch_video_inventory_multi_page_success(tmp_path):
    path = tmp_path / "ledger.jsonl"
    page1 = {"items": [_playlist_item("vid00000001")], "nextPageToken": "token-page-2"}
    page2 = {"items": [_playlist_item("vid00000002")]}
    youtube = _fake_youtube(playlist_items=[page1, page2])

    videos, run_ceiling_used = video_inventory.fetch_video_inventory(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert [v["video_id"] for v in videos] == ["vid00000001", "vid00000002"]
    assert run_ceiling_used == 2
    assert youtube.playlistItems.return_value.list.return_value.execute.call_count == 2

    calls = youtube.playlistItems.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "token-page-2"


def test_fetch_video_inventory_denied_does_not_execute(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE)

    with pytest.raises(QuotaDeniedError):
        video_inventory.fetch_video_inventory(
            youtube, "UUsample000000000000000", run_ceiling_used=50, cooldown_ok=True, path=path
        )

    youtube.playlistItems.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=path)
    assert len(entries) == 1
    assert entries[0]["pre_call_check"]["decision"] == "denied"
    assert entries[0]["pre_call_check"]["binding"] == "run_ceiling"


def test_fetch_video_inventory_mid_loop_denial_stops_after_first_page(tmp_path):
    """
    A denial on page 2 (run ceiling exhausted by page 1's own call)
    must raise before page 2's .execute(), while page 1 already
    genuinely ran and succeeded.
    """
    path = tmp_path / "ledger.jsonl"
    page1 = {"items": [_playlist_item("vid00000001")], "nextPageToken": "token-page-2"}
    youtube = _fake_youtube(playlist_items=[page1])

    with pytest.raises(QuotaDeniedError):
        video_inventory.fetch_video_inventory(
            youtube, "UUsample000000000000000", run_ceiling_used=49, cooldown_ok=True, path=path
        )

    assert youtube.playlistItems.return_value.list.return_value.execute.call_count == 1

    entries = quota_ledger.read_entries(path=path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 2
    assert pre_call_events[0]["pre_call_check"]["decision"] == "allowed"
    assert pre_call_events[1]["pre_call_check"]["decision"] == "denied"


def test_fetch_video_inventory_page_20_allowed_all_pages_succeed(tmp_path):
    """Contract Sec 7.1: 20 pages is the ceiling itself, not a trigger -- exactly 20 pages must all be allowed and succeed."""
    path = tmp_path / "ledger.jsonl"
    pages = []
    for i in range(1, 21):
        page = {"items": [_playlist_item(f"vid{i:03d}")]}
        if i < 20:
            page["nextPageToken"] = f"token-{i}"
        pages.append(page)
    youtube = _fake_youtube(playlist_items=pages)

    videos, run_ceiling_used = video_inventory.fetch_video_inventory(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert len(videos) == 20
    assert run_ceiling_used == 20
    assert youtube.playlistItems.return_value.list.return_value.execute.call_count == 20

    entries = quota_ledger.read_entries(path=path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 20
    assert all(e["pre_call_check"]["decision"] == "allowed" for e in pre_call_events)
    assert pre_call_events[-1]["pre_call_check"]["remaining_pagination_ceiling_before_call"] == 1


def test_fetch_video_inventory_page_21_denied(tmp_path):
    """Contract Sec 7.1/7.3: the 21st page must be denied before .execute(), with binding pagination_ceiling."""
    path = tmp_path / "ledger.jsonl"
    pages = [
        {"items": [_playlist_item(f"vid{i:03d}")], "nextPageToken": f"token-{i}"}
        for i in range(1, 21)
    ]
    youtube = _fake_youtube(playlist_items=pages)

    with pytest.raises(QuotaDeniedError):
        video_inventory.fetch_video_inventory(
            youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
        )

    # Exactly 20 real calls happened; the 21st was denied before
    # reaching .execute() -- if the implementation had a bug and
    # actually tried a 21st .execute(), the mock's side_effect list
    # (length 20) would raise StopIteration instead, failing this test
    # loudly rather than silently passing.
    assert youtube.playlistItems.return_value.list.return_value.execute.call_count == 20

    entries = quota_ledger.read_entries(path=path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 21
    assert pre_call_events[-1]["pre_call_check"]["decision"] == "denied"
    assert pre_call_events[-1]["pre_call_check"]["binding"] == "pagination_ceiling"


def test_fetch_video_inventory_pre_call_write_failure_prevents_execute(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE)

    def _raise(*args, **kwargs):
        raise OSError("simulated pre-call ledger write failure")

    monkeypatch.setattr(video_inventory.quota_ledger, "write_pre_call_event", _raise)

    with pytest.raises(OSError):
        video_inventory.fetch_video_inventory(
            youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
        )

    youtube.playlistItems.return_value.list.return_value.execute.assert_not_called()


def test_fetch_video_inventory_success_writes_success_post_call_event(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE)

    video_inventory.fetch_video_inventory(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    post = next(e for e in entries if e["event_type"] == "post_call_result")

    assert len(entries) == 2
    assert post["call_id"] == pre["call_id"]
    assert post["outcome"] == "success"
    assert post["error"] is None


def test_fetch_video_inventory_api_failure_writes_failure_post_call_event_and_reraises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=RuntimeError("simulated API failure"))

    with pytest.raises(RuntimeError, match="simulated API failure"):
        video_inventory.fetch_video_inventory(
            youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
        )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "failure"
    assert "simulated API failure" in post["error"]


def test_fetch_video_inventory_collection_id_passthrough(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE)

    video_inventory.fetch_video_inventory(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True,
        collection_id="a-collection-run-id", path=path,
    )

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    assert pre["collection_id"] == "a-collection-run-id"


def test_fetch_video_inventory_query_parameters_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE)

    video_inventory.fetch_video_inventory(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    youtube.playlistItems.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,status",
        playlistId="UUsample000000000000000",
        maxResults=50,
        pageToken=None,
    )


# ---------------------------------------------------------------------
# enrich_video_statistics
# ---------------------------------------------------------------------

def test_enrich_video_statistics_empty_videos_early_return(tmp_path):
    """No videos -> no API call, no ledger writes, run_ceiling_used passes through unchanged."""
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube()

    videos, run_ceiling_used = video_inventory.enrich_video_statistics(
        youtube, [], run_ceiling_used=7, cooldown_ok=True, path=path
    )

    assert videos == []
    assert run_ceiling_used == 7
    youtube.videos.return_value.list.return_value.execute.assert_not_called()
    assert quota_ledger.read_entries(path=path) == []


def test_enrich_video_statistics_single_batch_success(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    videos, run_ceiling_used = video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert videos[0]["video_details"]["id"] == "vid00000001"
    assert run_ceiling_used == 1
    youtube.videos.return_value.list.return_value.execute.assert_called_once()


def test_enrich_video_statistics_multi_batch_success(tmp_path):
    path = tmp_path / "ledger.jsonl"
    videos_in = [_video_stub(f"vid{i:04d}") for i in range(75)]  # 2 batches: 50 + 25
    batch1_ids = [v["video_id"] for v in videos_in[:50]]
    batch2_ids = [v["video_id"] for v in videos_in[50:]]
    response1 = {"items": [{"id": vid} for vid in batch1_ids]}
    response2 = {"items": [{"id": vid} for vid in batch2_ids]}
    youtube = _fake_youtube(videos=[response1, response2])

    videos, run_ceiling_used = video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert all("video_details" in v for v in videos)
    assert run_ceiling_used == 2
    assert youtube.videos.return_value.list.return_value.execute.call_count == 2


def test_enrich_video_statistics_denied_does_not_execute(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    with pytest.raises(QuotaDeniedError):
        video_inventory.enrich_video_statistics(
            youtube, videos_in, run_ceiling_used=50, cooldown_ok=True, path=path
        )

    youtube.videos.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=path)
    assert len(entries) == 1
    assert entries[0]["pre_call_check"]["decision"] == "denied"
    assert entries[0]["pre_call_check"]["binding"] == "run_ceiling"


def test_enrich_video_statistics_batch_20_allowed_all_batches_succeed(tmp_path):
    """Contract Sec 7.2: the batch ceiling, derived from Sec 7.1, is 20 -- exactly 20 batches must all be allowed and succeed."""
    path = tmp_path / "ledger.jsonl"
    videos_in = [_video_stub(f"vid{i:05d}") for i in range(1000)]  # exactly 20 batches of 50
    responses = []
    for start in range(0, 1000, 50):
        batch_ids = [v["video_id"] for v in videos_in[start:start + 50]]
        responses.append({"items": [{"id": vid} for vid in batch_ids]})
    youtube = _fake_youtube(videos=responses)

    videos, run_ceiling_used = video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert all("video_details" in v for v in videos)
    assert run_ceiling_used == 20
    assert youtube.videos.return_value.list.return_value.execute.call_count == 20

    entries = quota_ledger.read_entries(path=path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 20
    assert all(e["pre_call_check"]["decision"] == "allowed" for e in pre_call_events)
    assert pre_call_events[-1]["pre_call_check"]["remaining_pagination_ceiling_before_call"] == 1


def test_enrich_video_statistics_batch_21_denied(tmp_path):
    """The 21st batch (1001st video onward) must be denied before .execute(), with binding pagination_ceiling."""
    path = tmp_path / "ledger.jsonl"
    videos_in = [_video_stub(f"vid{i:05d}") for i in range(1001)]  # 20 full batches + 1 more video
    responses = []
    for start in range(0, 1000, 50):
        batch_ids = [v["video_id"] for v in videos_in[start:start + 50]]
        responses.append({"items": [{"id": vid} for vid in batch_ids]})
    youtube = _fake_youtube(videos=responses)  # only 20 responses configured -- see assertion below

    with pytest.raises(QuotaDeniedError):
        video_inventory.enrich_video_statistics(
            youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    assert youtube.videos.return_value.list.return_value.execute.call_count == 20

    entries = quota_ledger.read_entries(path=path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 21
    assert pre_call_events[-1]["pre_call_check"]["decision"] == "denied"
    assert pre_call_events[-1]["pre_call_check"]["binding"] == "pagination_ceiling"


def test_enrich_video_statistics_pre_call_write_failure_prevents_execute(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    def _raise(*args, **kwargs):
        raise OSError("simulated pre-call ledger write failure")

    monkeypatch.setattr(video_inventory.quota_ledger, "write_pre_call_event", _raise)

    with pytest.raises(OSError):
        video_inventory.enrich_video_statistics(
            youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    youtube.videos.return_value.list.return_value.execute.assert_not_called()


def test_enrich_video_statistics_success_writes_success_post_call_event(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    post = next(e for e in entries if e["event_type"] == "post_call_result")

    assert len(entries) == 2
    assert post["call_id"] == pre["call_id"]
    assert post["outcome"] == "success"
    assert post["error"] is None


def test_enrich_video_statistics_api_failure_writes_failure_post_call_event_and_reraises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=RuntimeError("simulated API failure"))
    videos_in = [_video_stub("vid00000001")]

    with pytest.raises(RuntimeError, match="simulated API failure"):
        video_inventory.enrich_video_statistics(
            youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "failure"
    assert "simulated API failure" in post["error"]


def test_enrich_video_statistics_collection_id_passthrough(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True,
        collection_id="a-collection-run-id", path=path,
    )

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    assert pre["collection_id"] == "a-collection-run-id"


def test_enrich_video_statistics_query_parameters_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    youtube.videos.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,statistics,status",
        id="vid00000001",
        maxResults=50,
    )


def test_enrich_video_statistics_skips_videos_without_video_id(tmp_path):
    """Preserves pre-existing behavior: videos missing a video_id are excluded from the batch request entirely."""
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001"), {"video_id": None}, {}]

    video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    youtube.videos.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,statistics,status",
        id="vid00000001",
        maxResults=50,
    )


def test_enrich_video_statistics_continues_run_ceiling_from_input_value(tmp_path):
    """run_ceiling_used must continue from whatever the caller passed in (e.g. fetch_video_inventory()'s own return value), not reset to 0."""
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    _, run_ceiling_used = video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=5, cooldown_ok=True, path=path
    )

    assert run_ceiling_used == 6

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    assert pre["pre_call_check"]["remaining_run_ceiling_before_call"] == 45


def test_enrich_video_statistics_batch_counter_independent_of_pagination_history(tmp_path):
    """
    Decision 3: enrich_video_statistics() has its own live batch
    counter, entirely independent of how many pages
    fetch_video_inventory() used earlier in the same invocation -- only
    run_ceiling_used carries across. Even if 15 pages were already
    consumed, the batch ceiling here must still show the full 20
    remaining for the first batch.
    """
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(videos=SAMPLE_VIDEOS_LIST_RESPONSE)
    videos_in = [_video_stub("vid00000001")]

    video_inventory.enrich_video_statistics(
        youtube, videos_in, run_ceiling_used=15, cooldown_ok=True, path=path
    )

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    assert pre["pre_call_check"]["remaining_pagination_ceiling_before_call"] == 20


# ---------------------------------------------------------------------
# main() -- full invocation integration
# ---------------------------------------------------------------------

def test_main_both_loops_succeed_without_self_denying_on_cooldown(tmp_path, monkeypatch):
    """
    Regression test mirroring B2.2d's Sec 5.1 finding, reconfirmed for
    B2.2e (decision 4): this script makes two sequential governed calls
    (playlistItems.list then videos.list) in one invocation. If
    cooldown_ok were (re-)derived fresh inside each loop's own pre-call
    check, the second loop would see the first loop's own just-written
    pre-call event and spuriously deny itself on cooldown grounds. Real
    ledger writes throughout (nothing about quota_ledger itself is
    mocked).
    """
    youtube = _fake_youtube(
        playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE,
        videos=SAMPLE_VIDEOS_LIST_RESPONSE,
    )
    ledger_path, output_dir = _patch_main_environment(monkeypatch, tmp_path, youtube)

    video_inventory.main()

    youtube.playlistItems.return_value.list.return_value.execute.assert_called_once()
    youtube.videos.return_value.list.return_value.execute.assert_called_once()

    output_files = list(output_dir.glob("videos_*.json"))
    assert len(output_files) == 1

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 2
    assert all(e["pre_call_check"]["decision"] == "allowed" for e in pre_call_events)
    assert all(e["pre_call_check"]["cooldown_ok"] is True for e in pre_call_events)


def test_main_run_ceiling_threads_across_both_loops(tmp_path, monkeypatch):
    """B2.2e approval decision 5: one run_ceiling_used counter across both loops, not reset between them."""
    page1 = {"items": [_playlist_item("vid00000001")], "nextPageToken": "token-2"}
    page2 = {"items": [_playlist_item("vid00000002")]}
    videos_response = {"items": [{"id": "vid00000001"}, {"id": "vid00000002"}]}
    youtube = _fake_youtube(playlist_items=[page1, page2], videos=videos_response)
    ledger_path, output_dir = _patch_main_environment(monkeypatch, tmp_path, youtube)

    video_inventory.main()

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    remaining_by_operation_order = [
        (e["operation"], e["pre_call_check"]["remaining_run_ceiling_before_call"])
        for e in pre_call_events
    ]

    # 2 playlistItems.list pages, then 1 videos.list batch -- run
    # ceiling counts down 50, 49 across the pages, then 48 for the
    # single batch, never resetting back to 50 for the second loop.
    assert remaining_by_operation_order == [
        ("playlistItems.list", 50),
        ("playlistItems.list", 49),
        ("videos.list", 48),
    ]


def test_main_skips_enrichment_ledger_writes_when_no_videos(tmp_path, monkeypatch):
    """Preserves the empty-video early return: if playlistItems.list finds nothing, videos.list is never called or governed."""
    empty_page = {"items": []}
    youtube = _fake_youtube(playlist_items=empty_page)
    ledger_path, output_dir = _patch_main_environment(monkeypatch, tmp_path, youtube)

    video_inventory.main()

    youtube.videos.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=ledger_path)
    operations = [e["operation"] for e in entries if e["event_type"] == "pre_call_check"]
    assert operations == ["playlistItems.list"]


def test_main_mid_run_denial_in_second_loop_discards_entire_run(tmp_path, monkeypatch):
    """
    Sec 7.3/Sec 10: main() combines both loops' results into one
    snapshot, written once at the end. A denial during the SECOND loop
    (videos.list) must discard the entire run -- including the first
    loop's playlistItems.list results, which already genuinely
    succeeded moments earlier -- not just skip enrichment.
    """
    youtube = _fake_youtube(
        playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE,
        videos=SAMPLE_VIDEOS_LIST_RESPONSE,
    )
    ledger_path, output_dir = _patch_main_environment(monkeypatch, tmp_path, youtube)

    # Pushes the shared known-cost daily budget to the brink under a
    # different script name (so this invocation's own cooldown lookup,
    # scoped to "video_inventory.py", is unaffected): the first loop's
    # single playlistItems.list call is still allowed (1 unit
    # remaining), and consuming it exhausts the pool exactly in time to
    # deny the second loop's videos.list call.
    _seed_known_cost_usage(ledger_path, estimated_cost_units=999, script="other_script.py")

    with pytest.raises(QuotaDeniedError):
        video_inventory.main()

    youtube.playlistItems.return_value.list.return_value.execute.assert_called_once()
    youtube.videos.return_value.list.return_value.execute.assert_not_called()

    assert list(output_dir.glob("videos_*.json")) == []

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [
        e for e in entries
        if e["event_type"] == "pre_call_check" and e["script"] == "video_inventory.py"
    ]
    assert pre_call_events[-1]["pre_call_check"]["decision"] == "denied"
    assert pre_call_events[-1]["pre_call_check"]["binding"] == "daily_budget"


def test_main_collection_id_passthrough_to_both_loops_and_snapshot(tmp_path, monkeypatch):
    youtube = _fake_youtube(
        playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE,
        videos=SAMPLE_VIDEOS_LIST_RESPONSE,
    )
    ledger_path, output_dir = _patch_main_environment(monkeypatch, tmp_path, youtube)
    monkeypatch.setenv("NIK_COLLECTION_ID", "a-collection-run-id")

    video_inventory.main()

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert all(e["collection_id"] == "a-collection-run-id" for e in pre_call_events)

    output_file = next(output_dir.glob("videos_*.json"))
    snapshot = json.loads(output_file.read_text(encoding="utf-8"))
    assert snapshot["collection_id"] == "a-collection-run-id"


def test_main_collection_id_none_when_env_var_absent(tmp_path, monkeypatch):
    youtube = _fake_youtube(
        playlist_items=SAMPLE_PLAYLIST_ITEMS_PAGE,
        videos=SAMPLE_VIDEOS_LIST_RESPONSE,
    )
    ledger_path, output_dir = _patch_main_environment(monkeypatch, tmp_path, youtube)
    monkeypatch.delenv("NIK_COLLECTION_ID", raising=False)

    video_inventory.main()

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert all(e["collection_id"] is None for e in pre_call_events)

    output_file = next(output_dir.glob("videos_*.json"))
    snapshot = json.loads(output_file.read_text(encoding="utf-8"))
    assert snapshot["collection_id"] is None
