"""
Shared collection-run I/O: resolving and (if needed) inserting the
youtube_evidence.collection_runs parent row a snapshot's collection_id
FK points at.

Extracted from channel_snapshot_ingest.py during B2.3.3 (B2.3.3
Decision 2), unchanged in behavior. Not specific to channel snapshots
in anything but its original location -- collection_id, a logs
directory, and the collection_runs table are all it ever touches.
video_inventory_ingest.py uses this module directly rather than
duplicating it, since B2.3.3 is the second real consumer of this logic
(the trigger this project's own quota-governance documentation already
named for centralizing shared logic, rather than a speculative
abstraction from a single use).

Append-only by construction, same as every other ingestion module:
every write below is an INSERT ... ON CONFLICT (id) DO NOTHING, never
DO UPDATE. Nothing here issues UPDATE or DELETE against any evidence
table, and nothing should ever be added that does.
"""

import json
from pathlib import Path

from psycopg2.extras import Json

from .errors import IngestRejected
from .mappings import map_collection_run, validate_collection_run


BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"


def _relative_path(path):
    path = Path(path)
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def find_collection_log(collection_id, logs_dir=None):
    """
    Scans logs/collection_*.json for the one whose own collection_id
    matches. Deliberately not a glob-newest-file shortcut like
    collector.py's own find_latest_snapshot() -- that finds the LATEST
    file; this needs the SPECIFIC file whose content matches a known
    id, which requires opening candidates, not sorting by mtime
    (B2.3.1 design doc Sec 6.2). Returns (path, doc), or (None, None)
    if no file matches.

    logs_dir defaults to the module-level LOGS_DIR, resolved at call
    time (not baked in as a default-argument value at import time) so
    that tests can monkeypatch this module's LOGS_DIR and have callers
    that don't pass logs_dir explicitly -- like ensure_collection_run()
    below -- actually pick up the patched value.
    """
    if logs_dir is None:
        logs_dir = LOGS_DIR

    for candidate in sorted(Path(logs_dir).glob("collection_*.json")):
        try:
            with candidate.open("r", encoding="utf-8") as file:
                doc = json.load(file)
        except (json.JSONDecodeError, OSError):
            continue
        if doc.get("collection_id") == collection_id:
            return candidate, doc
    return None, None


def _collection_run_exists(conn, collection_id):
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from youtube_evidence.collection_runs where collection_id = %s",
            (collection_id,),
        )
        return cur.fetchone() is not None


def _insert_collection_run(conn, row):
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into youtube_evidence.collection_runs (
                collection_id, schema_version, collection_type, started_at_utc,
                finished_at_utc, success, components, source_file
            ) values (
                %(collection_id)s, %(schema_version)s, %(collection_type)s, %(started_at_utc)s,
                %(finished_at_utc)s, %(success)s, %(components)s, %(source_file)s
            )
            on conflict (collection_id) do nothing
            returning collection_id;
            """,
            {**row, "components": Json(row["components"])},
        )
        return cur.fetchone() is not None


def ensure_collection_run(conn, collection_id, dry_run):
    """
    B2.3.1 design doc Sec 6.2, option (a). If a parent row already
    exists, does nothing. Otherwise finds the matching
    logs/collection_*.json by collection_id (not by filename/timestamp
    guessing), validates and maps it with the already-approved
    collection_runs mapping, and inserts it -- unless dry_run, in which
    case it only reports what would happen. If no matching log file can
    be found at all, raises IngestRejected rather than proceeding with
    an unresolvable FK (fail closed, design doc Sec 6.2/6.6) -- this
    never silently nulls out a real collection_id to dodge the foreign
    key.

    Returns (collection_id, inserted: bool).
    """
    if _collection_run_exists(conn, collection_id):
        return collection_id, False

    log_path, log_doc = find_collection_log(collection_id)
    if log_doc is None:
        raise IngestRejected(
            f"snapshot references collection_id={collection_id!r}, "
            "but no matching logs/collection_*.json was found and no "
            "collection_runs row exists yet -- refusing to insert the "
            "snapshot with an unresolvable FK (design doc Sec 6.2)."
        )

    validate_collection_run(log_doc)
    row = map_collection_run(log_doc, source_file=_relative_path(log_path))

    if dry_run:
        return collection_id, False

    inserted = _insert_collection_run(conn, row)
    return collection_id, inserted
