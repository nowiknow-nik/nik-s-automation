"""
Pure mapping/validation functions: source JSON -> youtube_evidence row
dicts. No I/O, no network, no Supabase -- Tier 0 in the B2.3.2 design's
test plan (NIK_YOUTUBE_B2_3_2_CHANNEL_SNAPSHOT_INGESTION_DESIGN.md Sec
6.9). Implements the field mapping already specified in
NIK_YOUTUBE_SUPABASE_EVIDENCE_SCHEMA_DESIGN.md Sec 8.1 (collection_runs)
and Sec 8.2 (channel_snapshots) exactly -- nothing here should diverge
from those two tables without the design doc changing first.
"""

import uuid
from datetime import datetime

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
