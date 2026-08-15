import json
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest
from psycopg2.extras import Json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.change_detection_ingest import (
    ingest_change_detection_events,
    resolve_channel_snapshot_ids,
)
from ingestion.errors import IngestRejected


# Same real, B2.3.5 fixture embedded in test_ingestion_change_detection_mappings.py
# (data/snapshots/changes/change_20260815_130216.json) -- this file
# exercises ingest_change_detection_events()'s orchestration (the
# four-mode conn/dry_run matrix, transaction boundary, resolution, and
# idempotency), not the per-field mapping/validation logic, which
# test_ingestion_change_detection_mappings.py already covers in full.

GOOD_CHANGE_DETECTION_EVENTS = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_change_detection",
    "generated_at_utc": "2026-08-15T13:02:16.753692+00:00",
    "previous_snapshot": {
        "path": "data/snapshots/channel_20260812_173832.json",
        "generated_at_utc": "2026-08-12T17:38:32.852532+00:00",
    },
    "current_snapshot": {
        "path": "data/snapshots/channel_20260812_192334.json",
        "generated_at_utc": "2026-08-12T19:23:34.033659+00:00",
    },
    "entity_type": "channel",
    "changes": [
        {
            "entity_type": "channel",
            "entity_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "metric": "subscriber_count",
            "previous_value": 0,
            "current_value": 0,
            "change_type": "UNCHANGED",
            "absolute_change": 0,
            "percentage_change": None,
            "evidence_class": "DERIVED",
        },
        {
            "entity_type": "channel",
            "entity_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "metric": "view_count",
            "previous_value": 0,
            "current_value": 0,
            "change_type": "UNCHANGED",
            "absolute_change": 0,
            "percentage_change": None,
            "evidence_class": "DERIVED",
        },
        {
            "entity_type": "channel",
            "entity_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "metric": "video_count",
            "previous_value": 0,
            "current_value": 0,
            "change_type": "UNCHANGED",
            "absolute_change": 0,
            "percentage_change": None,
            "evidence_class": "DERIVED",
        },
    ],
}


def _write_json(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")


def _mock_connection(fetchone_results):
    """
    Mirrors test_ingestion_analytics.py's own helper exactly: a minimal
    stand-in for a psycopg2 connection, deep enough to support
    `with conn.cursor() as cur: cur.execute(...); cur.fetchone()`.
    fetchone_results is consumed in call order, matching the order
    ingest_change_detection_events() issues queries in: resolve
    previous_snapshot_id, resolve current_snapshot_id, then (live mode
    only) one insert per mapped row.
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


def _executed_params(cursor):
    return [call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1]


# --- ingest_change_detection_events() -- conn=None modes -----------------

def test_structural_dry_run_with_no_connection_does_not_attempt_resolution(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    result = ingest_change_detection_events(path, conn=None, dry_run=True)

    assert result.dry_run is True
    assert result.rows_mapped == 3
    assert result.rows_inserted == 0
    assert result.previous_snapshot_resolved is False
    assert result.current_snapshot_resolved is False
    assert result.previous_snapshot_id is None
    assert result.current_snapshot_id is None
    assert result.source_file.endswith("change_20260815_130216.json")


def test_dry_run_false_with_no_connection_raises(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    with pytest.raises(ValueError, match="requires a real database connection"):
        ingest_change_detection_events(path, conn=None, dry_run=False)


def test_malformed_file_rejected_before_any_db_call(tmp_path):
    path = tmp_path / "change_broken.json"
    _write_json(path, {"schema_version": "1.0"})  # missing everything else

    conn, cursor = _mock_connection(fetchone_results=[])

    with pytest.raises(IngestRejected):
        ingest_change_detection_events(path, conn=conn, dry_run=False)

    cursor.execute.assert_not_called()


# --- ingest_change_detection_events() -- resolution dry run (real conn, dry_run=True) ---

def test_resolution_dry_run_runs_selects_but_issues_no_insert_and_no_commit(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[None, ("current-snap-id-0000-000000000000",)]
    )

    result = ingest_change_detection_events(path, conn=conn, dry_run=True)

    assert result.dry_run is True
    assert result.rows_inserted == 0
    assert "insert" not in " ".join(_executed_sql(cursor)).lower()
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


def test_resolution_dry_run_reports_resolved_true_even_when_both_sides_null():
    """
    previous_snapshot_resolved/current_snapshot_resolved must be True
    (attempted) even when the lookup found nothing -- not merely that
    the IDs are None, which could also be masking a real
    resolve-and-not-found. This is the exact distinction design doc
    Sec 7's test strategy calls out by name.
    """
    conn, cursor = _mock_connection(fetchone_results=[None, None])

    previous_id, current_id = resolve_channel_snapshot_ids(
        conn,
        GOOD_CHANGE_DETECTION_EVENTS["previous_snapshot"],
        GOOD_CHANGE_DETECTION_EVENTS["current_snapshot"],
        "UCn4OmZFMasYBkmCx6Q2oUBQ",
    )
    assert previous_id is None
    assert current_id is None
    # Two real SELECTs were issued -- both attempted, both genuinely
    # returned zero rows (fail-open), not skipped.
    assert cursor.execute.call_count == 2


def test_resolution_dry_run_demonstrates_one_resolved_one_null_fallback(tmp_path):
    """
    The real B2.3.5 fixture scenario (design doc Decision 7): previous
    resolves to NULL (legacy, never-ingested snapshot), current
    resolves successfully (the one snapshot actually in
    channel_snapshots).
    """
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[None, ("11111111-1111-1111-1111-111111111111",)]
    )

    result = ingest_change_detection_events(path, conn=conn, dry_run=True)

    assert result.previous_snapshot_resolved is True
    assert result.previous_snapshot_id is None
    assert result.current_snapshot_resolved is True
    assert result.current_snapshot_id == "11111111-1111-1111-1111-111111111111"


def test_resolution_uses_first_changes_entry_entity_id_as_channel_id(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(fetchone_results=[None, None])

    ingest_change_detection_events(path, conn=conn, dry_run=True)

    params = _executed_params(cursor)
    assert params[0]["channel_id"] == "UCn4OmZFMasYBkmCx6Q2oUBQ"
    assert params[1]["channel_id"] == "UCn4OmZFMasYBkmCx6Q2oUBQ"
    assert params[0]["generated_at_utc"] == GOOD_CHANGE_DETECTION_EVENTS["previous_snapshot"]["generated_at_utc"]
    assert params[1]["generated_at_utc"] == GOOD_CHANGE_DETECTION_EVENTS["current_snapshot"]["generated_at_utc"]


# --- ingest_change_detection_events() -- live ingestion (real conn, dry_run=False) ---

def test_live_ingestion_inserts_all_rows_and_commits(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    # Order: resolve previous -> None; resolve current -> row; then 3 inserts, all succeed.
    conn, cursor = _mock_connection(
        fetchone_results=[
            None,
            ("11111111-1111-1111-1111-111111111111",),
            ("event-1",),
            ("event-2",),
            ("event-3",),
        ]
    )

    result = ingest_change_detection_events(path, conn=conn, dry_run=False)

    assert result.rows_mapped == 3
    assert result.rows_inserted == 3
    assert result.previous_snapshot_id is None
    assert result.current_snapshot_id == "11111111-1111-1111-1111-111111111111"
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()

    executed = _executed_sql(cursor)
    insert_calls = [s for s in executed if "insert into youtube_evidence.change_detection_events" in s.lower()]
    assert len(insert_calls) == 3


def test_live_ingestion_every_inserted_row_shares_one_detection_run_id(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[None, None, ("event-1",), ("event-2",), ("event-3",)]
    )

    result = ingest_change_detection_events(path, conn=conn, dry_run=False)

    insert_params = [
        call.args[1] for call in cursor.execute.call_args_list
        if "insert into youtube_evidence.change_detection_events" in call.args[0].lower()
    ]
    run_ids = {p["detection_run_id"] for p in insert_params}
    assert len(run_ids) == 1
    assert run_ids.pop() == result.detection_run_id


def test_live_ingestion_applies_resolved_snapshot_ids_to_every_row(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[
            ("prev-id-0000-0000-0000-000000000000",),
            ("curr-id-0000-0000-0000-000000000000",),
            ("event-1",),
            ("event-2",),
            ("event-3",),
        ]
    )

    ingest_change_detection_events(path, conn=conn, dry_run=False)

    insert_params = [
        call.args[1] for call in cursor.execute.call_args_list
        if "insert into youtube_evidence.change_detection_events" in call.args[0].lower()
    ]
    for params in insert_params:
        assert params["previous_snapshot_id"] == "prev-id-0000-0000-0000-000000000000"
        assert params["current_snapshot_id"] == "curr-id-0000-0000-0000-000000000000"


def test_live_ingestion_json_wraps_snapshot_source_columns(tmp_path):
    """
    previous_snapshot_source/current_snapshot_source target jsonb
    columns and must be Json(...)-wrapped -- the opposite distinction
    from metrics_requested in analytics_ingest.py (which must NOT be
    wrapped because it targets a native text[] column). This table has
    no native-array columns at all, so both snapshot_source columns are
    wrapped, with no exception.
    """
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[None, None, ("event-1",), ("event-2",), ("event-3",)]
    )

    ingest_change_detection_events(path, conn=conn, dry_run=False)

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "insert into youtube_evidence.change_detection_events" in call.args[0].lower()
    )
    params = insert_call.args[1]
    assert isinstance(params["previous_snapshot_source"], Json)
    assert isinstance(params["current_snapshot_source"], Json)


def test_live_ingestion_uses_on_conflict_source_file_metric(tmp_path):
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[None, None, ("event-1",), ("event-2",), ("event-3",)]
    )

    ingest_change_detection_events(path, conn=conn, dry_run=False)

    executed = _executed_sql(cursor)
    insert_sql = next(s for s in executed if "insert into youtube_evidence.change_detection_events" in s.lower())
    assert "on conflict (source_file, metric) do nothing" in insert_sql.lower()


# --- Idempotency (design doc Sec 5.6/Sec 7) -------------------------------

def test_idempotent_rerun_produces_zero_new_inserts(tmp_path):
    """
    Mock-level proof of idempotency: on a re-ingestion of the same file,
    every row's (source_file, metric) pair already exists, so
    ON CONFLICT ... DO NOTHING returns no row for each insert attempt --
    modeled here by every insert's fetchone() returning None.
    """
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(
        fetchone_results=[
            ("prev-id-0000-0000-0000-000000000000",),
            ("curr-id-0000-0000-0000-000000000000",),
            None,  # insert row 1 -- conflict, skipped
            None,  # insert row 2 -- conflict, skipped
            None,  # insert row 3 -- conflict, skipped
        ]
    )

    result = ingest_change_detection_events(path, conn=conn, dry_run=False)

    assert result.rows_inserted == 0
    conn.commit.assert_called_once()  # still commits cleanly -- a no-op skip, not an error
    conn.rollback.assert_not_called()


def test_idempotent_rerun_still_generates_a_fresh_detection_run_id_that_is_simply_never_persisted(tmp_path):
    """
    Decision 6, made concrete: a second attempt's differently-valued
    detection_run_id is real (generated fresh, per-call) but never
    actually lands in the database, because every row it would have
    produced collides on (source_file, metric) and is skipped. Two
    separate calls must still produce two different detection_run_id
    values at the Python level, even though neither run's rows survive
    the second time.
    """
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn1, cursor1 = _mock_connection(
        fetchone_results=[("p",), ("c",), ("event-1",), ("event-2",), ("event-3",)]
    )
    result1 = ingest_change_detection_events(path, conn=conn1, dry_run=False)

    conn2, cursor2 = _mock_connection(fetchone_results=[("p",), ("c",), None, None, None])
    result2 = ingest_change_detection_events(path, conn=conn2, dry_run=False)

    assert result1.detection_run_id != result2.detection_run_id
    assert result1.rows_inserted == 3
    assert result2.rows_inserted == 0


# --- Failure handling ------------------------------------------------------

def test_rolls_back_on_failure_during_insert(tmp_path):
    """
    If an insert blows up partway through a file's N rows, the
    transaction must roll back -- a failed run must never leave a
    partial set of rows for one comparison run committed.
    """
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(fetchone_results=[None, None, ("event-1",)])
    cursor.execute.side_effect = [None, None, None, RuntimeError("simulated insert failure")]

    with pytest.raises(RuntimeError, match="simulated insert failure"):
        ingest_change_detection_events(path, conn=conn, dry_run=False)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_resolution_dry_run_does_not_rollback_on_failure(tmp_path):
    """
    A resolution-dry-run failure never wrote anything, so it has
    nothing to roll back -- mirrors the conn/dry_run guard used
    throughout every prior adapter's except block.
    """
    path = tmp_path / "change_20260815_130216.json"
    _write_json(path, GOOD_CHANGE_DETECTION_EVENTS)

    conn, cursor = _mock_connection(fetchone_results=[])
    cursor.fetchone.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        ingest_change_detection_events(path, conn=conn, dry_run=True)

    conn.rollback.assert_not_called()
    conn.commit.assert_not_called()
