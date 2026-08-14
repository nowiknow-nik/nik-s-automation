from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROPOSAL_SQL = BASE_DIR / "NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql"


def _text():
    return PROPOSAL_SQL.read_text(encoding="utf-8")


def _executable_text():
    """
    The SQL file documents, in comments, exactly which privileges and
    tables were deliberately excluded (e.g. "Deliberately NOT included:
    BYPASSRLS ...", "no access at all to video_inventory_snapshots") --
    so a naive whole-file substring search for those words would
    false-fail on the comment that explains why they're absent. These
    checks only scan non-comment lines: what would actually be sent to
    Postgres if this file were ever executed. This file is never
    executed by this test suite, or by any code in this repo -- these
    are static regression checks only, guarding against a future
    accidental edit that reintroduces BYPASSRLS or drops one of the two
    required policies. See NIK_YOUTUBE_B2_3_2_INDEPENDENT_REVIEW_REPORT.md
    Sec 9.
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


def test_creates_exactly_one_role_named_youtube_ingest():
    text = _executable_text()
    assert "create role youtube_ingest" in text
    assert text.count("create role") == 1


def test_has_a_table_scoped_policy_on_both_required_tables():
    text = _executable_text()
    assert "on youtube_evidence.collection_runs" in text
    assert "on youtube_evidence.channel_snapshots" in text
    assert text.count("create policy") == 2


def test_policies_are_scoped_to_youtube_ingest_role_only():
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
        "video_inventory_snapshots",
        "channel_analytics_snapshots",
        "change_detection_events",
    ):
        assert out_of_scope not in text


def test_does_not_set_a_password():
    """
    CREATE ROLE below must grant LOGIN without a password -- password
    provisioning is a separate, founder-controlled step run directly
    against Supabase, never through Claude (Step 2a approval message).
    A future accidental edit that inlines a real or placeholder
    password back into this statement should fail this test.
    """
    assert "password" not in _executable_text()
