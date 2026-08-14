"""
Direct-Postgres connection helper for the youtube_evidence ingestion
adapters (B2.3.2+).

Deliberately NOT the Supabase client library: youtube_evidence is not
in Exposed Schemas (NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec
6.4), so PostgREST has no route into it regardless of which API key is
presented -- see NIK_YOUTUBE_B2_3_2_CHANNEL_SNAPSHOT_INGESTION_DESIGN.md
Sec 7. This module opens a direct psycopg2 connection instead,
authenticating as a dedicated, least-privilege database role -- not
the `postgres` superuser used to run migrations.

The credential is never read, generated, or held by Claude. It lives in
a local, gitignored file this module reads at call time -- the same
"Claude does not open this" pattern already used for the YouTube OAuth
client secret in credentials/do_not_open_claude.json (see src/auth.py).
That file does not exist yet as of B2.3.2's implementation pass: the
youtube_ingest role it would authenticate as has been designed but not
created (a separate, explicit, founder-approved migration -- see the
design doc Sec 9, item 3). Until it exists, get_connection() raises
IngestionNotConfigured, on purpose.

Security refinement (independent review Sec 8): a connection string
alone isn't proof of which role it actually authenticates as -- a
credentials file that was ever accidentally pointed at a leftover,
more-privileged connection string (e.g. for `postgres`) would otherwise
be accepted silently. get_connection() checks `select current_user`
immediately after connecting and fails closed -- closing the connection
and raising IngestionRoleMismatch -- if it isn't exactly EXPECTED_ROLE.
"""

import json
from pathlib import Path

import psycopg2

from .errors import IngestionNotConfigured, IngestionRoleMismatch


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_DIR = BASE_DIR / "credentials"

# Expected shape:
#   {"db_url": "postgresql://youtube_ingest.<project-ref>:<password>@<pooler-host>:5432/postgres"}
#
# Created by hand, outside of any Claude session, once the youtube_ingest
# role actually exists. Never generated or written by this module or by
# Claude -- see the module docstring above.
DB_CREDENTIALS_FILE = CREDENTIALS_DIR / "do_not_open_claude_supabase.json"

# The only role this adapter is ever expected to authenticate as -- see
# NIK_YOUTUBE_B2_3_2_YOUTUBE_INGEST_ROLE_PROPOSAL.sql. get_connection()
# fails closed (IngestionRoleMismatch) if a connection ever
# authenticates as anything else.
EXPECTED_ROLE = "youtube_ingest"


def get_connection():
    """
    Opens and returns a new psycopg2 connection using the locally-held
    youtube_ingest credential.

    Raises IngestionNotConfigured -- clearly, fail-closed -- if the
    credentials file doesn't exist or is missing its db_url, rather
    than falling back to any default, broader-privilege credential.
    There is no fallback path in this function to the `postgres` role
    on purpose.

    Raises IngestionRoleMismatch -- also fail-closed -- if the
    connection succeeds but authenticates as any role other than
    EXPECTED_ROLE. The connection is closed before raising; the caller
    never receives a connection authenticated as the wrong role.
    """
    if not DB_CREDENTIALS_FILE.exists():
        raise IngestionNotConfigured(
            f"No database credential found at {DB_CREDENTIALS_FILE}. "
            "This is expected until the youtube_ingest role is created "
            "and its connection string is placed there by hand -- see "
            "NIK_YOUTUBE_B2_3_2_CHANNEL_SNAPSHOT_INGESTION_DESIGN.md Sec 9, item 3."
        )

    with DB_CREDENTIALS_FILE.open("r", encoding="utf-8") as file:
        config = json.load(file)

    db_url = config.get("db_url")
    if not db_url:
        raise IngestionNotConfigured(
            f"{DB_CREDENTIALS_FILE} exists but has no 'db_url' key."
        )

    conn = psycopg2.connect(db_url)
    _assert_expected_role(conn)
    return conn


def _assert_expected_role(conn):
    """
    Fails closed if conn did not authenticate as exactly EXPECTED_ROLE.
    Guards against a credentials file that silently points at a
    different -- possibly more privileged -- role (independent review
    Sec 8). Closes conn before raising, so a rejected connection is
    never left open or usable by the caller.
    """
    with conn.cursor() as cur:
        cur.execute("select current_user;")
        actual_role = cur.fetchone()[0]

    if actual_role != EXPECTED_ROLE:
        conn.close()
        raise IngestionRoleMismatch(
            f"Connected as role {actual_role!r}, but this adapter "
            f"requires exactly {EXPECTED_ROLE!r}. Refusing to proceed "
            "with an unexpected role (B2.3.2 security refinement)."
        )
