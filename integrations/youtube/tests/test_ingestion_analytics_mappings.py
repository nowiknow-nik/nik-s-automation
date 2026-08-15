from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.errors import IngestRejected
from ingestion.mappings import (
    map_channel_analytics_snapshot,
    validate_channel_analytics_snapshot,
)


# ---------------------------------------------------------------------
# Real fixtures, embedded verbatim -- not synthesized. The "good" one is
# data/analytics/channel_analytics_20260812_192340.json; the legacy shape
# below is shared identically by channel_analytics_20260812_172513.json
# and channel_analytics_20260812_173839.json (confirmed genuinely on
# disk, both missing the same four fields). All three real files
# currently show analytics.rows == [[0, 0, 0, 0, 0, 0, 0, 0]] -- every
# requested metric is zero in every real fixture that exists. No real
# fixture demonstrates non-zero analytics values, and none demonstrates
# a genuinely empty analytics.rows == [] (a real, documented possible
# API response, distinct from "one row of zeros"). That distinction is
# intentional and should not be quietly dropped (B2.3.4 design doc
# Sec 3).
# ---------------------------------------------------------------------

GOOD_ANALYTICS_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_channel_analytics",
    "snapshot_id": "e73bc407-59a7-465a-96cb-85a00fcf9ac6",
    "generated_at_utc": "2026-08-12T19:23:40.035508+00:00",
    "source": "youtube_analytics_api",
    "api_version": "v2",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "retrieval_metadata": {
        "retrieved_resources": ["youtubeAnalytics#resultTable"],
        "pagination_completed": None,
        "errors": [],
        "warnings": [],
    },
    "reporting_period": {
        "start_date": "2026-08-05",
        "end_date": "2026-08-11",
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
    "analytics": {
        "kind": "youtubeAnalytics#resultTable",
        "columnHeaders": [
            {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "estimatedMinutesWatched", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "averageViewDuration", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "subscribersGained", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "subscribersLost", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "comments", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "shares", "columnType": "METRIC", "dataType": "INTEGER"},
        ],
        "rows": [[0, 0, 0, 0, 0, 0, 0, 0]],
    },
}

LEGACY_ANALYTICS_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_channel_analytics",
    "generated_at_utc": "2026-08-12T17:25:13.821079+00:00",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "reporting_period": {"start_date": "2026-08-05", "end_date": "2026-08-11"},
    "metrics_requested": [
        "views", "estimatedMinutesWatched", "averageViewDuration", "subscribersGained",
        "subscribersLost", "likes", "comments", "shares",
    ],
    "analytics": {
        "kind": "youtubeAnalytics#resultTable",
        "columnHeaders": [{"name": "views", "columnType": "METRIC", "dataType": "INTEGER"}],
        "rows": [[0, 0, 0, 0, 0, 0, 0, 0]],
    },
    # No snapshot_id, source, api_version, or retrieval_metadata --
    # exactly matching both real legacy files on disk
    # (channel_analytics_20260812_172513.json and
    # channel_analytics_20260812_173839.json share this identical
    # shape). collection_id is also absent here, same as the real
    # files, but that alone is NOT one of the validation failures below
    # -- collection_id is nullable/optional (only checked for UUID
    # validity when present), so its absence is not itself a
    # "missing required field" problem. (B2.3.4 Decision D.)
}


def _write_snapshot(**overrides):
    return {**GOOD_ANALYTICS_SNAPSHOT, **overrides}


# --- validate_channel_analytics_snapshot() -- envelope-level -----------

def test_good_analytics_snapshot_passes_validation():
    validate_channel_analytics_snapshot(GOOD_ANALYTICS_SNAPSHOT)  # must not raise


def test_legacy_analytics_snapshot_rejected_naming_every_missing_field():
    with pytest.raises(IngestRejected) as exc_info:
        validate_channel_analytics_snapshot(LEGACY_ANALYTICS_SNAPSHOT)

    message = str(exc_info.value)
    for field in ("snapshot_id", "source", "api_version", "retrieval_metadata"):
        assert field in message, f"expected {field!r} to be named in the rejection message"

    # collection_id is nullable -- its absence must NOT be reported as
    # a missing-field problem (unlike the four genuinely required
    # fields above). Same distinction B2.3.3's own test suite caught
    # and fixed for its equivalent legacy fixture -- guarded against
    # explicitly here rather than re-learning it.
    assert "collection_id" not in message


def test_invalid_snapshot_id_rejected():
    doc = _write_snapshot(snapshot_id="not-a-uuid")
    with pytest.raises(IngestRejected, match="not a valid UUID"):
        validate_channel_analytics_snapshot(doc)


def test_invalid_collection_id_rejected():
    doc = _write_snapshot(collection_id="not-a-uuid")
    with pytest.raises(IngestRejected, match="not a valid UUID"):
        validate_channel_analytics_snapshot(doc)


def test_null_collection_id_is_valid():
    """A standalone-run snapshot with collection_id: null must pass -- nullable, not required."""
    doc = _write_snapshot(collection_id=None)
    validate_channel_analytics_snapshot(doc)  # must not raise


def test_wrong_snapshot_type_rejected():
    doc = _write_snapshot(snapshot_type="youtube_channel")
    with pytest.raises(IngestRejected, match="snapshot_type must be 'youtube_channel_analytics'"):
        validate_channel_analytics_snapshot(doc)


def test_wrong_source_rejected():
    doc = _write_snapshot(source="youtube_data_api")
    with pytest.raises(IngestRejected, match="source must be 'youtube_analytics_api'"):
        validate_channel_analytics_snapshot(doc)


def test_wrong_api_version_rejected():
    doc = _write_snapshot(api_version="v3")
    with pytest.raises(IngestRejected, match="api_version must be 'v2'"):
        validate_channel_analytics_snapshot(doc)


# --- validate_channel_analytics_snapshot() -- reporting_period ---------
#
# B2.3.4 design doc Sec 4: replicates the live
# channel_analytics_snapshots_period_valid CHECK constraint in Python,
# fail-closed before any SQL is issued.

def test_missing_reporting_period_key_rejected():
    doc = {k: v for k, v in GOOD_ANALYTICS_SNAPSHOT.items() if k != "reporting_period"}
    with pytest.raises(IngestRejected, match="missing required field: 'reporting_period'"):
        validate_channel_analytics_snapshot(doc)


def test_reporting_period_not_an_object_rejected():
    doc = _write_snapshot(reporting_period=["2026-08-05", "2026-08-11"])
    with pytest.raises(IngestRejected, match="missing required field: 'reporting_period'"):
        validate_channel_analytics_snapshot(doc)


def test_reporting_period_missing_start_date_rejected():
    doc = _write_snapshot(reporting_period={"end_date": "2026-08-11"})
    with pytest.raises(IngestRejected, match="reporting_period.start_date"):
        validate_channel_analytics_snapshot(doc)


def test_reporting_period_missing_end_date_rejected():
    doc = _write_snapshot(reporting_period={"start_date": "2026-08-05"})
    with pytest.raises(IngestRejected, match="reporting_period.end_date"):
        validate_channel_analytics_snapshot(doc)


def test_reporting_period_unparseable_start_date_rejected():
    doc = _write_snapshot(reporting_period={"start_date": "not-a-date", "end_date": "2026-08-11"})
    with pytest.raises(IngestRejected, match="does not parse as a date"):
        validate_channel_analytics_snapshot(doc)


def test_reporting_period_end_before_start_rejected():
    """Replicates the live channel_analytics_snapshots_period_valid CHECK constraint."""
    doc = _write_snapshot(reporting_period={"start_date": "2026-08-11", "end_date": "2026-08-05"})
    with pytest.raises(IngestRejected, match="is before start_date"):
        validate_channel_analytics_snapshot(doc)


def test_reporting_period_end_equal_to_start_is_valid():
    """A single-day reporting window (end == start) satisfies `end_date >= start_date`."""
    doc = _write_snapshot(reporting_period={"start_date": "2026-08-05", "end_date": "2026-08-05"})
    validate_channel_analytics_snapshot(doc)  # must not raise


# --- validate_channel_analytics_snapshot() -- metrics_requested --------

def test_missing_metrics_requested_key_rejected():
    doc = {k: v for k, v in GOOD_ANALYTICS_SNAPSHOT.items() if k != "metrics_requested"}
    with pytest.raises(IngestRejected, match="missing required field: 'metrics_requested'"):
        validate_channel_analytics_snapshot(doc)


def test_metrics_requested_not_a_list_rejected():
    doc = _write_snapshot(metrics_requested="views,likes")
    with pytest.raises(IngestRejected, match="'metrics_requested' must be an array"):
        validate_channel_analytics_snapshot(doc)


def test_metrics_requested_with_non_string_element_rejected():
    doc = _write_snapshot(metrics_requested=["views", 123])
    with pytest.raises(IngestRejected, match="array of strings"):
        validate_channel_analytics_snapshot(doc)


def test_metrics_requested_empty_list_is_valid():
    """An empty list is still a list of strings (vacuously) -- not a missing field."""
    doc = _write_snapshot(metrics_requested=[])
    validate_channel_analytics_snapshot(doc)  # must not raise


# --- validate_channel_analytics_snapshot() -- analytics (Decision C) ---
#
# Deliberately minimal/tolerant: 'analytics' must be present and a
# dict. Nothing about 'rows'/'columnHeaders' is validated. These tests
# exist specifically to prove that limit is a decision, not a gap.

def test_missing_analytics_key_rejected():
    doc = {k: v for k, v in GOOD_ANALYTICS_SNAPSHOT.items() if k != "analytics"}
    with pytest.raises(IngestRejected, match="missing required field: 'analytics'"):
        validate_channel_analytics_snapshot(doc)


def test_analytics_not_a_dict_rejected():
    doc = _write_snapshot(analytics=["not", "a", "dict"])
    with pytest.raises(IngestRejected, match="'analytics' must be an object, got list"):
        validate_channel_analytics_snapshot(doc)


def test_analytics_empty_dict_is_accepted():
    """
    B2.3.4 Decision C, made concrete: an empty {} satisfies 'present and
    a dict' -- there is no deeper structural requirement on rows/
    columnHeaders, and none should be silently added later without a
    founder decision to do so.
    """
    doc = _write_snapshot(analytics={})
    validate_channel_analytics_snapshot(doc)  # must not raise


def test_analytics_with_empty_rows_is_accepted():
    """
    A genuinely empty rows: [] (a real, legitimate 'no data for this
    period' API response) must not be rejected -- Decision C means this
    table's validator does not inspect rows at all, empty or not.
    """
    doc = _write_snapshot(analytics={"kind": "youtubeAnalytics#resultTable", "columnHeaders": [], "rows": []})
    validate_channel_analytics_snapshot(doc)  # must not raise


def test_analytics_row_length_mismatch_with_metrics_requested_is_not_checked():
    """
    Decision C explicitly: no cross-check between analytics.rows'
    length and metrics_requested's length exists. This is intentionally
    tolerant, proven here rather than left implicit.
    """
    doc = _write_snapshot(
        metrics_requested=["views", "likes", "comments"],
        analytics={"kind": "youtubeAnalytics#resultTable", "columnHeaders": [], "rows": [[1]]},
    )
    validate_channel_analytics_snapshot(doc)  # must not raise


# --- map_channel_analytics_snapshot() -----------------------------------

def test_map_channel_analytics_snapshot_field_by_field():
    row = map_channel_analytics_snapshot(
        GOOD_ANALYTICS_SNAPSHOT,
        source_file="data/analytics/channel_analytics_20260812_192340.json",
    )

    assert row["snapshot_id"] == "e73bc407-59a7-465a-96cb-85a00fcf9ac6"
    assert row["collection_id"] == "98321ba3-6bf1-4e50-aa8b-8a223ccd4862"
    assert row["channel_id"] == "UCn4OmZFMasYBkmCx6Q2oUBQ"
    assert row["reporting_start_date"] == "2026-08-05"
    assert row["reporting_end_date"] == "2026-08-11"
    assert row["source_file"] == "data/analytics/channel_analytics_20260812_192340.json"

    # Sanity: the extracted dates really do parse as the dates they claim to be.
    assert date.fromisoformat(row["reporting_start_date"]) == date(2026, 8, 5)
    assert date.fromisoformat(row["reporting_end_date"]) == date(2026, 8, 11)


def test_map_channel_analytics_snapshot_has_no_reporting_period_key():
    """The live table has no reporting_period column -- only the two flat date columns."""
    row = map_channel_analytics_snapshot(GOOD_ANALYTICS_SNAPSHOT, source_file="x.json")
    assert "reporting_period" not in row


def test_map_channel_analytics_snapshot_metrics_requested_stays_a_plain_list():
    """
    Load-bearing per the B2.3.4 design doc: metrics_requested must
    remain a plain Python list after mapping, not a Json(...)-wrapped
    object or a re-typed value -- it targets a native Postgres text[]
    column, not jsonb. Wrapping happens (or rather, deliberately does
    not happen) one layer down in analytics_ingest.py, not here, but
    this function must not do anything that would make that wrapping
    decision harder to get right.
    """
    row = map_channel_analytics_snapshot(GOOD_ANALYTICS_SNAPSHOT, source_file="x.json")

    assert type(row["metrics_requested"]) is list
    assert row["metrics_requested"] == GOOD_ANALYTICS_SNAPSHOT["metrics_requested"]
    assert all(isinstance(item, str) for item in row["metrics_requested"])
    # Casing is preserved verbatim -- these are literal YouTube API
    # metric identifiers, not display strings.
    assert "estimatedMinutesWatched" in row["metrics_requested"]


def test_map_channel_analytics_snapshot_preserves_analytics_and_retrieval_metadata_verbatim():
    row = map_channel_analytics_snapshot(GOOD_ANALYTICS_SNAPSHOT, source_file="x.json")

    assert row["analytics"] is GOOD_ANALYTICS_SNAPSHOT["analytics"]
    assert row["analytics"]["rows"] == [[0, 0, 0, 0, 0, 0, 0, 0]]
    assert row["retrieval_metadata"] is GOOD_ANALYTICS_SNAPSHOT["retrieval_metadata"]
    assert row["retrieval_metadata"]["pagination_completed"] is None


def test_map_channel_analytics_snapshot_standalone_run_has_null_collection_id():
    doc = _write_snapshot(collection_id=None)
    row = map_channel_analytics_snapshot(doc, source_file="x.json")

    assert row["collection_id"] is None
