import json
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.collection_runs import ensure_collection_run, find_collection_log
from ingestion.errors import IngestRejected


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
    ensure_collection_run() issues queries in.
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
#
# These three tests were originally written in test_ingestion_channel_snapshot.py
# and moved here unchanged (B2.3.3 Decision 2 -- collection_runs.py extraction),
# since find_collection_log() has never been channel-snapshot-specific in
# anything but its former location. No assertions changed.

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
#
# These four tests were originally written in test_ingestion_channel_snapshot.py
# and moved here unchanged (B2.3.3 Decision 2). Only the monkeypatch
# target changed, from `ingestion.channel_snapshot_ingest as adapter`
# to `ingestion.collection_runs as adapter`, since LOGS_DIR now lives
# in this module -- no assertion changed.

def test_ensure_collection_run_no_op_when_parent_already_exists(tmp_path):
    conn, cursor = _mock_connection(fetchone_results=[(1,)])  # exists check returns a row

    collection_id, inserted = ensure_collection_run(conn, "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", dry_run=False)

    assert inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()


def test_ensure_collection_run_raises_when_no_matching_log_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    conn, cursor = _mock_connection(fetchone_results=[None])  # doesn't exist

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", tmp_path / "logs")

    with pytest.raises(IngestRejected, match="no matching logs/collection_\\*.json"):
        ensure_collection_run(conn, "does-not-exist-anywhere", dry_run=False)


def test_ensure_collection_run_inserts_parent_when_missing(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_json(logs_dir / "collection_20260812_192340.json", GOOD_COLLECTION_RUN)

    import ingestion.collection_runs as adapter
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

    import ingestion.collection_runs as adapter
    monkeypatch.setattr(adapter, "LOGS_DIR", logs_dir)

    conn, cursor = _mock_connection(fetchone_results=[None])  # only the exists-check is called

    collection_id, inserted = ensure_collection_run(conn, "98321ba3-6bf1-4e50-aa8b-8a223ccd4862", dry_run=True)

    assert inserted is False
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()
