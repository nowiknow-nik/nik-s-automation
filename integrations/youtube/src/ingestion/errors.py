class IngestRejected(Exception):
    """
    Raised when a source JSON file fails validation before any SQL is
    issued -- fail-closed, per
    NIK_YOUTUBE_B2_3_2_CHANNEL_SNAPSHOT_INGESTION_DESIGN.md Sec 6.6.
    Validation always runs to completion (every problem is collected,
    not just the first) before either passing or raising once with the
    full list -- never raised mid-write, and never caught and degraded
    to a partial insert.
    """


class IngestionNotConfigured(Exception):
    """
    Raised when no database credential is available. This is the
    expected, correct outcome in any environment that hasn't been
    deliberately configured with
    credentials/do_not_open_claude_supabase.json -- including this
    adapter's own test suite, and Claude's own sandbox, which must
    never hold this credential (design doc Sec 6.8 / Sec 7).
    """


class IngestionRoleMismatch(Exception):
    """
    Raised when a database connection succeeds but authenticates as a
    role other than the one this adapter requires (db.py's
    EXPECTED_ROLE). Fails closed rather than silently proceeding under
    an unexpected -- possibly more privileged -- role, e.g. if the
    credentials file were ever pointed at a leftover `postgres`
    connection string by mistake. Security refinement identified in
    NIK_YOUTUBE_B2_3_2_INDEPENDENT_REVIEW_REPORT.md Sec 8.
    """
