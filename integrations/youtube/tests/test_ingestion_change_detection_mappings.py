from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.errors import IngestRejected
from ingestion.mappings import (
    map_change_detection_events,
    validate_change_detection_events,
)


# ---------------------------------------------------------------------
# Real fixture, embedded verbatim -- not synthesized. This is the fresh
# fixture generated for B2.3.5 per design doc Decision 7/Sec 8
# (data/snapshots/changes/change_20260815_130216.json), produced by
# running change_detection.py again after B2.3.4 closed so that the
# comparison would land on channel_20260812_192334.json -- the one
# channel snapshot actually present in youtube_evidence.channel_snapshots
# -- as the CURRENT side, alongside channel_20260812_173832.json (a
# legacy, never-ingested snapshot) as the PREVIOUS side. Unlike the
# original fixture (change_20260812_175040.json, which resolves both
# sides to NULL), this fixture is the one real, live-generated document
# that can demonstrate both the successful-resolution and the
# NULL-fallback path in a single file, once ingested against a real
# connection (test_ingestion_change_detection.py exercises this against
# a mocked connection; a live confirmation happens only at the actual
# live-ingestion gate, not here).
# ---------------------------------------------------------------------

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


def _write_doc(**overrides):
    return {**GOOD_CHANGE_DETECTION_EVENTS, **overrides}


# --- validate_change_detection_events() -- envelope-level ---------------

def test_good_change_detection_events_passes_validation():
    validate_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS)  # must not raise


def test_missing_top_level_field_named_in_rejection():
    for field in ("schema_version", "snapshot_type", "generated_at_utc", "entity_type"):
        doc = {k: v for k, v in GOOD_CHANGE_DETECTION_EVENTS.items() if k != field}
        with pytest.raises(IngestRejected, match=field):
            validate_change_detection_events(doc)


def test_wrong_snapshot_type_rejected():
    doc = _write_doc(snapshot_type="youtube_channel")
    with pytest.raises(IngestRejected, match="snapshot_type must be 'youtube_change_detection'"):
        validate_change_detection_events(doc)


def test_unparseable_generated_at_utc_rejected():
    doc = _write_doc(generated_at_utc="not-a-timestamp")
    with pytest.raises(IngestRejected, match="does not parse as a timestamp"):
        validate_change_detection_events(doc)


# --- validate_change_detection_events() -- previous_snapshot/current_snapshot ---

def test_missing_previous_snapshot_rejected():
    doc = {k: v for k, v in GOOD_CHANGE_DETECTION_EVENTS.items() if k != "previous_snapshot"}
    with pytest.raises(IngestRejected, match="'previous_snapshot'"):
        validate_change_detection_events(doc)


def test_previous_snapshot_not_an_object_rejected():
    doc = _write_doc(previous_snapshot="data/snapshots/channel_x.json")
    with pytest.raises(IngestRejected, match="'previous_snapshot' \\(must be an object\\)"):
        validate_change_detection_events(doc)


def test_previous_snapshot_missing_path_rejected():
    doc = _write_doc(previous_snapshot={"generated_at_utc": "2026-08-12T17:38:32.852532+00:00"})
    with pytest.raises(IngestRejected, match="'previous_snapshot.path'"):
        validate_change_detection_events(doc)


def test_current_snapshot_missing_generated_at_utc_rejected():
    doc = _write_doc(current_snapshot={"path": "data/snapshots/channel_x.json"})
    with pytest.raises(IngestRejected, match="'current_snapshot.generated_at_utc'"):
        validate_change_detection_events(doc)


def test_current_snapshot_unparseable_generated_at_utc_rejected():
    doc = _write_doc(current_snapshot={"path": "x.json", "generated_at_utc": "not-a-timestamp"})
    with pytest.raises(IngestRejected, match="current_snapshot.generated_at_utc does not parse"):
        validate_change_detection_events(doc)


# --- validate_change_detection_events() -- changes[] (Decision 4) -------

def test_missing_changes_key_rejected():
    doc = {k: v for k, v in GOOD_CHANGE_DETECTION_EVENTS.items() if k != "changes"}
    with pytest.raises(IngestRejected, match="'changes' \\(must be an array\\)"):
        validate_change_detection_events(doc)


def test_changes_not_a_list_rejected():
    doc = _write_doc(changes={"metric": "subscriber_count"})
    with pytest.raises(IngestRejected, match="'changes' \\(must be an array\\)"):
        validate_change_detection_events(doc)


def test_empty_changes_array_rejected():
    """
    Decision 4: a present-but-empty changes array is a validation
    failure, not a valid zero-row ingestion. compare_channel() always
    produces exactly three entries today, so this path is unreachable
    from real output -- this is a defensive, fail-closed rule for
    hypothetical malformed input.
    """
    doc = _write_doc(changes=[])
    with pytest.raises(IngestRejected, match="'changes' must not be empty"):
        validate_change_detection_events(doc)


def test_changes_entry_not_an_object_rejected():
    doc = _write_doc(changes=["subscriber_count"])
    with pytest.raises(IngestRejected, match=r"changes\[0\] must be an object"):
        validate_change_detection_events(doc)


def test_changes_entry_missing_required_field_named():
    doc = _write_doc(changes=[{
        "entity_type": "channel",
        "metric": "subscriber_count",
        "change_type": "UNCHANGED",
        "evidence_class": "DERIVED",
        # entity_id deliberately omitted
    }])
    with pytest.raises(IngestRejected, match=r"changes\[0\] missing required field: 'entity_id'"):
        validate_change_detection_events(doc)


def test_changes_entry_invalid_change_type_rejected():
    doc = _write_doc(changes=[{**GOOD_CHANGE_DETECTION_EVENTS["changes"][0], "change_type": "MAYBE"}])
    with pytest.raises(IngestRejected, match="change_type must be one of"):
        validate_change_detection_events(doc)


def test_changes_entry_invalid_evidence_class_rejected():
    doc = _write_doc(changes=[{**GOOD_CHANGE_DETECTION_EVENTS["changes"][0], "evidence_class": "GUESSED"}])
    with pytest.raises(IngestRejected, match="evidence_class must be one of"):
        validate_change_detection_events(doc)


@pytest.mark.parametrize("change_type", ["UNCHANGED", "CHANGED", "UNAVAILABLE"])
def test_every_valid_change_type_is_accepted(change_type):
    doc = _write_doc(changes=[{**GOOD_CHANGE_DETECTION_EVENTS["changes"][0], "change_type": change_type}])
    validate_change_detection_events(doc)  # must not raise


@pytest.mark.parametrize("evidence_class", ["OBSERVED", "DERIVED", "INTERPRETATION", "ASSUMPTION"])
def test_every_valid_evidence_class_is_accepted(evidence_class):
    doc = _write_doc(changes=[{**GOOD_CHANGE_DETECTION_EVENTS["changes"][0], "evidence_class": evidence_class}])
    validate_change_detection_events(doc)  # must not raise


def test_previous_value_and_friends_may_be_null():
    """
    previous_value/current_value/absolute_change/percentage_change are
    legitimately nullable numeric columns -- exactly what UNAVAILABLE/
    zero-baseline comparisons look like. None of the four is required.
    """
    doc = _write_doc(changes=[{
        "entity_type": "channel",
        "entity_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
        "metric": "subscriber_count",
        "previous_value": None,
        "current_value": None,
        "change_type": "UNAVAILABLE",
        "absolute_change": None,
        "percentage_change": None,
        "evidence_class": "DERIVED",
    }])
    validate_change_detection_events(doc)  # must not raise


def test_previous_value_and_friends_entirely_absent_is_also_valid():
    """Same as above, but the four keys are missing entirely, not just null -- also valid."""
    doc = _write_doc(changes=[{
        "entity_type": "channel",
        "entity_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
        "metric": "subscriber_count",
        "change_type": "UNAVAILABLE",
        "evidence_class": "DERIVED",
    }])
    validate_change_detection_events(doc)  # must not raise


# --- validate_change_detection_events() -- Decision 5 (single entity) ---

def test_multiple_entities_in_changes_rejected():
    doc = _write_doc(changes=[
        GOOD_CHANGE_DETECTION_EVENTS["changes"][0],
        {**GOOD_CHANGE_DETECTION_EVENTS["changes"][1], "entity_id": "UCdifferentChannelId00000"},
    ])
    with pytest.raises(IngestRejected, match="changes\\[\\] entries reference more than one entity"):
        validate_change_detection_events(doc)


def test_multiple_entity_types_in_changes_rejected():
    doc = _write_doc(changes=[
        GOOD_CHANGE_DETECTION_EVENTS["changes"][0],
        {**GOOD_CHANGE_DETECTION_EVENTS["changes"][1], "entity_type": "video"},
    ])
    with pytest.raises(IngestRejected, match="changes\\[\\] entries reference more than one entity"):
        validate_change_detection_events(doc)


def test_three_entries_same_entity_is_valid():
    """The real shape change_detection.py actually produces: 3 entries, one entity."""
    validate_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS)  # must not raise


# --- map_change_detection_events() ---------------------------------------

def test_map_returns_a_list_with_one_row_per_change_entry():
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    assert isinstance(rows, list)
    assert len(rows) == 3


def test_map_row_fields_match_source_change_entry():
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    row = rows[1]  # view_count
    entry = GOOD_CHANGE_DETECTION_EVENTS["changes"][1]

    assert row["entity_type"] == entry["entity_type"]
    assert row["entity_id"] == entry["entity_id"]
    assert row["metric"] == "view_count"
    assert row["previous_value"] == entry["previous_value"]
    assert row["current_value"] == entry["current_value"]
    assert row["change_type"] == entry["change_type"]
    assert row["absolute_change"] == entry["absolute_change"]
    assert row["percentage_change"] == entry["percentage_change"]
    assert row["evidence_class"] == entry["evidence_class"]


def test_map_shares_schema_version_generated_at_utc_and_source_file_across_all_rows():
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="data/snapshots/changes/x.json")
    for row in rows:
        assert row["schema_version"] == "1.0"
        assert row["generated_at_utc"] == "2026-08-15T13:02:16.753692+00:00"
        assert row["source_file"] == "data/snapshots/changes/x.json"


def test_map_generated_at_utc_is_the_runs_own_timestamp_not_a_snapshots():
    """
    The mapped generated_at_utc must be the comparison run's own
    top-level timestamp -- neither previous_snapshot's nor
    current_snapshot's own generated_at_utc.
    """
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    for row in rows:
        assert row["generated_at_utc"] == GOOD_CHANGE_DETECTION_EVENTS["generated_at_utc"]
        assert row["generated_at_utc"] != GOOD_CHANGE_DETECTION_EVENTS["previous_snapshot"]["generated_at_utc"]
        assert row["generated_at_utc"] != GOOD_CHANGE_DETECTION_EVENTS["current_snapshot"]["generated_at_utc"]


def test_map_detection_run_id_identical_across_every_row_from_one_call():
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    run_ids = {row["detection_run_id"] for row in rows}
    assert len(run_ids) == 1


def test_map_detection_run_id_differs_across_two_separate_calls():
    """
    Decision 6: detection_run_id is a plain, non-deterministic
    uuid.uuid4() generated fresh on every call -- it must NOT be
    content-derived or stable across repeated ingestion attempts of the
    same file. Idempotency lives entirely in (source_file, metric), not
    here.
    """
    first = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    second = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    assert first[0]["detection_run_id"] != second[0]["detection_run_id"]


def test_map_preserves_previous_and_current_snapshot_source_verbatim():
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    for row in rows:
        assert row["previous_snapshot_source"] == GOOD_CHANGE_DETECTION_EVENTS["previous_snapshot"]
        assert row["current_snapshot_source"] == GOOD_CHANGE_DETECTION_EVENTS["current_snapshot"]
        assert row["previous_snapshot_source"]["path"] == "data/snapshots/channel_20260812_173832.json"
        assert row["current_snapshot_source"]["path"] == "data/snapshots/channel_20260812_192334.json"


def test_map_output_never_includes_snapshot_id_keys():
    """
    Structural proof that resolution isn't folded into this pure
    function -- previous_snapshot_id/current_snapshot_id are computed
    separately, by resolve_channel_snapshot_ids() in
    change_detection_ingest.py, and layered on by the ingestion adapter,
    not this mapper (design doc Sec 5.2/5.3).
    """
    rows = map_change_detection_events(GOOD_CHANGE_DETECTION_EVENTS, source_file="x.json")
    for row in rows:
        assert "previous_snapshot_id" not in row
        assert "current_snapshot_id" not in row
