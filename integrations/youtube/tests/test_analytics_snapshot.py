from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

import analytics_snapshot
import quota_ledger
from analytics_snapshot import (
    QuotaDeniedError,
    fetch_channel_analytics,
)


SAMPLE_ANALYTICS_RESPONSE = {
    "kind": "youtubeAnalytics#resultTable",
    "columnHeaders": [
        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
    ],
    "rows": [[123]],
}


def _ledger_path(tmp_path):
    return tmp_path / "quota_ledger.jsonl"


def _fake_youtube_analytics(response=None, raises=None):
    """MagicMock fake for youtube_analytics.reports().query(...).execute()."""
    youtube_analytics = MagicMock()
    execute_mock = youtube_analytics.reports.return_value.query.return_value.execute
    if raises is not None:
        execute_mock.side_effect = raises
    else:
        execute_mock.return_value = (
            response if response is not None else SAMPLE_ANALYTICS_RESPONSE
        )
    return youtube_analytics


def _seed_analytics_invocations(path, count, script="analytics_snapshot.py"):
    """Writes `count` allowed dynamic-cost pre-call events, for ceiling/cooldown tests."""
    for _ in range(count):
        quota_ledger.write_pre_call_event(
            script=script,
            operation="reports.query",
            collection_id=None,
            cost_model=quota_ledger.DYNAMIC_COST_MODEL,
            estimated_cost_units=None,
            pre_call_check={
                "policy": analytics_snapshot.ANALYTICS_POLICY_NAME,
                "invocations_remaining_in_window": 0,
                "cooldown_ok": True,
                "binding": None,
                "decision": quota_ledger.ALLOWED,
            },
            path=path,
        )


# ---------------------------------------------------------------------
# _evaluate_analytics_pre_call_check
# ---------------------------------------------------------------------

def test_evaluate_allowed_baseline(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

    result = analytics_snapshot._evaluate_analytics_pre_call_check(
        calls_made_this_invocation=0, path=path, now=now,
    )

    assert result == {
        "policy": "analytics_call_frequency_v1",
        "invocations_remaining_in_window": 12,
        "cooldown_ok": True,
        "binding": None,
        "decision": "allowed",
    }


def test_evaluate_per_invocation_limit_denied(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

    result = analytics_snapshot._evaluate_analytics_pre_call_check(
        calls_made_this_invocation=1, path=path, now=now,
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "per_invocation_limit"


def test_evaluate_invocation_ceiling_denied(tmp_path):
    path = _ledger_path(tmp_path)
    old_time = datetime(2026, 8, 13, 6, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=old_time):
        _seed_analytics_invocations(path, 12)

    # Past the 5-minute cooldown, but still well within the 24h window,
    # so only the invocation ceiling -- not cooldown -- should bind.
    now = old_time + timedelta(minutes=10)
    result = analytics_snapshot._evaluate_analytics_pre_call_check(
        calls_made_this_invocation=0, path=path, now=now,
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "invocation_ceiling"
    assert result["invocations_remaining_in_window"] == 0


def test_evaluate_cooldown_denied(tmp_path):
    path = _ledger_path(tmp_path)
    _seed_analytics_invocations(path, 1)  # written "just now"

    result = analytics_snapshot._evaluate_analytics_pre_call_check(
        calls_made_this_invocation=0, path=path,
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "cooldown"
    assert result["cooldown_ok"] is False


def test_evaluate_cooldown_ok_when_old_enough(tmp_path):
    path = _ledger_path(tmp_path)
    old_time = datetime(2026, 8, 13, 6, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=old_time):
        _seed_analytics_invocations(path, 1)

    now = old_time + timedelta(minutes=10)
    result = analytics_snapshot._evaluate_analytics_pre_call_check(
        calls_made_this_invocation=0, path=path, now=now,
    )

    assert result["cooldown_ok"] is True
    assert result["decision"] == "allowed"


def test_evaluate_per_invocation_limit_checked_before_cooldown(tmp_path):
    path = _ledger_path(tmp_path)
    _seed_analytics_invocations(path, 1)  # written "just now" -- cooldown would also deny

    result = analytics_snapshot._evaluate_analytics_pre_call_check(
        calls_made_this_invocation=1, path=path,
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "per_invocation_limit"


# ---------------------------------------------------------------------
# fetch_channel_analytics
# ---------------------------------------------------------------------

def test_allowed_call_executes_and_returns_response(tmp_path):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics(response=SAMPLE_ANALYTICS_RESPONSE)

    result = fetch_channel_analytics(
        youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07", path=path,
    )

    assert result == SAMPLE_ANALYTICS_RESPONSE
    youtube_analytics.reports.return_value.query.return_value.execute.assert_called_once()


def test_denied_call_does_not_execute_and_writes_only_pre_call_event(tmp_path):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics()

    with pytest.raises(QuotaDeniedError):
        fetch_channel_analytics(
            youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07",
            calls_made_this_invocation=1,  # forces per_invocation_limit denial
            path=path,
        )

    youtube_analytics.reports.return_value.query.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path)
    assert len(entries) == 1
    assert entries[0]["event_type"] == "pre_call_check"
    assert entries[0]["pre_call_check"]["decision"] == "denied"
    assert entries[0]["pre_call_check"]["binding"] == "per_invocation_limit"


def test_pre_call_write_failure_prevents_execute(tmp_path, monkeypatch):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics()

    def _raise_on_write(*args, **kwargs):
        raise OSError("simulated ledger write failure")

    monkeypatch.setattr(analytics_snapshot.quota_ledger, "write_pre_call_event", _raise_on_write)

    with pytest.raises(OSError):
        fetch_channel_analytics(
            youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07", path=path,
        )

    youtube_analytics.reports.return_value.query.return_value.execute.assert_not_called()


def test_successful_call_writes_success_post_call_event(tmp_path):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics(response=SAMPLE_ANALYTICS_RESPONSE)

    fetch_channel_analytics(
        youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07", path=path,
    )

    entries = quota_ledger.read_entries(path)
    assert len(entries) == 2
    assert entries[1]["event_type"] == "post_call_result"
    assert entries[1]["outcome"] == "success"
    assert entries[1]["error"] is None


def test_failed_api_call_writes_failure_post_call_event_and_reraises(tmp_path):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics(raises=RuntimeError("HttpError 500"))

    with pytest.raises(RuntimeError, match="HttpError 500"):
        fetch_channel_analytics(
            youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07", path=path,
        )

    entries = quota_ledger.read_entries(path)
    assert len(entries) == 2
    assert entries[1]["event_type"] == "post_call_result"
    assert entries[1]["outcome"] == "failure"
    assert entries[1]["error"] == "HttpError 500"


def test_collection_id_passthrough_onto_pre_call_event(tmp_path):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics(response=SAMPLE_ANALYTICS_RESPONSE)

    fetch_channel_analytics(
        youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07",
        collection_id="abc-123", path=path,
    )

    entries = quota_ledger.read_entries(path)
    assert entries[0]["collection_id"] == "abc-123"


def test_query_parameters_unchanged(tmp_path):
    path = _ledger_path(tmp_path)
    youtube_analytics = _fake_youtube_analytics(response=SAMPLE_ANALYTICS_RESPONSE)

    fetch_channel_analytics(
        youtube_analytics, "UCxxx", "2026-08-01", "2026-08-07", path=path,
    )

    youtube_analytics.reports.return_value.query.assert_called_once_with(
        ids="channel==UCxxx",
        startDate="2026-08-01",
        endDate="2026-08-07",
        metrics=(
            "views,estimatedMinutesWatched,averageViewDuration,"
            "subscribersGained,subscribersLost,likes,comments,shares"
        ),
    )
