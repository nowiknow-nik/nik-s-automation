import json
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.video_inventory_ingest import ingest_video_inventory
from ingestion.errors import IngestRejected


# Mirrors test_ingestion_channel_snapshot.py's fixtures and helpers
# exactly, adapted for video_inventory_snapshots. GOOD_VIDEO_INVENTORY_SNAPSHOT
# is the same real fixture (videos_20260812_192336.json) embedded in
# test_ingestion_video_mappings.py -- video_count == 0, videos == [] is
# the only real populated state that exists today (see that file's
# module-level note); this file exercises ingest_video_inventory()'s
# orchestration (transaction boundary, duplicate handling, FK
# resolution), not the per-item mapping logic, so the empty-videos real
# shape is sufficient here.

GOOD_VIDEO_INVENTORY_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_video_inventory",
    "snapshot_id": "27869aab-2c6d-440c-b24d-4e9500d30450",
    "generated_at_utc": "2026-08-12T19:23:36.514369+00:00",
    "source": "youtube_data_api",
    "api_version": "v3",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "retrieval_metadata": {
        "retrieved_resources": ["youtube#playlistItem", "youtube#video"],
        "pagination_completed": True,
        "errors": [],
        "warnings": [],
    },
    "uploads_playlist_id": "UUn4OmZFMasYBkmCx6Q2oUBQ",
    "video_count": 0,
    "videos": [],
}

GOOD_COLLECTION_RUN = {
    "schema_version": "1.0",
    "collection_type": "youtube_full_collection",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "collection_started_at_utc": "2026-08-12T19:23:30.436491+00:00",
    "collection_finished_at_utc": "2026-08-12T19:23:40.192417+00:00",
    "success": True,
    "components": [{"component": "video_inventory", "success": True}],
}


def _write_json(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")


def _mock_connection(fetchone_results):
    """
    A minimal stand-in for a psycopg2 connection, deep enough to
    support `with conn.cursor() as cur: cur.execute(...); cur.fetchone()`.
    fetchone_results is consumed in call order, matching the order
    ingest_video_inventory() / ensure_collection_run() issue queries in.
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


# --- ingest_video_inventory() ------------------------------------------

def test_ingest_pure_local_dry_run_with_no_connection(tmp_path):
    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    result = ingest_video_inventory(path, conn=None, dry_run=True)

    assert result.dry_run is True
    assert result.video_inventory_snapshot_inserted is False
    assert result.snapshot_id == "27869aab-2c6d-440c-b24d-4e9500d30450"


def test_ingest_dry_run_false_with_no_connection_raises(tmp_path):
    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    with pytest.raises(ValueError, match="requires a real database connection"):
        ingest_video_inventory(path, conn=None, dry_run=False)


def test_ingest_malformed_file_rejected_before_any_db_call(tmp_path):
    path = tmp_path / "videos_20260812_171438.json"
    _write_json(path, {"schema_version": "1.0", "videos": [], "video_count": 0})  # missing everything else

    conn, cursor = _mock_connection(fetchone_results=[])

    with pytest.raises(IngestRejected):
        ingest_video_inventory(path, conn=conn, dry_run=False)

    cursor.execute.assert_not_called()


def test_ingest_full_dry_run_with_live_connection_issues_no_writes(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    # collection_runs exists-check -> None (missing); video_inventory_snapshots exists-check -> None (missing)
    conn, cursor = _mock_connection(fetchone_results=[None, None])

    result = ingest_video_inventory(path, conn=conn, dry_run=True)

    assert result.dry_run is True
    assert result.video_inventory_snapshot_inserted is False
    assert result.collection_run_inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()
    conn.commit.assert_not_called()


def test_ingest_first_real_insert_inserts_parent_then_child_and_commits(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    # Order: collection_runs exists? -> None; insert collection_runs -> row;
    #        video_inventory_snapshots exists? -> None; insert video_inventory_snapshots -> row.
    conn, cursor = _mock_connection(
        fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None, ("27869aab-2c6d-440c-b24d-4e9500d30450",)]
    )

    result = ingest_video_inventory(path, conn=conn, dry_run=False)

    assert result.collection_run_inserted is True
    assert result.video_inventory_snapshot_inserted is True
    executed = _executed_sql(cursor)
    # Parent insert must happen before the child insert (design doc Sec 6.2/12).
    collection_idx = next(i for i, s in enumerate(executed) if "insert into youtube_evidence.collection_runs" in s.lower())
    snapshot_idx = next(i for i, s in enumerate(executed) if "insert into youtube_evidence.video_inventory_snapshots" in s.lower())
    assert collection_idx < snapshot_idx
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()


def test_ingest_duplicate_snapshot_is_a_clean_skip_not_an_error(tmp_path, monkeypatch):
    """Idempotency (design doc Sec 7): re-ingesting an already-present snapshot_id writes nothing."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    # collection_runs already exists (row 1); video_inventory_snapshots already exists (row 2).
    conn, cursor = _mock_connection(fetchone_results=[(1,), (1,)])

    result = ingest_video_inventory(path, conn=conn, dry_run=False)

    assert result.video_inventory_snapshot_inserted is False
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

    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    conn, cursor = _mock_connection(fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None])
    cursor.execute.side_effect = [None, None, None, RuntimeError("simulated insert failure")]

    with pytest.raises(RuntimeError, match="simulated insert failure"):
        ingest_video_inventory(path, conn=conn, dry_run=False)

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

    path = tmp_path / "videos_20260812_192336.json"
    _write_json(path, GOOD_VIDEO_INVENTORY_SNAPSHOT)

    conn, cursor = _mock_connection(fetchone_results=[None])  # collection_runs exists-check -> missing

    with pytest.raises(IngestRejected, match="no matching logs/collection_\\*.json"):
        ingest_video_inventory(path, conn=conn, dry_run=False)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
