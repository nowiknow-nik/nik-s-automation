from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import channel_snapshot
import quota_ledger
from channel_snapshot import QuotaDeniedError, build_snapshot


SAMPLE_CHANNEL = {
    "kind": "youtube#channel",
    "etag": "sample-etag",
    "id": "UCsample000000000000000",
    "snippet": {
        "title": "Sample Channel",
        "description": "A sample description.",
        "customUrl": "@sample",
        "publishedAt": "2026-01-01T00:00:00Z",
        "country": "US",
    },
    "statistics": {
        "viewCount": "42",
        "subscriberCount": "7",
        "videoCount": "3",
        "hiddenSubscriberCount": False,
    },
    "contentDetails": {
        "relatedPlaylists": {
            "uploads": "UUsample000000000000000",
            "likes": "LL",
        },
    },
    "brandingSettings": {
        "channel": {"title": "Sample Channel"},
    },
}


def test_build_snapshot_has_required_metadata_fields():
    snapshot = build_snapshot(SAMPLE_CHANNEL)

    assert snapshot["schema_version"] == "1.0"
    assert snapshot["snapshot_type"] == "youtube_channel"
    assert snapshot["snapshot_id"]
    assert snapshot["generated_at_utc"]
    assert snapshot["source"] == "youtube_data_api"
    assert snapshot["api_version"] == "v3"
    assert snapshot["channel_id"] == "UCsample000000000000000"


def test_build_snapshot_collection_id_defaults_to_none():
    """
    Standalone runs (outside collector.py) never set NIK_COLLECTION_ID,
    so build_snapshot's default must stay None rather than, say, an
    empty string -- None is how this codebase already distinguishes
    "not applicable" from a real value (see pagination_completed).
    """
    snapshot = build_snapshot(SAMPLE_CHANNEL)

    assert snapshot["collection_id"] is None


def test_build_snapshot_collection_id_passthrough():
    snapshot = build_snapshot(SAMPLE_CHANNEL, collection_id="a-collection-run-id")

    assert snapshot["collection_id"] == "a-collection-run-id"


def test_build_snapshot_snapshot_id_is_unique_per_call():
    first = build_snapshot(SAMPLE_CHANNEL)
    second = build_snapshot(SAMPLE_CHANNEL)

    assert first["snapshot_id"] != second["snapshot_id"]


def test_build_snapshot_retrieval_metadata_shape():
    snapshot = build_snapshot(SAMPLE_CHANNEL)
    retrieval_metadata = snapshot["retrieval_metadata"]

    assert retrieval_metadata["retrieved_resources"] == ["youtube#channel"]
    assert retrieval_metadata["pagination_completed"] is None
    assert retrieval_metadata["errors"] == []
    assert retrieval_metadata["warnings"] == []


def test_build_snapshot_preserves_raw_response_as_evidence():
    snapshot = build_snapshot(SAMPLE_CHANNEL)
    raw = snapshot["evidence"]["raw_response"]

    assert raw is SAMPLE_CHANNEL
    # Fields the reshaped "channel" view below doesn't carry forward
    # are still recoverable from the preserved raw response.
    assert raw["etag"] == "sample-etag"
    assert raw["contentDetails"]["relatedPlaylists"]["likes"] == "LL"


def test_build_snapshot_existing_channel_view_unchanged():
    """
    The pre-existing reshaped "channel" block is untouched by this
    change, including its known missing-vs-zero limitation (see the
    next test) — this pass adds provenance fields alongside it and
    does not modify it.
    """
    snapshot = build_snapshot(SAMPLE_CHANNEL)
    channel = snapshot["channel"]

    assert channel["channel_id"] == "UCsample000000000000000"
    assert channel["title"] == "Sample Channel"
    assert channel["statistics"]["view_count"] == 42
    assert channel["statistics"]["subscriber_count"] == 7
    assert channel["statistics"]["video_count"] == 3
    assert channel["uploads_playlist_id"] == "UUsample000000000000000"


def test_build_snapshot_missing_statistics_field_still_defaults_to_zero():
    """
    Characterization test, not an endorsement. Documents CURRENT,
    known behavior: a statistics field absent from the API response
    is silently recorded as an observed 0, indistinguishable from a
    real zero. This is the exact gap the inspection report flagged in
    build_snapshot() and this pass deliberately does not fix it (the
    founder's own instruction: preserve it as a future data-quality
    validation/test requirement, don't hotfix it here). This test is
    the concrete anchor for that future fix — when the missing-vs-zero
    distinction is implemented, this assertion is expected to change.
    """
    channel_missing_view_count = {
        **SAMPLE_CHANNEL,
        "statistics": {
            "subscriberCount": "7",
            "videoCount": "3",
            # viewCount deliberately absent, not just zero
        },
    }

    snapshot = build_snapshot(channel_missing_view_count)

    assert snapshot["channel"]["statistics"]["view_count"] == 0


# ---------------------------------------------------------
# get_channel() -- quota governance integration (Stage B2.2b)
# ---------------------------------------------------------

SAMPLE_CHANNEL_RESPONSE = {"items": [SAMPLE_CHANNEL]}


def _fake_youtube(response=None, raises=None):
    """
    A minimal stand-in for the googleapiclient youtube resource, deep
    enough to support youtube.channels().list(...).execute().
    """
    youtube = MagicMock()
    execute = youtube.channels.return_value.list.return_value.execute
    if raises is not None:
        execute.side_effect = raises
    else:
        execute.return_value = response
    return youtube


def _seed_known_cost_usage(path, estimated_cost_units, script="other_script.py"):
    """
    Appends one allowed known-cost pre_call_check event carrying an
    arbitrary estimated_cost_units, so compute_known_cost_usage() can
    be pushed to a chosen total without writing hundreds of individual
    entries. write_pre_call_event() does not validate
    estimated_cost_units's value, so this is a safe test shortcut, not
    a shape any production code would actually write.
    """
    quota_ledger.write_pre_call_event(
        script=script,
        operation="channels.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=estimated_cost_units,
        pre_call_check={
            "remaining_run_ceiling_before_call": 1,
            "remaining_daily_budget_before_call": 1,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )


# --- _evaluate_known_cost_pre_call_check() --------------------------

def test_pre_call_check_allowed_when_all_three_checks_pass(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"

    result = channel_snapshot._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, script="channel_snapshot.py", path=ledger_path
    )

    assert result["decision"] == "allowed"
    assert result["binding"] is None
    assert result["remaining_run_ceiling_before_call"] == 50
    assert result["remaining_daily_budget_before_call"] == 1000
    assert result["cooldown_ok"] is True


def test_pre_call_check_denied_run_ceiling_when_process_local_usage_reaches_ceiling(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"

    result = channel_snapshot._evaluate_known_cost_pre_call_check(
        run_ceiling_used=50, script="channel_snapshot.py", path=ledger_path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"
    assert result["remaining_run_ceiling_before_call"] == 0


def test_pre_call_check_denied_daily_budget_when_shared_pool_usage_at_ceiling(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(ledger_path, estimated_cost_units=1000)

    result = channel_snapshot._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, script="channel_snapshot.py", path=ledger_path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "daily_budget"
    assert result["remaining_daily_budget_before_call"] == 0


def test_pre_call_check_denied_cooldown_when_last_invocation_too_recent(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    # A real invocation of this same script, written moments ago.
    channel_snapshot.get_channel(
        _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE), path=ledger_path
    )

    result = channel_snapshot._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, script="channel_snapshot.py", path=ledger_path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "cooldown"
    assert result["cooldown_ok"] is False


def test_pre_call_check_cooldown_ok_when_last_invocation_old_enough(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    channel_snapshot.get_channel(
        _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE), path=ledger_path
    )

    later = quota_ledger.utc_now() + timedelta(minutes=6)
    result = channel_snapshot._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, script="channel_snapshot.py", path=ledger_path, now=later
    )

    assert result["cooldown_ok"] is True
    assert result["decision"] == "allowed"


def test_pre_call_check_run_ceiling_checked_before_daily_budget(tmp_path):
    """
    Contract Sec 6 lists the per-run ceiling (a) before the daily
    budget (b); when both would deny the same call, binding should
    name the first one, not the second.
    """
    ledger_path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(ledger_path, estimated_cost_units=1000)

    result = channel_snapshot._evaluate_known_cost_pre_call_check(
        run_ceiling_used=50, script="channel_snapshot.py", path=ledger_path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"


# --- get_channel() ---------------------------------------------------

def test_get_channel_allowed_executes_api_call_and_returns_channel(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE)

    channel = channel_snapshot.get_channel(youtube, path=ledger_path)

    assert channel == SAMPLE_CHANNEL
    youtube.channels.return_value.list.return_value.execute.assert_called_once()


def test_get_channel_denied_does_not_execute_api_call(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE)

    with pytest.raises(QuotaDeniedError):
        channel_snapshot.get_channel(youtube, run_ceiling_used=50, path=ledger_path)

    youtube.channels.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=ledger_path)
    assert len(entries) == 1
    assert entries[0]["event_type"] == "pre_call_check"
    assert entries[0]["pre_call_check"]["decision"] == "denied"
    assert entries[0]["pre_call_check"]["binding"] == "run_ceiling"


def test_get_channel_ledger_write_failure_prevents_api_call(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE)

    def _raise(*args, **kwargs):
        raise OSError("simulated pre-call ledger write failure")

    monkeypatch.setattr(channel_snapshot.quota_ledger, "write_pre_call_event", _raise)

    with pytest.raises(OSError):
        channel_snapshot.get_channel(youtube, path=ledger_path)

    youtube.channels.return_value.list.return_value.execute.assert_not_called()


def test_get_channel_successful_call_writes_success_post_call_event(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE)

    channel_snapshot.get_channel(youtube, path=ledger_path)

    entries = quota_ledger.read_entries(path=ledger_path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    post = next(e for e in entries if e["event_type"] == "post_call_result")

    assert len(entries) == 2
    assert post["call_id"] == pre["call_id"]
    assert post["outcome"] == "success"
    assert post["error"] is None


def test_get_channel_failed_api_call_writes_failure_post_call_event(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(raises=RuntimeError("simulated API failure"))

    with pytest.raises(RuntimeError, match="simulated API failure"):
        channel_snapshot.get_channel(youtube, path=ledger_path)

    entries = quota_ledger.read_entries(path=ledger_path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")

    assert post["outcome"] == "failure"
    assert "simulated API failure" in post["error"]


def test_get_channel_passes_collection_id_through_to_pre_call_event(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(response=SAMPLE_CHANNEL_RESPONSE)

    channel_snapshot.get_channel(
        youtube, collection_id="a-collection-run-id", path=ledger_path
    )

    entries = quota_ledger.read_entries(path=ledger_path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")

    assert pre["collection_id"] == "a-collection-run-id"


def test_get_channel_raises_when_no_channel_in_response(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(response={"items": []})

    with pytest.raises(RuntimeError, match="No YouTube channel was found"):
        channel_snapshot.get_channel(youtube, path=ledger_path)
