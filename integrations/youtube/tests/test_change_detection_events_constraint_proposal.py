from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROPOSAL_SQL = BASE_DIR / "NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_CONSTRAINT_PROPOSAL.sql"


def _text():
    return PROPOSAL_SQL.read_text(encoding="utf-8")


def _executable_text():
    """
    Mirrors test_channel_analytics_grant_proposal.py's own helper
    exactly, and for the same reason: this file's comments deliberately
    name the tables it does NOT touch (e.g. "Does NOT touch
    channel_snapshots, video_inventory_snapshots, ..."), so a naive
    whole-file substring search would false-fail on the very comment
    explaining their absence. These checks only scan non-comment lines
    -- what would actually be sent to Postgres if this file were ever
    executed. This file is never executed by this test suite, or by any
    code in this repo -- these are static regression checks only,
    guarding against a future accidental edit that widens this
    migration's scope beyond design doc Sec 6 ("Migration A").
    """
    lines = [
        line for line in _text().splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    return " ".join(lines).lower()


def test_proposal_file_exists():
    assert PROPOSAL_SQL.exists()


def test_sets_source_file_not_null():
    assert "alter column source_file set not null" in _executable_text()


def test_adds_unique_constraint_on_source_file_and_metric():
    assert "unique (source_file, metric)" in _executable_text()


def test_constraint_is_named_and_scoped_to_change_detection_events():
    text = _executable_text()
    assert "add constraint change_detection_events_source_file_metric_key" in text


def test_only_alters_source_file_column():
    """
    Migration A touches exactly one column via ALTER COLUMN --
    source_file. 'metric' appears only as the second half of the
    UNIQUE pair below, never itself altered.
    """
    text = _executable_text()
    assert text.count("alter column") == 1
    assert "alter column source_file" in text


def test_only_touches_change_detection_events_table():
    text = _executable_text()
    assert text.count("alter table") == 2
    for statement in text.split("alter table")[1:]:
        assert statement.strip().startswith("youtube_evidence.change_detection_events")


def test_does_not_touch_out_of_scope_tables():
    text = _executable_text()
    for out_of_scope in (
        "channel_snapshots",
        "video_inventory_snapshots",
        "collection_runs",
        "channel_analytics_snapshots",
    ):
        assert out_of_scope not in text, f"proposal must stay scoped away from {out_of_scope}"


def test_does_not_grant_or_create_anything():
    """
    This file is schema-structure only (Migration A) -- grants/policies
    are a separate file (Migration B,
    NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_GRANT_PROPOSAL.sql), kept apart
    per the design doc's Decision 2.
    """
    text = _executable_text()
    for forbidden in ("grant ", "create policy", "create role"):
        assert forbidden not in text


def test_does_not_drop_or_delete_anything():
    text = _executable_text()
    for forbidden in ("drop ", "delete from", "truncate"):
        assert forbidden not in text


def test_does_not_set_a_password():
    assert "password" not in _executable_text()
