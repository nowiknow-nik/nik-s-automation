"""
B2.3.5 adapter: reads one change_detection.py output file
(data/snapshots/changes/change_*.json) and, subject to the four-mode
conn/dry_run matrix below (NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_INGESTION_DESIGN.md
Sec 5.5), inserts its mapped rows into
youtube_evidence.change_detection_events.

Structurally different from channel_snapshot_ingest.py/
video_inventory_ingest.py/analytics_ingest.py in three ways, all
deliberate (design doc Sec 5.2/5.3/5.4), not oversights:

1. One file maps to N rows, not one -- map_change_detection_events()
   returns a list. Every row from one call shares one
   detection_run_id.
2. No youtube_evidence.collection_runs handling at all --
   change_detection.py is not one of collector.py's three components,
   and detection_run_id deliberately carries no FK to collection_runs
   (schema doc Sec 6.2, founder-resolved 2026-08-14).
3. Resolving previous_snapshot_id/current_snapshot_id requires a real
   SELECT against youtube_evidence.channel_snapshots
   (resolve_channel_snapshot_ids() below) -- unlike every prior
   adapter's mapping step, this cannot be fully computed without a
   database connection, which is why "dry run" means something new
   here (Sec 5.5).

Idempotency (design doc Sec 5.6) is enforced entirely by the live
UNIQUE (source_file, metric) constraint on change_detection_events
(Migration A, NIK_YOUTUBE_B2_3_5_CHANGE_DETECTION_CONSTRAINT_PROPOSAL.sql)
-- every write below is an INSERT ... ON CONFLICT (source_file, metric)
DO NOTHING, never DO UPDATE -- youtube_evidence.forbid_mutation()'s
BEFORE UPDATE OR DELETE trigger would abort a DO UPDATE anyway. Nothing
in this module issues UPDATE or DELETE against any evidence table, and
nothing should ever be added that does.

Does not modify change_detection.py, analytics_snapshot.py, or
quota_ledger.py, does not touch quota governance, and never connects
through the Supabase Data API -- see db.py. Ingestion-layer code never
calls the YouTube API, so it has no interaction with quota policy at
all -- the same non-relationship every other adapter in this package
already has with quota governance.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from psycopg2.extras import Json

from .collection_runs import _relative_path
from .db import get_connection
from .errors import IngestionNotConfigured
from .mappings import map_change_detection_events, validate_change_detection_events


@dataclass
class ChangeDetectionIngestResult:
    source_file: str
    detection_run_id: str
    rows_mapped: int
    previous_snapshot_id: "str | None"
    previous_snapshot_resolved: bool  # False = not attempted (conn=None); True = attempted, value may still be None
    current_snapshot_id: "str | None"
    current_snapshot_resolved: bool
    rows_inserted: int
    dry_run: bool


def _resolve_one_snapshot_id(conn, channel_id, generated_at_utc):
    with conn.cursor() as cur:
        cur.execute(
            """
            select snapshot_id from youtube_evidence.channel_snapshots
            where channel_id = %(channel_id)s and generated_at_utc = %(generated_at_utc)s;
            """,
            {"channel_id": channel_id, "generated_at_utc": generated_at_utc},
        )
        row = cur.fetchone()
        return row[0] if row is not None else None


def resolve_channel_snapshot_ids(conn, previous_snapshot, current_snapshot, channel_id):
    """
    Design doc Sec 5.3. Requires a real conn -- there is no meaningful
    "resolve without a database" mode; conn=None is handled entirely by
    the caller before this function is ever reached.

    Runs (up to) two lookups against the live
    youtube_evidence.channel_snapshots table: one for
    previous_snapshot['generated_at_utc'], one for
    current_snapshot['generated_at_utc'], both matched against the same
    channel_id. channel_snapshots' live UNIQUE (channel_id,
    generated_at_utc) constraint (applied at B2.3.1) makes each lookup
    return 0 or 1 rows, never more -- no ambiguity is possible. A
    0-row result resolves to None; the caller still inserts the row, it
    does not drop it (fail-open, schema doc Sec 6.6).

    Runs once per file (not once per row) by design -- three identical
    round trips per file would be wasteful and could, in principle,
    observe different results if a concurrent write landed between
    them.

    Returns (previous_snapshot_id, current_snapshot_id).
    """
    previous_snapshot_id = _resolve_one_snapshot_id(
        conn, channel_id, previous_snapshot["generated_at_utc"]
    )
    current_snapshot_id = _resolve_one_snapshot_id(
        conn, channel_id, current_snapshot["generated_at_utc"]
    )
    return previous_snapshot_id, current_snapshot_id


def _insert_change_detection_event(conn, row):
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into youtube_evidence.change_detection_events (
                detection_run_id, schema_version, generated_at_utc, entity_type, entity_id, metric,
                previous_value, current_value, change_type, absolute_change, percentage_change, evidence_class,
                previous_snapshot_id, current_snapshot_id, previous_snapshot_source, current_snapshot_source,
                source_file
            ) values (
                %(detection_run_id)s, %(schema_version)s, %(generated_at_utc)s, %(entity_type)s, %(entity_id)s, %(metric)s,
                %(previous_value)s, %(current_value)s, %(change_type)s, %(absolute_change)s, %(percentage_change)s, %(evidence_class)s,
                %(previous_snapshot_id)s, %(current_snapshot_id)s, %(previous_snapshot_source)s, %(current_snapshot_source)s,
                %(source_file)s
            )
            on conflict (source_file, metric) do nothing
            returning event_id;
            """,
            {
                **row,
                # previous_snapshot_source/current_snapshot_source target
                # jsonb columns -- unlike metrics_requested in
                # analytics_ingest.py, both are Json(...)-wrapped here,
                # no native-array exception applies to this table.
                "previous_snapshot_source": Json(row["previous_snapshot_source"]),
                "current_snapshot_source": Json(row["current_snapshot_source"]),
            },
        )
        return cur.fetchone() is not None


def ingest_change_detection_events(path, conn=None, dry_run=True):
    """
    Design doc Sec 5.5 -- four modes, distinguished by conn and dry_run
    together:

      conn=None,  dry_run=True  -> structural dry run: validates and
                                    maps every row; resolution is not
                                    attempted at all --
                                    previous_snapshot_resolved/
                                    current_snapshot_resolved are False,
                                    both IDs None.
      real conn,  dry_run=True  -> resolution dry run: validates, maps,
                                    AND runs the real resolution SELECTs
                                    (resolve_channel_snapshot_ids()) --
                                    so this mode can show exactly what a
                                    live ingestion would produce,
                                    including genuine NULL fallbacks --
                                    but never executes an INSERT and
                                    never commits.
      real conn,  dry_run=False -> live ingestion: resolves, inserts
                                    every row with ON CONFLICT
                                    (source_file, metric) DO NOTHING,
                                    commits.
      conn=None,  dry_run=False -> raises ValueError -- identical to
                                    the existing pattern in every prior
                                    adapter; there is no "execute with
                                    no connection" mode.

    Reads and validates the file first, pure, no database I/O, so a
    malformed file is rejected before any database call, dry run or
    not -- same ordering as every prior adapter.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        doc = json.load(file)

    validate_change_detection_events(doc)
    source_file = _relative_path(path)
    rows = map_change_detection_events(doc, source_file=source_file)
    detection_run_id = rows[0]["detection_run_id"]
    # Guaranteed identical across every changes[] entry by
    # validate_change_detection_events()'s Decision-5 check.
    channel_id = doc["changes"][0]["entity_id"]

    if conn is None:
        if not dry_run:
            raise ValueError("dry_run=False requires a real database connection.")
        return ChangeDetectionIngestResult(
            source_file=source_file,
            detection_run_id=detection_run_id,
            rows_mapped=len(rows),
            previous_snapshot_id=None,
            previous_snapshot_resolved=False,
            current_snapshot_id=None,
            current_snapshot_resolved=False,
            rows_inserted=0,
            dry_run=True,
        )

    previous_snapshot_id = None
    current_snapshot_id = None
    rows_inserted = 0

    try:
        previous_snapshot_id, current_snapshot_id = resolve_channel_snapshot_ids(
            conn, doc["previous_snapshot"], doc["current_snapshot"], channel_id
        )

        for row in rows:
            row["previous_snapshot_id"] = previous_snapshot_id
            row["current_snapshot_id"] = current_snapshot_id

        if not dry_run:
            for row in rows:
                if _insert_change_detection_event(conn, row):
                    rows_inserted += 1
            conn.commit()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise

    return ChangeDetectionIngestResult(
        source_file=source_file,
        detection_run_id=detection_run_id,
        rows_mapped=len(rows),
        previous_snapshot_id=previous_snapshot_id,
        previous_snapshot_resolved=True,
        current_snapshot_id=current_snapshot_id,
        current_snapshot_resolved=True,
        rows_inserted=rows_inserted,
        dry_run=dry_run,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Ingest one change_detection.py output file into youtube_evidence.change_detection_events."
    )
    parser.add_argument("file", type=Path, help="Path to a data/snapshots/changes/change_*.json file")
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
        print("(reporting mapping/validation only, no resolution or duplicate check possible)")

    try:
        result = ingest_change_detection_events(args.file, conn=conn, dry_run=dry_run)
    finally:
        if conn is not None:
            conn.close()

    print(f"source_file:                 {result.source_file}")
    print(f"detection_run_id:            {result.detection_run_id}")
    print(f"rows_mapped:                 {result.rows_mapped}")
    print(f"previous_snapshot_id:        {result.previous_snapshot_id}")
    print(f"previous_snapshot_resolved:  {result.previous_snapshot_resolved}")
    print(f"current_snapshot_id:         {result.current_snapshot_id}")
    print(f"current_snapshot_resolved:   {result.current_snapshot_resolved}")
    print(f"rows_inserted:               {result.rows_inserted}")
    print(f"dry_run:                     {result.dry_run}")


if __name__ == "__main__":
    main()
