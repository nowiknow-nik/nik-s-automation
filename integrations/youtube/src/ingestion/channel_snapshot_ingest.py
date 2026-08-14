"""
B2.3.2 adapter: reads one channel_snapshot.py output file and, subject
to dry_run, inserts it into youtube_evidence.channel_snapshots -- first
ensuring its youtube_evidence.collection_runs parent exists, if the
snapshot carries a collection_id (design doc Sec 6.2).

Append-only by construction: every write below is an
INSERT ... ON CONFLICT (id) DO NOTHING, never DO UPDATE (design doc
Sec 6.3 -- DO UPDATE would fire the forbid_mutation trigger from
NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 6.3 and abort).
Nothing in this module issues UPDATE or DELETE against any evidence
table, and nothing should ever be added that does.

Does not modify channel_snapshot.py or collector.py, does not touch
quota governance, and never connects through the Supabase Data API --
see db.py and design doc Sec 7/6.8.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from psycopg2.extras import Json

from .collection_runs import _relative_path, ensure_collection_run
from .db import get_connection
from .errors import IngestionNotConfigured
from .mappings import (
    map_channel_snapshot,
    validate_channel_snapshot,
)


@dataclass
class IngestResult:
    snapshot_id: str
    channel_snapshot_inserted: bool
    collection_run_id: "str | None"
    collection_run_inserted: bool
    dry_run: bool
    source_file: str


def _channel_snapshot_exists(conn, snapshot_id):
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from youtube_evidence.channel_snapshots where snapshot_id = %s",
            (snapshot_id,),
        )
        return cur.fetchone() is not None


def _insert_channel_snapshot(conn, row):
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into youtube_evidence.channel_snapshots (
                snapshot_id, schema_version, snapshot_type, generated_at_utc, source,
                api_version, collection_id, channel_id, title, description, custom_url,
                published_at, country, view_count, subscriber_count, video_count,
                hidden_subscriber_count, uploads_playlist_id, branding,
                retrieval_metadata, raw_response, source_file
            ) values (
                %(snapshot_id)s, %(schema_version)s, %(snapshot_type)s, %(generated_at_utc)s, %(source)s,
                %(api_version)s, %(collection_id)s, %(channel_id)s, %(title)s, %(description)s, %(custom_url)s,
                %(published_at)s, %(country)s, %(view_count)s, %(subscriber_count)s, %(video_count)s,
                %(hidden_subscriber_count)s, %(uploads_playlist_id)s, %(branding)s,
                %(retrieval_metadata)s, %(raw_response)s, %(source_file)s
            )
            on conflict (snapshot_id) do nothing
            returning snapshot_id;
            """,
            {
                **row,
                "branding": Json(row["branding"]) if row["branding"] is not None else None,
                "retrieval_metadata": Json(row["retrieval_metadata"]),
                "raw_response": Json(row["raw_response"]),
            },
        )
        return cur.fetchone() is not None


def ingest_channel_snapshot(path, conn=None, dry_run=True):
    """
    The real implementation of design doc Sec 8. Reads and validates
    the file first -- pure, no database I/O -- so a malformed file
    (Sec 5/6.6) is rejected before any database call is attempted,
    dry run or not.

    conn=None + dry_run=True: a pure local dry run -- validates and
    maps the file, but can't report duplicate/FK state since there's
    no database to check against.

    conn=<real connection> + dry_run=True: a full dry run -- validates,
    maps, and checks real duplicate/FK state, but issues no INSERT.

    conn=<real connection> + dry_run=False: the real thing. Both
    inserts (parent then child, if needed) happen in one transaction --
    commit only after both succeed, rollback on any exception, so a
    failure never leaves an orphaned collection_runs row behind with
    no corresponding snapshot.

    dry_run=False with conn=None raises ValueError -- there is no
    "execute with no connection" mode.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        doc = json.load(file)

    validate_channel_snapshot(doc)
    row = map_channel_snapshot(doc, source_file=_relative_path(path))

    if conn is None:
        if not dry_run:
            raise ValueError("dry_run=False requires a real database connection.")
        return IngestResult(
            snapshot_id=row["snapshot_id"],
            channel_snapshot_inserted=False,
            collection_run_id=row["collection_id"],
            collection_run_inserted=False,
            dry_run=True,
            source_file=row["source_file"],
        )

    collection_run_id = None
    collection_run_inserted = False
    snapshot_inserted = False

    try:
        if row["collection_id"] is not None:
            collection_run_id, collection_run_inserted = ensure_collection_run(
                conn, row["collection_id"], dry_run
            )

        already_present = _channel_snapshot_exists(conn, row["snapshot_id"])

        if not already_present and not dry_run:
            snapshot_inserted = _insert_channel_snapshot(conn, row)

        if not dry_run:
            conn.commit()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise

    return IngestResult(
        snapshot_id=row["snapshot_id"],
        channel_snapshot_inserted=snapshot_inserted,
        collection_run_id=collection_run_id,
        collection_run_inserted=collection_run_inserted,
        dry_run=dry_run,
        source_file=row["source_file"],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Ingest one channel_snapshot.py output file into youtube_evidence.channel_snapshots."
    )
    parser.add_argument("file", type=Path, help="Path to a data/snapshots/channel_*.json file")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write to Supabase. Without this flag, runs as a dry run and writes nothing.",
    )
    args = parser.parse_args()

    dry_run = not args.execute

    print(
        "===== EXECUTING -- this will write to the live Supabase database ====="
        if not dry_run
        else "===== DRY RUN (pass --execute to actually write; nothing will be written) ====="
    )

    conn = None
    try:
        conn = get_connection()
    except IngestionNotConfigured as exc:
        if not dry_run:
            raise
        print(f"(no database connection available -- {exc})")
        print("(reporting mapping/validation only, no duplicate/FK check possible)")

    try:
        result = ingest_channel_snapshot(args.file, conn=conn, dry_run=dry_run)
    finally:
        if conn is not None:
            conn.close()

    print(f"snapshot_id:               {result.snapshot_id}")
    print(f"channel_snapshot_inserted: {result.channel_snapshot_inserted}")
    print(f"collection_run_id:         {result.collection_run_id}")
    print(f"collection_run_inserted:   {result.collection_run_inserted}")
    print(f"dry_run:                   {result.dry_run}")


if __name__ == "__main__":
    main()
