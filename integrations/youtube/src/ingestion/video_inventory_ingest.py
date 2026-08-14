"""
B2.3.3 adapter: reads one video_inventory.py output file
(data/snapshots/videos/videos_*.json) and, subject to dry_run, inserts
it into youtube_evidence.video_inventory_snapshots -- first ensuring
its youtube_evidence.collection_runs parent exists, if the snapshot
carries a collection_id (design doc Sec 6.2, reused unchanged from
B2.3.2 via collection_runs.py -- see B2.3.3 Decision 2).

Mirrors channel_snapshot_ingest.py's structure and guarantees one for
one: append-only by construction (every write below is an
INSERT ... ON CONFLICT (snapshot_id) DO NOTHING, never DO UPDATE --
youtube_evidence.forbid_mutation()'s BEFORE UPDATE OR DELETE trigger
would abort a DO UPDATE anyway). Nothing in this module issues UPDATE
or DELETE against any evidence table, and nothing should ever be added
that does.

Ingests video_inventory.py's current output exactly as produced --
including the playlist-item/video_details fidelity asymmetry documented
in NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 6.9 and
NIK_YOUTUBE_B2_3_3_VIDEO_INVENTORY_INGESTION_DESIGN.md Sec 10. Does not
modify video_inventory.py or collector.py, does not touch quota
governance, and never connects through the Supabase Data API -- see
db.py and design doc Sec 7/6.8 (B2.3.3 Decision 4: acquisition-layer
fidelity improvements, if any, are a separate future item, not part of
this file).
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
    map_video_inventory_snapshot,
    validate_video_inventory_snapshot,
)


@dataclass
class IngestResult:
    snapshot_id: str
    video_inventory_snapshot_inserted: bool
    collection_run_id: "str | None"
    collection_run_inserted: bool
    dry_run: bool
    source_file: str


def _video_inventory_snapshot_exists(conn, snapshot_id):
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from youtube_evidence.video_inventory_snapshots where snapshot_id = %s",
            (snapshot_id,),
        )
        return cur.fetchone() is not None


def _insert_video_inventory_snapshot(conn, row):
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into youtube_evidence.video_inventory_snapshots (
                snapshot_id, schema_version, snapshot_type, generated_at_utc, source,
                api_version, collection_id, channel_id, uploads_playlist_id, video_count,
                videos, retrieval_metadata, source_file
            ) values (
                %(snapshot_id)s, %(schema_version)s, %(snapshot_type)s, %(generated_at_utc)s, %(source)s,
                %(api_version)s, %(collection_id)s, %(channel_id)s, %(uploads_playlist_id)s, %(video_count)s,
                %(videos)s, %(retrieval_metadata)s, %(source_file)s
            )
            on conflict (snapshot_id) do nothing
            returning snapshot_id;
            """,
            {
                **row,
                "videos": Json(row["videos"]),
                "retrieval_metadata": Json(row["retrieval_metadata"]),
            },
        )
        return cur.fetchone() is not None


def ingest_video_inventory(path, conn=None, dry_run=True):
    """
    Mirrors ingest_channel_snapshot() exactly (see that function's own
    docstring for the full conn/dry_run mode matrix) -- reads and
    validates the file first, pure, no database I/O, so a malformed
    file is rejected before any database call, dry run or not; when a
    real connection is supplied, resolves/inserts the collection_runs
    parent first, then the video_inventory_snapshots child, both inside
    one transaction (design doc Sec 6.2/12); dry_run=False with
    conn=None raises ValueError -- there is no "execute with no
    connection" mode.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        doc = json.load(file)

    validate_video_inventory_snapshot(doc)
    row = map_video_inventory_snapshot(doc, source_file=_relative_path(path))

    if conn is None:
        if not dry_run:
            raise ValueError("dry_run=False requires a real database connection.")
        return IngestResult(
            snapshot_id=row["snapshot_id"],
            video_inventory_snapshot_inserted=False,
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

        already_present = _video_inventory_snapshot_exists(conn, row["snapshot_id"])

        if not already_present and not dry_run:
            snapshot_inserted = _insert_video_inventory_snapshot(conn, row)

        if not dry_run:
            conn.commit()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise

    return IngestResult(
        snapshot_id=row["snapshot_id"],
        video_inventory_snapshot_inserted=snapshot_inserted,
        collection_run_id=collection_run_id,
        collection_run_inserted=collection_run_inserted,
        dry_run=dry_run,
        source_file=row["source_file"],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Ingest one video_inventory.py output file into youtube_evidence.video_inventory_snapshots."
    )
    parser.add_argument("file", type=Path, help="Path to a data/snapshots/videos/videos_*.json file")
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
        result = ingest_video_inventory(args.file, conn=conn, dry_run=dry_run)
    finally:
        if conn is not None:
            conn.close()

    print(f"snapshot_id:                       {result.snapshot_id}")
    print(f"video_inventory_snapshot_inserted: {result.video_inventory_snapshot_inserted}")
    print(f"collection_run_id:                 {result.collection_run_id}")
    print(f"collection_run_inserted:           {result.collection_run_inserted}")
    print(f"dry_run:                           {result.dry_run}")


if __name__ == "__main__":
    main()
