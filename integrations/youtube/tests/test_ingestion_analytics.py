import json
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest
from psycopg2.extras import Json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.analytics_ingest import ingest_channel_analytics
from ingestion.errors import IngestRejected


# Mirrors test_ingestion_video_inventory.py's fixtures and helpers
# exactly, adapted for channel_analytics_snapshots. GOOD_ANALYTICS_SNAPSHOT
# is the same real fixture (channel_analytics_20260812_192340.json)
# embedded in test_ingestion_analytics_mappings.py -- this file exercises
# ingest_channel_analytics()'s orchestration (transaction boundary,
# duplicate handling, FK resolution, and the metrics_requested Json-
# wrapping distinction), not the per-field mapping/validation logic,
# which test_ingestion_analytics_mappings.py already covers in full.

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

GOOD_COLLECTION_RUN = {
    "schema_version": "1.0",
    "collection_type": "youtube_full_collection",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "collection_started_at_utc": "2026-08-12T19:23:30.436491+00:00",
    "collection_finished_at_utc": "2026-08-12T19:23:40.192417+00:00",
    "success": True,
    "components": [{"component": "channel_analytics", "success": True}],
}


def _write_json(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")


def _mock_connection(fetchone_results):
    """
    A minimal stand-in for a psycopg2 connection, deep enough to
    support `with conn.cursor() as cur: cur.execute(...); cur.fetchone()`.
    fetchone_results is consumed in call order, matching the order
    ingest_channel_analytics() / ensure_collection_run() issue queries in.
    """
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone_results
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _executed_sql(cursor):
    return [call.args[0] for call in cursor.execute.call_args_list]


# --- ingest_channel_analytics() ------------------------------------------

def test_ingest_pure_local_dry_run_with_no_connection(tmp_path):
    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    result = ingest_channel_analytics(path, conn=None, dry_run=True)

    assert result.dry_run is True
    assert result.channel_analytics_snapshot_inserted is False
    assert result.snapshot_id == "e73bc407-59a7-465a-96cb-85a00fcf9ac6"


def test_ingest_dry_run_false_with_no_connection_raises(tmp_path):
    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    with pytest.raises(ValueError, match="requires a real database connection"):
        ingest_channel_analytics(path, conn=None, dry_run=False)


def test_ingest_malformed_file_rejected_before_any_db_call(tmp_path):
    path = tmp_path / "channel_analytics_20260812_172513.json"
    _write_json(path, {"schema_version": "1.0", "analytics": {}})  # missing everything else

    conn, cursor = _mock_connection(fetchone_results=[])

    with pytest.raises(IngestRejected):
        ingest_channel_analytics(path, conn=conn, dry_run=False)

    cursor.execute.assert_not_called()


def test_ingest_full_dry_run_with_live_connection_issues_no_writes(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    # collection_runs exists-check -> None (missing); channel_analytics_snapshots exists-check -> None (missing)
    conn, cursor = _mock_connection(fetchone_results=[None, None])

    result = ingest_channel_analytics(path, conn=conn, dry_run=True)

    assert result.dry_run is True
    assert result.channel_analytics_snapshot_inserted is False
    assert result.collection_run_inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()
    conn.commit.assert_not_called()


def test_ingest_first_real_insert_inserts_parent_then_child_and_commits(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    # Order: collection_runs exists? -> None; insert collection_runs -> row;
    #        channel_analytics_snapshots exists? -> None; insert channel_analytics_snapshots -> row.
    conn, cursor = _mock_connection(
        fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None, ("e73bc407-59a7-465a-96cb-85a00fcf9ac6",)]
    )

    result = ingest_channel_analytics(path, conn=conn, dry_run=False)

    assert result.collection_run_inserted is True
    assert result.channel_analytics_snapshot_inserted is True
    executed = _executed_sql(cursor)
    # Parent insert must happen before the child insert (design doc Sec 6.2).
    collection_idx = next(i for i, s in enumerate(executed) if "insert into youtube_evidence.collection_runs" in s.lower())
    snapshot_idx = next(i for i, s in enumerate(executed) if "insert into youtube_evidence.channel_analytics_snapshots" in s.lower())
    assert collection_idx < snapshot_idx
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()


def test_ingest_duplicate_snapshot_is_a_clean_skip_not_an_error(tmp_path, monkeypatch):
    """Idempotency (design doc Sec 7): re-ingesting an already-present snapshot_id writes nothing."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    # collection_runs already exists (row 1); channel_analytics_snapshots already exists (row 2).
    conn, cursor = _mock_connection(fetchone_results=[(1,), (1,)])

    result = ingest_channel_analytics(path, conn=conn, dry_run=False)

    assert result.channel_analytics_snapshot_inserted is False
    assert result.collection_run_inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()
    conn.commit.assert_called_once()  # still commits cleanly -- a no-op skip, not an error


def test_ingest_rolls_back_on_failure_after_parent_insert(tmp_path, monkeypatch):
    """
    If the child insert blows up after the parent insert succeeded,
    the transaction must roll back -- a failed run must never leave an
    orphaned collection_runs row with no corresponding snapshot.
    """
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    conn, cursor = _mock_connection(fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None])
    cursor.execute.side_effect = [None, None, None, RuntimeError("simulated insert failure")]

    with pytest.raises(RuntimeError, match="simulated insert failure"):
        ingest_channel_analytics(path, conn=conn, dry_run=False)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_ingest_fails_closed_when_no_matching_collection_log_exists(tmp_path, monkeypatch):
    """
    Reuses collection_runs.ensure_collection_run()'s fail-closed
    behavior (B2.3.3 Decision 2 -- shared, unchanged logic): a
    collection_id with no matching logs/collection_*.json and no
    existing collection_runs row must raise IngestRejected rather than
    silently proceeding with an unresolvable FK.
    """
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()  # empty -- no matching log file

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    conn, cursor = _mock_connection(fetchone_results=[None])  # collection_runs exists-check -> missing

    with pytest.raises(IngestRejected, match="no matching logs/collection_\\*.json"):
        ingest_channel_analytics(path, conn=conn, dry_run=False)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_ingest_passes_metrics_requested_as_plain_list_not_json_wrapped(tmp_path, monkeypatch):
    """
    metrics_requested targets a native `text[]` column, not jsonb --
    unlike every other structured field on this table (see mappings.py's
    map_channel_analytics_snapshot() and design doc Sec 4/5). The insert
    must pass it through as a plain Python list so psycopg2 adapts it to
    a Postgres array, and must NOT wrap it in Json(...) the way
    `analytics`/`retrieval_metadata` are -- doing so would be a real
    type mismatch against the live column, not a style choice. This
    test inspects the actual executed SQL parameters (not just the SQL
    text) to prove the distinction is real, mirroring the
    _executed_sql()-based inspection pattern already used in
    test_ingestion_channel_snapshot.py.
    """
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_analytics_20260812_192340.json"
    _write_json(path, GOOD_ANALYTICS_SNAPSHOT)

    conn, cursor = _mock_connection(
        fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None, ("e73bc407-59a7-465a-96cb-85a00fcf9ac6",)]
    )

    ingest_channel_analytics(path, conn=conn, dry_run=False)

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "insert into youtube_evidence.channel_analytics_snapshots" in call.args[0].lower()
    )
    params = insert_call.args[1]

    # metrics_requested: plain list, passed through unwrapped.
    assert type(params["metrics_requested"]) is list
    assert params["metrics_requested"] == GOOD_ANALYTICS_SNAPSHOT["metrics_requested"]
    assert not isinstance(params["metrics_requested"], Json)

    # Contrast case: analytics/retrieval_metadata target jsonb columns
    # and must be Json(...)-wrapped -- proving the distinction is
    # deliberate, not an oversight that happens to leave one field bare.
    assert isinstance(params["analytics"], Json)
    assert isinstance(params["retrieval_metadata"], Json)
