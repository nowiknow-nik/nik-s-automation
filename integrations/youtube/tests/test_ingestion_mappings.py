from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.errors import IngestRejected
from ingestion.mappings import (
    map_channel_snapshot,
    map_collection_run,
    validate_channel_snapshot,
    validate_collection_run,
)


# ---------------------------------------------------------------------
# Real fixtures, embedded verbatim -- not synthesized. The "good" one is
# data/snapshots/channel_20260812_192334.json; the two "legacy" ones are
# channel_20260812_171041.json and channel_20260812_173832.json, both
# confirmed genuinely on disk and genuinely missing these fields (design
# doc Sec 5), not hypothetical malformed examples.
# ---------------------------------------------------------------------

GOOD_CHANNEL_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_channel",
    "snapshot_id": "a9594393-7572-4597-bb05-76082a9c993d",
    "generated_at_utc": "2026-08-12T19:23:34.033659+00:00",
    "source": "youtube_data_api",
    "api_version": "v3",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "retrieval_metadata": {
        "retrieved_resources": ["youtube#channel"],
        "pagination_completed": None,
        "errors": [],
        "warnings": [],
    },
    "channel": {
        "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
        "title": "Now I Know NIK",
        "description": "",
        "custom_url": "@nowiknownik",
        "published_at": "2026-08-09T03:33:12.388094Z",
        "country": None,
        "statistics": {
            "view_count": 0,
            "subscriber_count": 0,
            "video_count": 0,
            "hidden_subscriber_count": False,
        },
        "uploads_playlist_id": "UUn4OmZFMasYBkmCx6Q2oUBQ",
        "branding": {"channel": {"title": "Now I Know NIK"}},
    },
    "evidence": {
        "raw_response": {
            "kind": "youtube#channel",
            "etag": "sn2foP0cmcqG48ldS2NfKydi_ME",
            "id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "statistics": {"viewCount": "0", "subscriberCount": "0"},
        }
    },
}

LEGACY_CHANNEL_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_channel",
    "generated_at_utc": "2026-08-12T17:10:41.604142+00:00",
    "channel": {
        "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
        "title": "Now I Know NIK",
        "description": "",
        "custom_url": "@nowiknownik",
        "published_at": "2026-08-09T03:33:12.388094Z",
        "country": None,
        "statistics": {
            "view_count": 0,
            "subscriber_count": 0,
            "video_count": 0,
            "hidden_subscriber_count": False,
        },
        "uploads_playlist_id": "UUn4OmZFMasYBkmCx6Q2oUBQ",
        "branding": {"channel": {"title": "Now I Know NIK"}},
    },
    # No snapshot_id, source, api_version, collection_id, top-level
    # channel_id, retrieval_metadata, or evidence -- exactly matching
    # the two real files on disk (design doc Sec 5).
}

GOOD_COLLECTION_RUN = {
    "schema_version": "1.0",
    "collection_type": "youtube_full_collection",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "collection_started_at_utc": "2026-08-12T19:23:30.436491+00:00",
    "collection_finished_at_utc": "2026-08-12T19:23:40.192417+00:00",
    "success": True,
    "components": [
        {"component": "channel_snapshot", "success": True, "produced_snapshot_id": "a9594393-7572-4597-bb05-76082a9c993d"},
        {"component": "video_inventory", "success": True},
        {"component": "analytics_snapshot", "success": True},
    ],
}

LEGACY_COLLECTION_RUN = {
    "schema_version": "1.0",
    "collection_type": "youtube_full_collection",
    "collection_started_at_utc": "2026-08-12T17:38:28.979636+00:00",
    "collection_finished_at_utc": "2026-08-12T17:38:40.021697+00:00",
    "success": True,
    "components": [{"component": "channel_snapshot", "success": True}],
    # No collection_id -- matching the real collection_20260812_173840.json.
}


# --- validate_channel_snapshot() --------------------------------------

def test_good_channel_snapshot_passes_validation():
    validate_channel_snapshot(GOOD_CHANNEL_SNAPSHOT)  # must not raise


def test_legacy_channel_snapshot_rejected_naming_every_missing_field():
    with pytest.raises(IngestRejected) as exc_info:
        validate_channel_snapshot(LEGACY_CHANNEL_SNAPSHOT)

    message = str(exc_info.value)
    for field in ("snapshot_id", "source", "api_version", "channel_id", "retrieval_metadata"):
        assert field in message, f"expected {field!r} to be named in the rejection message"


def test_invalid_snapshot_id_rejected():
    doc = {**GOOD_CHANNEL_SNAPSHOT, "snapshot_id": "not-a-uuid"}
    with pytest.raises(IngestRejected, match="not a valid UUID"):
        validate_channel_snapshot(doc)


def test_invalid_collection_id_rejected():
    doc = {**GOOD_CHANNEL_SNAPSHOT, "collection_id": "not-a-uuid"}
    with pytest.raises(IngestRejected, match="not a valid UUID"):
        validate_channel_snapshot(doc)


def test_null_collection_id_is_valid():
    """A standalone-run snapshot with collection_id: null must pass -- nullable, not required."""
    doc = {**GOOD_CHANNEL_SNAPSHOT, "collection_id": None}
    validate_channel_snapshot(doc)  # must not raise


def test_wrong_snapshot_type_rejected():
    doc = {**GOOD_CHANNEL_SNAPSHOT, "snapshot_type": "youtube_video_inventory"}
    with pytest.raises(IngestRejected, match="snapshot_type must be 'youtube_channel'"):
        validate_channel_snapshot(doc)


def test_malformed_published_at_rejected():
    doc = {
        **GOOD_CHANNEL_SNAPSHOT,
        "channel": {**GOOD_CHANNEL_SNAPSHOT["channel"], "published_at": "not-a-timestamp"},
    }
    with pytest.raises(IngestRejected, match="published_at does not parse"):
        validate_channel_snapshot(doc)


def test_z_suffixed_published_at_is_valid():
    """
    YouTube's own API renders publishedAt with a literal "Z" suffix.
    This must validate cleanly even on Python 3.10, where
    datetime.fromisoformat() alone would reject a bare "Z" (design doc
    Sec 6.7 / mappings.py's _is_valid_timestamp docstring).
    """
    validate_channel_snapshot(GOOD_CHANNEL_SNAPSHOT)  # must not raise; published_at ends in "Z"


# --- map_channel_snapshot() -------------------------------------------

def test_map_channel_snapshot_field_by_field():
    row = map_channel_snapshot(GOOD_CHANNEL_SNAPSHOT, source_file="data/snapshots/channel_20260812_192334.json")

    assert row["snapshot_id"] == "a9594393-7572-4597-bb05-76082a9c993d"
    assert row["collection_id"] == "98321ba3-6bf1-4e50-aa8b-8a223ccd4862"
    assert row["channel_id"] == "UCn4OmZFMasYBkmCx6Q2oUBQ"
    assert row["title"] == "Now I Know NIK"
    assert row["custom_url"] == "@nowiknownik"
    assert row["country"] is None
    assert row["view_count"] == 0
    assert row["subscriber_count"] == 0
    assert row["hidden_subscriber_count"] is False
    assert row["uploads_playlist_id"] == "UUn4OmZFMasYBkmCx6Q2oUBQ"
    assert row["branding"] == {"channel": {"title": "Now I Know NIK"}}
    assert row["source_file"] == "data/snapshots/channel_20260812_192334.json"


def test_map_channel_snapshot_preserves_raw_response_and_retrieval_metadata_verbatim():
    row = map_channel_snapshot(GOOD_CHANNEL_SNAPSHOT, source_file="x.json")

    assert row["raw_response"] is GOOD_CHANNEL_SNAPSHOT["evidence"]["raw_response"]
    assert row["raw_response"]["etag"] == "sn2foP0cmcqG48ldS2NfKydi_ME"
    assert row["retrieval_metadata"] is GOOD_CHANNEL_SNAPSHOT["retrieval_metadata"]
    assert row["retrieval_metadata"]["pagination_completed"] is None  # not coerced to False


def test_map_channel_snapshot_standalone_run_has_null_collection_id():
    doc = {**GOOD_CHANNEL_SNAPSHOT, "collection_id": None}
    row = map_channel_snapshot(doc, source_file="x.json")

    assert row["collection_id"] is None


# --- validate_collection_run() / map_collection_run() ------------------

def test_good_collection_run_passes_validation():
    validate_collection_run(GOOD_COLLECTION_RUN)  # must not raise


def test_legacy_collection_run_rejected_missing_collection_id():
    with pytest.raises(IngestRejected, match="collection_id"):
        validate_collection_run(LEGACY_COLLECTION_RUN)


def test_collection_run_success_false_is_valid():
    """success is checked for presence, not truthiness -- False is a real, legitimate observation."""
    doc = {**GOOD_COLLECTION_RUN, "success": False}
    validate_collection_run(doc)  # must not raise


def test_map_collection_run_field_by_field():
    row = map_collection_run(GOOD_COLLECTION_RUN, source_file="logs/collection_20260812_192340.json")

    assert row["collection_id"] == "98321ba3-6bf1-4e50-aa8b-8a223ccd4862"
    assert row["collection_type"] == "youtube_full_collection"
    assert row["started_at_utc"] == "2026-08-12T19:23:30.436491+00:00"
    assert row["finished_at_utc"] == "2026-08-12T19:23:40.192417+00:00"
    assert row["success"] is True
    assert row["components"] is GOOD_COLLECTION_RUN["components"]
    assert row["source_file"] == "logs/collection_20260812_192340.json"
