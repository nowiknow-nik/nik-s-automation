from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from quota_ledger import (
    LedgerReadError,
    write_pre_call_event,
    write_post_call_event,
    read_entries,
    compute_known_cost_usage,
    known_cost_usage_last_24h,
    compute_search_usage,
    search_usage_last_24h,
    compute_analytics_call_count,
    analytics_call_count_last_24h,
    most_recent_invocation_timestamp,
)


def _ledger_path(tmp_path):
    return tmp_path / "quota_ledger.jsonl"


def _write_known(path, decision="allowed", estimated_cost_units=1, script="channel_snapshot.py", operation="channels.list", collection_id=None):
    return write_pre_call_event(
        script=script,
        operation=operation,
        collection_id=collection_id,
        cost_model="known",
        estimated_cost_units=estimated_cost_units,
        pre_call_check={
            "remaining_run_ceiling_before_call": 49,
            "remaining_daily_budget_before_call": 999,
            "cooldown_ok": True,
            "binding": None if decision == "allowed" else "daily_budget",
            "decision": decision,
        },
        path=path,
    )


def _write_search(path, decision="allowed", estimated_cost_units=1, script="youtube_discovery.py", collection_id=None):
    """
    search.list is cost_model == "known" (Contract Sec 4.1) but not
    shared-pool -- its pre_call_check shape has no
    remaining_daily_budget_before_call field (Schema Sec 6.2), and its
    own usage is counted separately (compute_search_usage(), not
    compute_known_cost_usage()).
    """
    return write_pre_call_event(
        script=script,
        operation="search.list",
        collection_id=collection_id,
        cost_model="known",
        estimated_cost_units=estimated_cost_units,
        pre_call_check={
            "remaining_run_ceiling_before_call": 49,
            "remaining_search_allocation_before_call": 99,
            "cooldown_ok": True,
            "binding": None if decision == "allowed" else "search_allocation",
            "decision": decision,
        },
        path=path,
    )


def _write_dynamic(path, decision="allowed", script="analytics_snapshot.py", operation="reports.query", collection_id=None):
    return write_pre_call_event(
        script=script,
        operation=operation,
        collection_id=collection_id,
        cost_model="dynamic",
        estimated_cost_units=None,
        pre_call_check={
            "policy": "analytics_call_frequency_v1",
            "invocations_remaining_in_window": 11,
            "cooldown_ok": True,
            "binding": None if decision == "allowed" else "invocation_ceiling",
            "decision": decision,
        },
        path=path,
    )


# ---------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------

def test_write_pre_call_event_returns_call_id_and_persists_it(tmp_path):
    path = _ledger_path(tmp_path)
    call_id = _write_known(path)

    entries = read_entries(path)
    assert len(entries) == 1
    assert entries[0]["call_id"] == call_id
    assert entries[0]["event_type"] == "pre_call_check"
    assert entries[0]["ledger_schema_version"] == "1.2"


def test_write_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deeper" / "quota_ledger.jsonl"
    _write_known(path)
    assert path.exists()


def test_pre_call_and_post_call_share_call_id(tmp_path):
    path = _ledger_path(tmp_path)
    call_id = _write_known(path)
    write_post_call_event(call_id=call_id, outcome="success", error=None, path=path)

    entries = read_entries(path)
    assert len(entries) == 2
    assert entries[0]["call_id"] == call_id
    assert entries[1]["call_id"] == call_id
    assert entries[0]["event_type"] == "pre_call_check"
    assert entries[1]["event_type"] == "post_call_result"


def test_post_call_event_records_failure_and_error(tmp_path):
    path = _ledger_path(tmp_path)
    call_id = _write_known(path)
    write_post_call_event(call_id=call_id, outcome="failure", error="HttpError 403", path=path)

    entries = read_entries(path)
    assert entries[1]["outcome"] == "failure"
    assert entries[1]["error"] == "HttpError 403"


def test_post_call_actual_cost_units_defaults_to_null(tmp_path):
    """
    Whether Google exposes actually-consumed quota per call has not
    been independently verified (Schema v1.1 Sec 6.3). Nothing should
    default this to estimated_cost_units or any other guessed value.
    """
    path = _ledger_path(tmp_path)
    call_id = _write_known(path)
    write_post_call_event(call_id=call_id, outcome="success", error=None, path=path)

    entries = read_entries(path)
    assert entries[1]["actual_cost_units"] is None


def test_denied_call_writes_only_pre_call_event(tmp_path):
    path = _ledger_path(tmp_path)
    _write_known(path, decision="denied")

    entries = read_entries(path)
    assert len(entries) == 1
    assert entries[0]["event_type"] == "pre_call_check"
    assert entries[0]["pre_call_check"]["decision"] == "denied"


def test_write_pre_call_event_rejects_invalid_cost_model(tmp_path):
    path = _ledger_path(tmp_path)
    with pytest.raises(ValueError):
        write_pre_call_event(
            script="x", operation="y", collection_id=None,
            cost_model="bogus", estimated_cost_units=1,
            pre_call_check={"decision": "allowed"},
            path=path,
        )


def test_write_pre_call_event_rejects_invalid_decision(tmp_path):
    path = _ledger_path(tmp_path)
    with pytest.raises(ValueError):
        write_pre_call_event(
            script="x", operation="y", collection_id=None,
            cost_model="known", estimated_cost_units=1,
            pre_call_check={"decision": "maybe"},
            path=path,
        )


def test_write_post_call_event_rejects_invalid_outcome(tmp_path):
    path = _ledger_path(tmp_path)
    with pytest.raises(ValueError):
        write_post_call_event(call_id="whatever", outcome="ok", error=None, path=path)


# ---------------------------------------------------------------------
# The key property: an orphaned allowed call still counts.
# This is the specific behavior the two-event design (Option A) exists
# to guarantee -- see NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md Sec 4 and 10.2.
# ---------------------------------------------------------------------

def test_orphaned_allowed_call_still_counts_toward_usage(tmp_path):
    """
    allowed pre-call event exists
            +
    NO post-call event
            v
    still counted against quota

    Simulates a process that made the real API call and then crashed
    before it could write the post-call result. If this test fails,
    an interrupted process can make a real API call disappear from
    quota accounting -- exactly the governance gap Option A was chosen
    over Option B to close.
    """
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_known(path, decision="allowed", estimated_cost_units=1)
    # Deliberately no write_post_call_event call here.

    usage = known_cost_usage_last_24h(path=path, now=now)

    assert usage == 1


def test_orphaned_allowed_analytics_call_still_counts(tmp_path):
    """Same property as above, for the dynamic-cost / Analytics frequency count."""
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_dynamic(path, decision="allowed")
    # No post-call event.

    assert analytics_call_count_last_24h(path=path, now=now) == 1


def test_completed_call_counts_the_same_as_an_orphaned_one(tmp_path):
    """
    A call that got its post-call event and one that didn't must count
    identically toward usage -- usage accounting depends only on the
    pre-call event, never on whether a post-call event exists.
    """
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        call_id = _write_known(path, decision="allowed", estimated_cost_units=1)
        write_post_call_event(call_id=call_id, outcome="success", error=None, path=path)

    assert known_cost_usage_last_24h(path=path, now=now) == 1


# ---------------------------------------------------------------------
# Denied calls and how denied calls are excluded
# ---------------------------------------------------------------------

def test_denied_pre_call_excluded_from_known_cost_usage(tmp_path):
    path = _ledger_path(tmp_path)
    _write_known(path, decision="denied")

    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert known_cost_usage_last_24h(path=path, now=now) == 0


def test_denied_pre_call_excluded_from_analytics_call_count(tmp_path):
    path = _ledger_path(tmp_path)
    _write_dynamic(path, decision="denied")

    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert analytics_call_count_last_24h(path=path, now=now) == 0


# ---------------------------------------------------------------------
# Known-cost vs. dynamic-cost separation
# ---------------------------------------------------------------------

def test_known_cost_summation_excludes_dynamic_cost_entries(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_dynamic(path, decision="allowed")
        _write_known(path, decision="allowed", estimated_cost_units=1)

    # Only the known-cost entry should contribute -- the dynamic entry
    # has no unit value and must never be summed in.
    assert known_cost_usage_last_24h(path=path, now=now) == 1


def test_analytics_call_count_excludes_known_cost_entries(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_known(path, decision="allowed", estimated_cost_units=1, script="analytics_snapshot.py", operation="channels.list")
        _write_dynamic(path, decision="allowed")

    assert analytics_call_count_last_24h(path=path, now=now, script="analytics_snapshot.py") == 1


def test_analytics_call_count_scoped_to_requested_script(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_dynamic(path, decision="allowed", script="analytics_snapshot.py")
        _write_known(path, decision="allowed", estimated_cost_units=1, script="channel_snapshot.py")

    assert analytics_call_count_last_24h(path=path, now=now, script="analytics_snapshot.py") == 1


# ---------------------------------------------------------------------
# search.list usage -- separate from both shared-pool known-cost usage
# and Analytics call count (Stage B2.1's accounting correction,
# Stage B2.2a's code update -- Contract Sec 4.1/Sec 6/Sec 8, Schema
# Sec 10.1).
# ---------------------------------------------------------------------

def test_known_cost_summation_excludes_search_list_entries(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_search(path, decision="allowed", estimated_cost_units=1)
        _write_known(path, decision="allowed", estimated_cost_units=1)

    # Only the ordinary known-cost (channels.list) entry should
    # contribute -- search.list draws from its own separate allocation
    # and must never be summed into the shared pool.
    assert known_cost_usage_last_24h(path=path, now=now) == 1


def test_search_usage_excludes_ordinary_known_cost_entries(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_known(path, decision="allowed", estimated_cost_units=1)
        _write_search(path, decision="allowed", estimated_cost_units=1)

    assert search_usage_last_24h(path=path, now=now) == 1


def test_search_usage_excludes_dynamic_cost_entries(tmp_path):
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_dynamic(path, decision="allowed")
        _write_search(path, decision="allowed", estimated_cost_units=1)

    assert search_usage_last_24h(path=path, now=now) == 1


def test_denied_search_pre_call_excluded_from_search_usage(tmp_path):
    path = _ledger_path(tmp_path)
    _write_search(path, decision="denied")

    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert search_usage_last_24h(path=path, now=now) == 0


def test_orphaned_allowed_search_call_still_counts_toward_usage(tmp_path):
    """
    Same crash-safety property as the shared-pool and Analytics usage
    functions (see the orphaned-call tests above): an allowed
    search.list pre-call event with no post-call event -- because the
    process made the real API call and crashed before recording the
    result -- must still count toward search.list's own rolling
    allocation. If this failed, an interrupted process could make a
    real search.list call disappear from the one governance mechanism
    (Sec 8) that stands between this operation and an unbounded search
    loop.
    """
    path = _ledger_path(tmp_path)
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=now):
        _write_search(path, decision="allowed", estimated_cost_units=1)
    # Deliberately no write_post_call_event call here.

    assert search_usage_last_24h(path=path, now=now) == 1


def test_search_usage_rolling_window_excludes_entries_older_than_24_hours(tmp_path):
    path = _ledger_path(tmp_path)
    old_time = datetime(2026, 8, 10, 0, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=old_time):
        _write_search(path, decision="allowed", estimated_cost_units=1)

    now = old_time + timedelta(hours=25)
    assert search_usage_last_24h(path=path, now=now) == 0


def test_compute_search_usage_pure_function_on_in_memory_entries():
    """
    Exercises compute_search_usage directly, without file I/O -- same
    rationale as the equivalent known-cost and Analytics tests above:
    easiest to reason about, and to unit test precisely, as a pure
    function over an explicit list of entries.
    """
    window_start = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    in_window = datetime(2026, 8, 13, 0, 0, 0, tzinfo=timezone.utc)

    entries = [
        {
            "event_type": "pre_call_check", "cost_model": "known",
            "operation": "search.list", "estimated_cost_units": 1,
            "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "allowed"},
        },
        {
            "event_type": "pre_call_check", "cost_model": "known",
            "operation": "search.list", "estimated_cost_units": 1,
            "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "denied"},
        },
        {
            "event_type": "pre_call_check", "cost_model": "known",
            "operation": "channels.list", "estimated_cost_units": 1,
            "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "allowed"},
        },
    ]

    assert compute_search_usage(entries, window_start, window_end) == 1


# ---------------------------------------------------------------------
# Rolling 24-hour window
# ---------------------------------------------------------------------

def test_rolling_window_excludes_entries_older_than_24_hours(tmp_path):
    path = _ledger_path(tmp_path)
    old_time = datetime(2026, 8, 10, 0, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=old_time):
        _write_known(path, decision="allowed", estimated_cost_units=1)

    now = old_time + timedelta(hours=25)
    assert known_cost_usage_last_24h(path=path, now=now) == 0


def test_rolling_window_includes_entry_at_exact_boundary(tmp_path):
    path = _ledger_path(tmp_path)
    boundary_time = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=boundary_time):
        _write_known(path, decision="allowed", estimated_cost_units=1)

    now = boundary_time + timedelta(hours=24)
    assert known_cost_usage_last_24h(path=path, now=now) == 1


def test_compute_known_cost_usage_pure_function_on_in_memory_entries():
    """
    Exercises compute_known_cost_usage directly, without going through
    file I/O -- the wrapper (known_cost_usage_last_24h) is convenient
    for real callers, but the underlying computation is easiest to
    reason about, and to unit test precisely, as a pure function over
    an explicit list of entries.
    """
    window_start = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    in_window = datetime(2026, 8, 13, 0, 0, 0, tzinfo=timezone.utc)

    entries = [
        {
            "event_type": "pre_call_check", "cost_model": "known",
            "estimated_cost_units": 1, "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "allowed"},
        },
        {
            "event_type": "pre_call_check", "cost_model": "known",
            "estimated_cost_units": 1, "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "denied"},
        },
        {
            "event_type": "post_call_result", "call_id": "irrelevant",
            "timestamp_utc": in_window.isoformat(),
        },
    ]

    assert compute_known_cost_usage(entries, window_start, window_end) == 1


def test_compute_analytics_call_count_pure_function_on_in_memory_entries():
    window_start = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    in_window = datetime(2026, 8, 13, 0, 0, 0, tzinfo=timezone.utc)

    entries = [
        {
            "event_type": "pre_call_check", "script": "analytics_snapshot.py",
            "cost_model": "dynamic", "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "allowed"},
        },
        {
            "event_type": "pre_call_check", "script": "analytics_snapshot.py",
            "cost_model": "dynamic", "timestamp_utc": in_window.isoformat(),
            "pre_call_check": {"decision": "allowed"},
        },
    ]

    assert compute_analytics_call_count(entries, window_start, window_end, script="analytics_snapshot.py") == 2


def test_rolling_window_is_a_true_rolling_window_not_a_calendar_day(tmp_path):
    """
    Two entries 20 hours apart, straddling a UTC midnight, must both
    count if "now" is within 24h of both -- this is what distinguishes
    a rolling window from a calendar-day reset (Schema v1.1 Sec 3).
    """
    path = _ledger_path(tmp_path)
    first = datetime(2026, 8, 12, 23, 0, 0, tzinfo=timezone.utc)
    second = datetime(2026, 8, 13, 3, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=first):
        _write_known(path, decision="allowed", estimated_cost_units=1)
    with patch("quota_ledger.utc_now", return_value=second):
        _write_known(path, decision="allowed", estimated_cost_units=1)

    now = second + timedelta(hours=1)
    assert known_cost_usage_last_24h(path=path, now=now) == 2


# ---------------------------------------------------------------------
# Read behavior: missing file, incomplete line, malformed line
# ---------------------------------------------------------------------

def test_missing_ledger_file_returns_empty_not_error(tmp_path):
    path = tmp_path / "does_not_exist.jsonl"
    assert read_entries(path) == []


def test_missing_ledger_file_means_zero_usage_not_a_denial(tmp_path):
    """
    A ledger that has never been created represents a fresh deployment
    with genuinely zero history, not an unreadable ledger -- see
    read_entries()'s docstring. This must resolve to a real, usable
    zero, not raise LedgerReadError, or nothing could ever write the
    first entry.
    """
    path = tmp_path / "does_not_exist.jsonl"
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert known_cost_usage_last_24h(path=path, now=now) == 0


def _write_raw_line(path, obj):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def _sample_entry(**overrides):
    entry = {
        "ledger_schema_version": "1.2",
        "entry_id": "e-1",
        "call_id": "c-1",
        "event_type": "pre_call_check",
        "timestamp_utc": "2026-08-13T00:00:00+00:00",
        "script": "channel_snapshot.py",
        "operation": "channels.list",
        "collection_id": None,
        "cost_model": "known",
        "estimated_cost_units": 1,
        "pre_call_check": {
            "remaining_run_ceiling_before_call": 49,
            "remaining_daily_budget_before_call": 999,
            "cooldown_ok": True,
            "binding": None,
            "decision": "allowed",
        },
    }
    entry.update(overrides)
    return entry


def test_incomplete_final_line_is_tolerated_and_skipped(tmp_path):
    path = _ledger_path(tmp_path)
    _write_raw_line(path, _sample_entry())
    with path.open("a", encoding="utf-8") as f:
        f.write('{"incomplete": tru')  # no trailing newline, invalid JSON

    entries = read_entries(path)
    assert len(entries) == 1
    assert entries[0]["entry_id"] == "e-1"


def test_malformed_non_final_line_raises_LedgerReadError(tmp_path):
    path = _ledger_path(tmp_path)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"broken": tru\n')
    _write_raw_line(path, _sample_entry())

    with pytest.raises(LedgerReadError):
        read_entries(path)


def test_blank_lines_are_skipped(tmp_path):
    path = _ledger_path(tmp_path)
    _write_raw_line(path, _sample_entry())
    with path.open("a", encoding="utf-8") as f:
        f.write("\n")
    _write_raw_line(path, _sample_entry(entry_id="e-2", call_id="c-2"))

    entries = read_entries(path)
    assert len(entries) == 2


def test_unreadable_existing_file_raises_LedgerReadError(tmp_path):
    """
    Distinct from the missing-file case: this simulates a ledger that
    exists but cannot be read (permission error, I/O error). Mocked
    rather than done via real OS permissions, since permission
    semantics differ between this sandbox (POSIX) and the project's
    real deployment target (Windows) -- the behavior under test is the
    exception translation inside read_entries(), not any particular
    OS's enforcement mechanism.
    """
    path = _ledger_path(tmp_path)
    path.write_text("{}\n", encoding="utf-8")

    with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
        with pytest.raises(LedgerReadError):
            read_entries(path)


# ---------------------------------------------------------------------
# Cooldown helper
# ---------------------------------------------------------------------

def test_most_recent_invocation_timestamp_finds_latest_regardless_of_decision(tmp_path):
    path = _ledger_path(tmp_path)
    t1 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 13, 11, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=t1):
        _write_dynamic(path, decision="allowed")
    with patch("quota_ledger.utc_now", return_value=t2):
        _write_dynamic(path, decision="denied")

    entries = read_entries(path)
    latest = most_recent_invocation_timestamp(entries, "analytics_snapshot.py")

    assert latest == t2


def test_most_recent_invocation_timestamp_returns_none_when_absent(tmp_path):
    path = _ledger_path(tmp_path)
    entries = read_entries(path)
    assert most_recent_invocation_timestamp(entries, "analytics_snapshot.py") is None


def test_most_recent_invocation_timestamp_scoped_to_script(tmp_path):
    path = _ledger_path(tmp_path)
    t1 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 13, 11, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=t1):
        _write_known(path, decision="allowed", script="analytics_snapshot.py", operation="channels.list")
    with patch("quota_ledger.utc_now", return_value=t2):
        _write_known(path, decision="allowed", script="channel_snapshot.py")

    entries = read_entries(path)
    latest = most_recent_invocation_timestamp(entries, "analytics_snapshot.py")

    assert latest == t1
