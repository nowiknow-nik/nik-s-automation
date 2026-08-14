import json
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.channel_snapshot_ingest import (
    ensure_collection_run,
    find_collection_log,
    ingest_channel_snapshot,
)
from ingestion.errors import IngestRejected


GOOD_CHANNEL_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_channel",
    "snapshot_id": "a9594393-7572-4597-bb05-76082a9c993d",
    "generated_at_utc": "2026-08-12T19:23:34.033659+00:00",
    "source": "youtube_data_api",
    "api_version": "v3",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "retrieval_metadata": {"retrieved_resources": ["youtube#channel"], "pagination_completed": None, "errors": [], "warnings": []},
    "channel": {
        "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
        "title": "Now I Know NIK",
        "statistics": {"view_count": 0, "subscriber_count": 0, "video_count": 0, "hidden_subscriber_count": False},
    },
    "evidence": {"raw_response": {"kind": "youtube#channel", "id": "UCn4OmZFMasYBkmCx6Q2oUBQ"}},
}

GOOD_COLLECTION_RUN = {
    "schema_version": "1.0",
    "collection_type": "youtube_full_collection",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "collection_started_at_utc": "2026-08-12T19:23:30.436491+00:00",
    "collection_finished_at_utc": "2026-08-12T19:23:40.192417+00:00",
    "success": True,
    "components": [{"component": "channel_snapshot", "success": True}],
}


def _write_json(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")


def _mock_connection(fetchone_results):
    """
    A minimal stand-in for a psycopg2 connection, deep enough to
    support `with conn.cursor() as cur: cur.execute(...); cur.fetchone()`.
    fetchone_results is consumed in call order, matching the order
    ingest_channel_snapshot() / ensure_collection_run() issue queries in.
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


# --- find_collection_log() --------------------------------------------

def test_find_collection_log_matches_by_collection_id_not_filename(tmp_path):
    _write_json(tmp_path / "collection_20260812_173840.json", {"collection_id": "other-id"})
    _write_json(tmp_path / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    path, doc = find_collection_log("98321ba3-6bf1-4e50-aa8b-8a223ccd4862", logs_dir=tmp_path)

    assert path.name == "collection_20260812_192340.json"
    assert doc["collection_id"] == "98321ba3-6bf1-4e50-aa8b-8a223ccd4862"


def test_find_collection_log_returns_none_when_no_match(tmp_path):
    _write_json(tmp_path / "collection_20260812_173840.json", {"collection_id": "some-other-id"})

    path, doc = find_collection_log("98321ba3-6bf1-4e50-aa8b-8a223ccd4862", logs_dir=tmp_path)

    assert path is None
    assert doc is None


def test_find_collection_log_skips_unparseable_files(tmp_path):
    (tmp_path / "collection_broken.json").write_text("{not valid json", encoding="utf-8")
    _write_json(tmp_path / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    path, doc = find_collection_log("98321ba3-6bf1-4e50-aa8b-8a223ccd4862", logs_dir=tmp_path)

    assert path.name == "collection_20260812_192340.json"


# --- ensure_collection_run() -------------------------------------------

def test_ensure_collection_run_no_op_when_parent_already_exists(tmp_path):
    conn, cursor = _mock_connection(fetchone_results=[(1,)])  # exists check returns a row

    collection_id, inserted = ensure_collection_run(conn, "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", dry_run=False)

    assert inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()


def test_ensure_collection_run_raises_when_no_matching_log_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    conn, cursor = _mock_connection(fetchone_results=[None])  # doesn't exist

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", tmp_path / "logs")

    with pytest.raises(IngestRejected, match="no matching logs/collection_\\*.json"):
        ensure_collection_run(conn, "does-not-exist-anywhere", dry_run=False)


def test_ensure_collection_run_inserts_parent_when_missing(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    conn, cursor = _mock_connection(fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",)])

    collection_id, inserted = ensure_collection_run(conn, "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", dry_run=False)

    assert inserted is True
    executed = " ".join(_executed_sql(cursor)).lower()
    assert "insert into youtube_evidence.collection_runs" in executed


def test_ensure_collection_run_dry_run_never_inserts(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    conn, cursor = _mock_connection(fetchone_results=[None])  # only the exists-check is called

    collection_id, inserted = ensure_collection_run(conn, "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", dry_run=True)

    assert inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()


# --- ingest_channel_snapshot() ------------------------------------------

def test_ingest_pure_local_dry_run_with_no_connection(tmp_path):
    path = tmp_path / "channel_20260812_192334.json"
    _write_json(path, GOOD_CHANNEL_SNAPSHOT)

    result = ingest_channel_snapshot(path, conn=None, dry_run=True)

    assert result.dry_run is True
    assert result.channel_snapshot_inserted is False
    assert result.snapshot_id == "a9594393-7572-4597-bb05-76082a9c993d"


def test_ingest_dry_run_false_with_no_connection_raises(tmp_path):
    path = tmp_path / "channel_20260812_192334.json"
    _write_json(path, GOOD_CHANNEL_SNAPSHOT)

    with pytest.raises(ValueError, match="requires a real database connection"):
        ingest_channel_snapshot(path, conn=None, dry_run=False)


def test_ingest_malformed_file_rejected_before_any_db_call(tmp_path):
    path = tmp_path / "channel_20260812_171041.json"
    _write_json(path, {"schema_version": "1.0", "channel": {}})  # missing everything else

    conn, cursor = _mock_connection(fetchone_results=[])

    with pytest.raises(IngestRejected):
        ingest_channel_snapshot(path, conn=conn, dry_run=False)

    cursor.execute.assert_not_called()


def test_ingest_full_dry_run_with_live_connection_issues_no_writes(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_20260812_192334.json"
    _write_json(path, GOOD_CHANNEL_SNAPSHOT)

    # collection_runs exists-check -> None (missing); channel_snapshots exists-check -> None (missing)
    conn, cursor = _mock_connection(fetchone_results=[None, None])

    result = ingest_channel_snapshot(path, conn=conn, dry_run=True)

    assert result.dry_run is True
    assert result.channel_snapshot_inserted is False
    assert result.collection_run_inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()
    conn.commit.assert_not_called()


def test_ingest_first_real_insert_inserts_parent_then_child_and_commits(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_20260812_192334.json"
    _write_json(path, GOOD_CHANNEL_SNAPSHOT)

    # Order: collection_runs exists? -> None; insert collection_runs -> row;
    #        channel_snapshots exists? -> None; insert channel_snapshots -> row.
    conn, cursor = _mock_connection(
        fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None, ("a9594393-7572-4597-bb05-76082a9c993d",)]
    )

    result = ingest_channel_snapshot(path, conn=conn, dry_run=False)

    assert result.collection_run_inserted is True
    assert result.channel_snapshot_inserted is True
    executed = _executed_sql(cursor)
    # Parent insert must happen before the child insert (design doc Sec 6.2).
    collection_idx = next(i for i, s in enumerate(executed) if "insert into youtube_evidence.collection_runs" in s.lower())
    snapshot_idx = next(i for i, s in enumerate(executed) if "insert into youtube_evidence.channel_snapshots" in s.lower())
    assert collection_idx < snapshot_idx
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()


def test_ingest_duplicate_snapshot_is_a_clean_skip_not_an_error(tmp_path, monkeypatch):
    """Idempotency (design doc Sec 6.3): re-ingesting an already-present snapshot_id writes nothing."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_20260812_192334.json"
    _write_json(path, GOOD_CHANNEL_SNAPSHOT)

    # collection_runs already exists (row 1); channel_snapshots already exists (row 2).
    conn, cursor = _mock_connection(fetchone_results=[(1,), (1,)])

    result = ingest_channel_snapshot(path, conn=conn, dry_run=False)

    assert result.channel_snapshot_inserted is False
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

    import ingestion.channel_snapshot_ingest as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    path = tmp_path / "channel_20260812_192334.json"
    _write_json(path, GOOD_CHANNEL_SNAPSHOT)

    conn, cursor = _mock_connection(fetchone_results=[None, ("98321ba3-6bf1-4e50-aa8b-8a223ccd4862",), None])
    cursor.execute.side_effect = [None, None, None, RuntimeError("simulated insert failure")]

    with pytest.raises(RuntimeError, match="simulated insert failure"):
        ingest_channel_snapshot(path, conn=conn, dry_run=False)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
