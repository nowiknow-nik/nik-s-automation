import json
from pathlib import Path
from unittest.mock import MagicMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion import db
from ingestion.errors import IngestionNotConfigured, IngestionRoleMismatch


def _mock_conn_for_role(role):
    """
    A minimal stand-in for a psycopg2 connection, deep enough to
    support `with conn.cursor() as cur: cur.execute(...); cur.fetchone()`,
    matching the pattern used in test_ingestion_channel_snapshot.py.
    fetchone() always returns a one-tuple containing `role`, mirroring
    what `select current_user;` returns from real Postgres.
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = (role,)
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _write_credentials(path, db_url="postgresql://fake-host/fake-db"):
    path.write_text(json.dumps({"db_url": db_url}), encoding="utf-8")


# --- missing / incomplete credentials file -------------------------------
# (pre-existing behavior; re-asserted here so db.py has direct test
# coverage of its own -- previously only exercised indirectly.)

def test_raises_when_credentials_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", tmp_path / "does_not_exist.json")

    with pytest.raises(IngestionNotConfigured, match="No database credential"):
        db.get_connection()


def test_raises_when_db_url_key_missing(tmp_path, monkeypatch):
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"not_db_url": "x"}), encoding="utf-8")
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", creds_file)

    with pytest.raises(IngestionNotConfigured, match="db_url"):
        db.get_connection()


def test_does_not_attempt_to_connect_when_not_configured(tmp_path, monkeypatch):
    """Fails closed before ever touching psycopg2.connect -- not just before returning a connection."""
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", tmp_path / "does_not_exist.json")
    connect_spy = MagicMock()
    monkeypatch.setattr(db.psycopg2, "connect", connect_spy)

    with pytest.raises(IngestionNotConfigured):
        db.get_connection()

    connect_spy.assert_not_called()


# --- post-connect role identity check (security refinement) -------------

def test_returns_connection_when_role_matches(tmp_path, monkeypatch):
    creds_file = tmp_path / "creds.json"
    _write_credentials(creds_file)
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", creds_file)

    conn = _mock_conn_for_role("youtube_ingest")
    monkeypatch.setattr(db.psycopg2, "connect", MagicMock(return_value=conn))

    result = db.get_connection()

    assert result is conn
    conn.close.assert_not_called()


def test_raises_and_closes_connection_when_role_does_not_match(tmp_path, monkeypatch):
    creds_file = tmp_path / "creds.json"
    _write_credentials(creds_file)
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", creds_file)

    conn = _mock_conn_for_role("postgres")
    monkeypatch.setattr(db.psycopg2, "connect", MagicMock(return_value=conn))

    with pytest.raises(IngestionRoleMismatch, match="postgres"):
        db.get_connection()

    conn.close.assert_called_once()


def test_role_mismatch_error_names_both_roles(tmp_path, monkeypatch):
    creds_file = tmp_path / "creds.json"
    _write_credentials(creds_file)
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", creds_file)

    conn = _mock_conn_for_role("some_other_role")
    monkeypatch.setattr(db.psycopg2, "connect", MagicMock(return_value=conn))

    with pytest.raises(IngestionRoleMismatch) as exc_info:
        db.get_connection()

    message = str(exc_info.value)
    assert "some_other_role" in message
    assert "youtube_ingest" in message


def test_role_check_issues_select_current_user(tmp_path, monkeypatch):
    creds_file = tmp_path / "creds.json"
    _write_credentials(creds_file)
    monkeypatch.setattr(db, "DB_CREDENTIALS_FILE", creds_file)

    conn = _mock_conn_for_role("youtube_ingest")
    monkeypatch.setattr(db.psycopg2, "connect", MagicMock(return_value=conn))

    db.get_connection()

    cursor = conn.cursor.return_value
    executed = [call.args[0].lower() for call in cursor.execute.call_args_list]
    assert any("current_user" in stmt for stmt in executed)


def test_expected_role_constant_is_youtube_ingest():
    """Pins the constant itself, so a future accidental edit is caught directly, not just indirectly."""
    assert db.EXPECTED_ROLE == "youtube_ingest"
