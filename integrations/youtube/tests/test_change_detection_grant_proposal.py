from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROPOSAL_SQL = BASE_DIR / "NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_GRANT_PROPOSAL.sql"


def _text():
    return PROPOSAL_SQL.read_text(encoding="utf-8")


def _executable_text():
    """
    Mirrors test_channel_analytics_grant_proposal.py's own helper
    exactly, and for the same reason: this file's comments deliberately
    name the tables/migrations it does NOT touch (e.g. "Does NOT grant
    anything on channel_snapshots"), so a naive whole-file substring
    search would false-fail on the very comment explaining their
    absence. These checks only scan non-comment lines -- what would
    actually be sent to Postgres if this file were ever executed. This
    file is never executed by this test suite, or by any code in this
    repo -- these are static regression checks only, guarding against a
    future accidental edit that widens this proposal's scope beyond
    design doc Sec 6 ("Migration B").
    """
    lines = [
        line for line in _text().splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    return " ".join(lines).lower()


def test_proposal_file_exists():
    assert PROPOSAL_SQL.exists()


def test_does_not_grant_bypassrls():
    assert "bypassrls" not in _executable_text()


def test_does_not_grant_superuser_or_createrole_or_createdb():
    text = _executable_text()
    for forbidden in ("superuser", "createrole", "createdb"):
        assert forbidden not in text, f"proposal must not grant {forbidden}"


def test_does_not_create_a_new_role():
    """
    This file EXTENDS the existing youtube_ingest role -- it must never
    create a new one. Mirrors test_channel_analytics_grant_proposal.py's
    identically-named check for the B2.3.4 file.
    """
    assert "create role" not in _executable_text()


def test_has_exactly_one_policy_scoped_to_change_detection_events():
    text = _executable_text()
    assert "on youtube_evidence.change_detection_events" in text
    assert text.count("create policy") == 1


def test_policy_is_scoped_to_youtube_ingest_role_only():
    text = _executable_text()
    for statement in text.split("create policy")[1:]:
        assert "to youtube_ingest" in statement.split(";")[0]


def test_does_not_grant_update_or_delete():
    for line in _text().splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("--"):
            continue
        if stripped.lower().startswith("grant ") and "usage on schema" not in stripped.lower():
            assert "update" not in stripped.lower()
            assert "delete" not in stripped.lower()


def test_does_not_touch_out_of_scope_tables():
    text = _executable_text()
    for out_of_scope in (
        "channel_snapshots",
        "video_inventory_snapshots",
        "collection_runs",
        "channel_analytics_snapshots",
    ):
        assert out_of_scope not in text, f"proposal must stay scoped away from {out_of_scope}"


def test_does_not_set_a_password():
    """
    This file must never set or reference a password -- it doesn't
    create the role at all (see test_does_not_create_a_new_role), and
    password provisioning was already a separate, founder-controlled
    step for the B2.3.2 file; this file has even less reason to touch
    it.
    """
    assert "password" not in _executable_text()


def test_does_not_grant_schema_usage_again():
    """
    Schema-level USAGE on youtube_evidence was already granted to
    youtube_ingest by the B2.3.2 migration and applies schema-wide --
    this file only needs the new table-scoped grant/policy, not a
    redundant schema-level grant.
    """
    assert "grant usage on schema" not in _executable_text()


def test_does_not_grant_anything_on_channel_snapshots():
    """
    youtube_ingest already holds SELECT on channel_snapshots (granted
    at B2.3.2) -- the resolution query this table's ingestion needs
    (resolve_channel_snapshot_ids() in change_detection_ingest.py) is
    already covered. This file must not re-grant or extend that.
    """
    text = _executable_text()
    assert "channel_snapshots" not in text
