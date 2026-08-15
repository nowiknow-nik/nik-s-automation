"""
Pure mapping/validation functions: source JSON -> youtube_evidence row
dicts. No I/O, no network, no Supabase -- Tier 0 in the B2.3.2/B2.3.3/
B2.3.4 designs' test plans (NIK_YOUTUBE_B2_3_2_CHANNEL_SNAPSHOT_INGESTION_DESIGN.md
Sec 6.9; NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_INGESTION_DESIGN.md Sec 6).
Implements the field mapping already specified in
NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.1 (collection_runs),
Sec 8.2 (channel_snapshots), Sec 8.3 (video_inventory_snapshots), and
Sec 8.4 (channel_analytics_snapshots) exactly -- nothing here should
diverge from those four tables without the design doc changing first.
"""

import uuid
from datetime import date, datetime

from .errors import IngestRejected


def _is_valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _is_valid_timestamp(value):
    """
    Validates only -- never used as the value actually written. The
    real INSERT passes the original source string through unchanged to
    Postgres's own (more permissive) timestamptz parser, so a
    snapshot's published_at -- which YouTube's own API renders with a
    literal "Z" suffix, e.g. "2026-08-09T03:33:12.388094Z" -- round-
    trips losslessly even though Python's datetime.fromisoformat() only
    accepts "Z" from Python 3.11 onward. This repo's own venv is 3.10
    (confirmed this session), so "Z" is normalized here for validation
    purposes only, never for the value actually stored.
    """
    if not isinstance(value, str):
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
        return True
    except ValueError:
        return False


def _is_valid_date(value):
    """
    Plain-date validator for reporting_period.start_date/end_date --
    these are "YYYY-MM-DD" strings (date.fromisoformat's exact
    supported shape), not timestamps, so this is deliberately separate
    from _is_valid_timestamp() above rather than reusing it.
    """
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------
# channel_snapshots  (NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.2)
# ---------------------------------------------------------------------

REQUIRED_CHANNEL_SNAPSHOT_KEYS = (
    "snapshot_id",
    "schema_version",
    "snapshot_type",
    "generated_at_utc",
    "source",
    "api_version",
    "channel_id",
    "retrieval_metadata",
)


def validate_channel_snapshot(doc):
    """
    Structural + value validation (design doc Sec 6.6), run before any
    SQL is issued. Collects every problem rather than stopping at the
    first, so a rejected file gets one clear, complete report -- this
    is the check that correctly rejects channel_20260812_171041.json
    and channel_20260812_173832.json (design doc Sec 5), each missing
    five of these fields at once, in one message naming all five.
    """
    problems = []

    for key in REQUIRED_CHANNEL_SNAPSHOT_KEYS:
        if doc.get(key) in (None, ""):
            problems.append(f"missing required field: {key!r}")

    channel = doc.get("channel")
    if not isinstance(channel, dict):
        problems.append("missing required field: 'channel' (must be an object)")
        channel = {}

    statistics = channel.get("statistics")
    if not isinstance(statistics, dict):
        problems.append("missing required field: 'channel.statistics' (must be an object)")
        statistics = {}
    else:
        for stat_key in ("view_count", "subscriber_count", "video_count", "hidden_subscriber_count"):
            if stat_key not in statistics:
                problems.append(f"missing required field: 'channel.statistics.{stat_key}'")

    evidence = doc.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("raw_response") in (None, {}):
        problems.append("missing required field: 'evidence.raw_response'")

    if doc.get("snapshot_id") not in (None, "") and not _is_valid_uuid(doc["snapshot_id"]):
        problems.append(f"snapshot_id is not a valid UUID: {doc['snapshot_id']!r}")

    collection_id = doc.get("collection_id")
    if collection_id is not None and not _is_valid_uuid(collection_id):
        problems.append(f"collection_id is present but not a valid UUID: {collection_id!r}")

    if doc.get("generated_at_utc") and not _is_valid_timestamp(doc["generated_at_utc"]):
        problems.append(f"generated_at_utc does not parse as a timestamp: {doc['generated_at_utc']!r}")

    published_at = channel.get("published_at")
    if published_at is not None and not _is_valid_timestamp(published_at):
        problems.append(f"channel.published_at does not parse as a timestamp: {published_at!r}")

    if doc.get("snapshot_type") not in (None, "youtube_channel"):
        problems.append(f"snapshot_type must be 'youtube_channel', got {doc['snapshot_type']!r}")

    if doc.get("source") not in (None, "youtube_data_api"):
        problems.append(f"source must be 'youtube_data_api', got {doc['source']!r}")

    if doc.get("api_version") not in (None, "v3"):
        problems.append(f"api_version must be 'v3', got {doc['api_version']!r}")

    if problems:
        raise IngestRejected(
            f"channel snapshot failed validation ({len(problems)} problem(s)): "
            + "; ".join(problems)
        )


def map_channel_snapshot(doc, source_file):
    """
    NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.2, implemented
    field for field. Caller must run validate_channel_snapshot(doc)
    first -- this function assumes the document already passed.
    """
    channel = doc["channel"]
    statistics = channel["statistics"]

    return {
        "snapshot_id": doc["snapshot_id"],
        "schema_version": doc["schema_version"],
        "snapshot_type": doc["snapshot_type"],
        "generated_at_utc": doc["generated_at_utc"],
        "source": doc["source"],
        "api_version": doc["api_version"],
        "collection_id": doc.get("collection_id"),
        "channel_id": doc["channel_id"],
        "title": channel.get("title"),
        "description": channel.get("description"),
        "custom_url": channel.get("custom_url"),
        "published_at": channel.get("published_at"),
        "country": channel.get("country"),
        "view_count": statistics["view_count"],
        "subscriber_count": statistics["subscriber_count"],
        "video_count": statistics["video_count"],
        "hidden_subscriber_count": statistics["hidden_subscriber_count"],
        "uploads_playlist_id": channel.get("uploads_playlist_id"),
        "branding": channel.get("branding"),
        "retrieval_metadata": doc["retrieval_metadata"],
        "raw_response": doc["evidence"]["raw_response"],
        "source_file": source_file,
    }


# ---------------------------------------------------------------------
# collection_runs  (NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.1)
# ---------------------------------------------------------------------
#
# Only ingested as a side effect of resolving a channel_snapshot's
# collection_id FK (design doc Sec 6.2, option (a)) -- not a standalone
# ingestion target of B2.3.2.

REQUIRED_COLLECTION_RUN_KEYS = (
    "collection_id",
    "schema_version",
    "collection_type",
    "collection_started_at_utc",
    "collection_finished_at_utc",
    "components",
)


def validate_collection_run(doc):
    """
    Mirrors validate_channel_snapshot(), scoped to the smaller
    collection_runs mapping. "success" is checked for presence, not
    truthiness -- it is a real boolean that can legitimately be False.
    """
    problems = []

    for key in REQUIRED_COLLECTION_RUN_KEYS:
        if doc.get(key) in (None, ""):
            problems.append(f"missing required field: {key!r}")

    if "success" not in doc:
        problems.append("missing required field: 'success'")

    if doc.get("collection_id") and not _is_valid_uuid(doc["collection_id"]):
        problems.append(f"collection_id is not a valid UUID: {doc['collection_id']!r}")

    if doc.get("collection_type") not in (None, "youtube_full_collection"):
        problems.append(
            f"collection_type must be 'youtube_full_collection', got {doc['collection_type']!r}"
        )

    if not isinstance(doc.get("components"), list):
        problems.append("'components' must be an array")

    if problems:
        raise IngestRejected(
            f"collection run failed validation ({len(problems)} problem(s)): "
            + "; ".join(problems)
        )


def map_collection_run(doc, source_file):
    """NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.1, implemented field for field."""
    return {
        "collection_id": doc["collection_id"],
        "schema_version": doc["schema_version"],
        "collection_type": doc["collection_type"],
        "started_at_utc": doc["collection_started_at_utc"],
        "finished_at_utc": doc["collection_finished_at_utc"],
        "success": doc["success"],
        "components": doc["components"],
        "source_file": source_file,
    }


# ---------------------------------------------------------------------
# video_inventory_snapshots  (NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md
# Sec 8.3; NIK_YOUTUBE_B2_3_3_VIDEO_INVENTORY_INGESTION_DESIGN.md Sec 6/11)
# ---------------------------------------------------------------------

REQUIRED_VIDEO_INVENTORY_KEYS = (
    "snapshot_id",
    "schema_version",
    "snapshot_type",
    "generated_at_utc",
    "source",
    "api_version",
    "channel_id",
    "retrieval_metadata",
)


def validate_video_inventory_snapshot(doc):
    """
    Envelope-level validation, deliberately the same strictness as
    validate_channel_snapshot() -- same required-field/UUID/timestamp/
    constant checks (B2.3.3 design doc Sec 11 items 1-4).

    Per-item validation is deliberately much lighter than the envelope
    (B2.3.3 Decision 3; design doc Sec 11 item 7): every element of
    'videos' need only be a dict. This does NOT require the 10
    acquisition keys video_inventory.py currently produces, 'video_id',
    or 'video_details' -- video_inventory.py's own output is a ceiling
    on what could be required, not a floor imposed here. A non-dict
    element rejects the whole snapshot (design doc Sec 6.6 fail-closed
    principle) rather than being silently dropped -- this must never
    turn "50 retrieved, 1 malformed" into "silently store 49."

    video_count is checked with "not in doc", never a truthy check --
    design doc Sec 11 item 6 flags this explicitly: every real fixture
    on disk today has video_count == 0, which a truthy check would
    wrongly treat as missing (the same trap map_channel_snapshot's
    statistics fields already avoid).
    """
    problems = []

    for key in REQUIRED_VIDEO_INVENTORY_KEYS:
        if doc.get(key) in (None, ""):
            problems.append(f"missing required field: {key!r}")

    videos = doc.get("videos")
    videos_is_list = isinstance(videos, list)
    if not videos_is_list:
        problems.append("missing required field: 'videos' (must be an array)")
    else:
        for index, item in enumerate(videos):
            if not isinstance(item, dict):
                problems.append(
                    f"videos[{index}] must be an object, got {type(item).__name__}"
                )

    if "video_count" not in doc:
        problems.append("missing required field: 'video_count'")
    elif videos_is_list and doc["video_count"] != len(videos):
        problems.append(
            f"video_count ({doc['video_count']!r}) does not match len(videos) ({len(videos)})"
        )

    if doc.get("snapshot_id") not in (None, "") and not _is_valid_uuid(doc["snapshot_id"]):
        problems.append(f"snapshot_id is not a valid UUID: {doc['snapshot_id']!r}")

    collection_id = doc.get("collection_id")
    if collection_id is not None and not _is_valid_uuid(collection_id):
        problems.append(f"collection_id is present but not a valid UUID: {collection_id!r}")

    if doc.get("generated_at_utc") and not _is_valid_timestamp(doc["generated_at_utc"]):
        problems.append(f"generated_at_utc does not parse as a timestamp: {doc['generated_at_utc']!r}")

    if doc.get("snapshot_type") not in (None, "youtube_video_inventory"):
        problems.append(f"snapshot_type must be 'youtube_video_inventory', got {doc['snapshot_type']!r}")

    if doc.get("source") not in (None, "youtube_data_api"):
        problems.append(f"source must be 'youtube_data_api', got {doc['source']!r}")

    if doc.get("api_version") not in (None, "v3"):
        problems.append(f"api_version must be 'v3', got {doc['api_version']!r}")

    if problems:
        raise IngestRejected(
            f"video inventory snapshot failed validation ({len(problems)} problem(s)): "
            + "; ".join(problems)
        )


def map_video_inventory_snapshot(doc, source_file):
    """
    NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.3, implemented
    field for field. Caller must run validate_video_inventory_snapshot(doc)
    first -- this function assumes the document already passed.

    'videos' is preserved verbatim, item for item -- including the
    playlist-item/video_details asymmetry described in schema design
    doc Sec 6.9 and B2.3.3 design doc Sec 10 (B2.3.3 Decision 4: ingest
    video_inventory.py's current output exactly as produced; do not
    reshape, drop, or backfill any per-item field here).
    """
    return {
        "snapshot_id": doc["snapshot_id"],
        "schema_version": doc["schema_version"],
        "snapshot_type": doc["snapshot_type"],
        "generated_at_utc": doc["generated_at_utc"],
        "source": doc["source"],
        "api_version": doc["api_version"],
        "collection_id": doc.get("collection_id"),
        "channel_id": doc["channel_id"],
        "uploads_playlist_id": doc.get("uploads_playlist_id"),
        "video_count": doc["video_count"],
        "videos": doc["videos"],
        "retrieval_metadata": doc["retrieval_metadata"],
        "source_file": source_file,
    }


# ---------------------------------------------------------------------
# channel_analytics_snapshots  (NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md
# Sec 8.4; NIK_YOUTUBE_B2_3_4_CHANNEL_ANALYTICS_INGESTION_DESIGN.md Sec 3/4)
# ---------------------------------------------------------------------

REQUIRED_ANALYTICS_KEYS = (
    "snapshot_id",
    "schema_version",
    "snapshot_type",
    "generated_at_utc",
    "source",
    "api_version",
    "channel_id",
    "retrieval_metadata",
)


def validate_channel_analytics_snapshot(doc):
    """
    Envelope-level validation, same core strictness as
    validate_channel_snapshot()/validate_video_inventory_snapshot() --
    same required-field/UUID/timestamp/constant checks -- plus three
    checks unique to this table's real shape (B2.3.4 design doc Sec 4):

    'reporting_period' must be an object with valid 'start_date'/
    'end_date' strings, and end_date must not be before start_date --
    this replicates the live channel_analytics_snapshots_period_valid
    CHECK constraint in application code, so a bad file is rejected
    with a clear message here rather than surfacing as a raw Postgres
    constraint violation.

    'metrics_requested' must be a list of strings -- stricter than
    video_inventory_snapshots' "just a dict" per-item precedent,
    because this targets a NOT NULL text[] column, not a loosely-typed
    jsonb blob (see map_channel_analytics_snapshot()'s own docstring).

    'analytics' validation is deliberately minimal (B2.3.4 Decision C):
    it must be present and a dict, nothing about its internal 'rows'/
    'columnHeaders' shape is checked. This is a deliberate limit, not
    missing coverage -- there is no real fixture with non-zero or
    genuinely empty analytics data yet to justify a stricter contract,
    and channel_analytics_snapshots' own live schema doesn't require
    one either. An empty {} is accepted on purpose.

    The two real legacy fixtures (channel_analytics_20260812_172513.json,
    ..._173839.json) predate this schema and are missing four required
    fields at once -- 'snapshot_id', 'source', 'api_version', and
    'retrieval_metadata' -- but NOT 'collection_id', which is nullable
    and never required here, the same distinction B2.3.3's own test
    suite caught and fixed for its equivalent legacy fixture (B2.3.4
    Decision D: reject them via this ordinary check, no special-casing).
    """
    problems = []

    for key in REQUIRED_ANALYTICS_KEYS:
        if doc.get(key) in (None, ""):
            problems.append(f"missing required field: {key!r}")

    reporting_period = doc.get("reporting_period")
    if not isinstance(reporting_period, dict):
        problems.append("missing required field: 'reporting_period' (must be an object)")
        reporting_period = {}
    else:
        start_date = reporting_period.get("start_date")
        end_date = reporting_period.get("end_date")

        if "start_date" not in reporting_period or start_date in (None, ""):
            problems.append("missing required field: 'reporting_period.start_date'")
            start_date = None
        elif not _is_valid_date(start_date):
            problems.append(f"reporting_period.start_date does not parse as a date: {start_date!r}")
            start_date = None

        if "end_date" not in reporting_period or end_date in (None, ""):
            problems.append("missing required field: 'reporting_period.end_date'")
            end_date = None
        elif not _is_valid_date(end_date):
            problems.append(f"reporting_period.end_date does not parse as a date: {end_date!r}")
            end_date = None

        if start_date and end_date and date.fromisoformat(end_date) < date.fromisoformat(start_date):
            problems.append(
                f"reporting_period.end_date ({end_date!r}) is before start_date ({start_date!r})"
            )

    if "metrics_requested" not in doc:
        problems.append("missing required field: 'metrics_requested'")
    elif not isinstance(doc["metrics_requested"], list):
        problems.append("'metrics_requested' must be an array")
    elif not all(isinstance(item, str) for item in doc["metrics_requested"]):
        problems.append("'metrics_requested' must be an array of strings")

    if "analytics" not in doc:
        problems.append("missing required field: 'analytics'")
    elif not isinstance(doc["analytics"], dict):
        problems.append(f"'analytics' must be an object, got {type(doc['analytics']).__name__}")

    if doc.get("snapshot_id") not in (None, "") and not _is_valid_uuid(doc["snapshot_id"]):
        problems.append(f"snapshot_id is not a valid UUID: {doc['snapshot_id']!r}")

    collection_id = doc.get("collection_id")
    if collection_id is not None and not _is_valid_uuid(collection_id):
        problems.append(f"collection_id is present but not a valid UUID: {collection_id!r}")

    if doc.get("generated_at_utc") and not _is_valid_timestamp(doc["generated_at_utc"]):
        problems.append(f"generated_at_utc does not parse as a timestamp: {doc['generated_at_utc']!r}")

    if doc.get("snapshot_type") not in (None, "youtube_channel_analytics"):
        problems.append(f"snapshot_type must be 'youtube_channel_analytics', got {doc['snapshot_type']!r}")

    if doc.get("source") not in (None, "youtube_analytics_api"):
        problems.append(f"source must be 'youtube_analytics_api', got {doc['source']!r}")

    if doc.get("api_version") not in (None, "v2"):
        problems.append(f"api_version must be 'v2', got {doc['api_version']!r}")

    if problems:
        raise IngestRejected(
            f"channel analytics snapshot failed validation ({len(problems)} problem(s)): "
            + "; ".join(problems)
        )


def map_channel_analytics_snapshot(doc, source_file):
    """
    NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.4, implemented
    field for field. Caller must run validate_channel_analytics_snapshot(doc)
    first -- this function assumes the document already passed.

    Two genuine transformations here, unlike every mapping function
    above this one, which are near-total passthrough into jsonb:

    'reporting_start_date'/'reporting_end_date' are EXTRACTED out of
    the nested 'reporting_period' object -- the live table has no
    'reporting_period' column, it has two flat native `date` columns
    (B2.3.4 design doc Sec 4/5).

    'metrics_requested' is returned as a plain Python list, unchanged.
    It must NOT be wrapped in psycopg2's Json(...) adapter the way
    'analytics'/'retrieval_metadata' are below -- it targets a native
    Postgres `text[]` column, not jsonb, and psycopg2 adapts a Python
    list to a Postgres array automatically. That wrapping decision is
    made one layer down, in analytics_ingest.py's insert function, not
    here -- this function's job is only to keep the list a list.
    """
    reporting_period = doc["reporting_period"]

    return {
        "snapshot_id": doc["snapshot_id"],
        "schema_version": doc["schema_version"],
        "snapshot_type": doc["snapshot_type"],
        "generated_at_utc": doc["generated_at_utc"],
        "source": doc["source"],
        "api_version": doc["api_version"],
        "collection_id": doc.get("collection_id"),
        "channel_id": doc["channel_id"],
        "reporting_start_date": reporting_period["start_date"],
        "reporting_end_date": reporting_period["end_date"],
        "metrics_requested": doc["metrics_requested"],
        "analytics": doc["analytics"],
        "retrieval_metadata": doc["retrieval_metadata"],
        "source_file": source_file,
    }
