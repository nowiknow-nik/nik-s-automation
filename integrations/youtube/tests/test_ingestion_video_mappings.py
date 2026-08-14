from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion.errors import IngestRejected
from ingestion.mappings import (
    map_video_inventory_snapshot,
    validate_video_inventory_snapshot,
)


# ---------------------------------------------------------------------
# Real fixtures, embedded verbatim -- not synthesized. The "good" one is
# data/snapshots/videos/videos_20260812_192336.json; the two legacy ones
# are videos_20260812_171438.json and videos_20260812_173835.json, both
# confirmed genuinely on disk and genuinely missing the same five fields
# (B2.3.3 design doc Sec 5). All three real files currently have
# video_count == 0 and videos == [] -- no real fixture with a populated
# videos array exists yet (B2.3.3 design doc Sec 4/15, Decision 3/4
# review). The per-item cases below (SYNTHETIC_VIDEO_*) are therefore
# explicitly synthetic: they prove the validation/mapping logic handles
# these shapes correctly, not that this behavior has been observed
# against real populated YouTube data. That distinction is intentional
# and should not be quietly dropped.
# ---------------------------------------------------------------------

GOOD_VIDEO_INVENTORY_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_video_inventory",
    "snapshot_id": "27869aab-2c6d-440c-b24d-4e9500d30450",
    "generated_at_utc": "2026-08-12T19:23:36.514369+00:00",
    "source": "youtube_data_api",
    "api_version": "v3",
    "collection_id": "98321ba3-6bf1-4e50-aa8b-8a223ccd4862",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "retrieval_metadata": {
        "retrieved_resources": ["youtube#playlistItem", "youtube#video"],
        "pagination_completed": True,
        "errors": [],
        "warnings": [],
    },
    "uploads_playlist_id": "UUn4OmZFMasYBkmCx6Q2oUBQ",
    "video_count": 0,
    "videos": [],
}

LEGACY_VIDEO_INVENTORY_SNAPSHOT = {
    "schema_version": "1.0",
    "snapshot_type": "youtube_video_inventory",
    "generated_at_utc": "2026-08-12T17:14:38.277717+00:00",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "uploads_playlist_id": "UUn4OmZFMasYBkmCx6Q2oUBQ",
    "video_count": 0,
    "videos": [],
    # No snapshot_id, source, api_version, or retrieval_metadata --
    # exactly matching both real legacy files on disk
    # (videos_20260812_171438.json and videos_20260812_173835.json
    # share this identical shape). collection_id is also absent here,
    # same as the real files, but that alone is NOT one of the
    # validation failures below -- collection_id is nullable/optional
    # (only checked for UUID validity when present), so its absence is
    # not itself a "missing required field" problem.
}

# A single synthetic per-video item shaped like a real videos().list()
# enrichment match -- the 10 acquisition keys fetch_video_inventory()
# actually produces, plus video_details as enrich_video_statistics()
# stores it verbatim (B2.3.3 design doc Sec 10).
SYNTHETIC_VIDEO_WITH_DETAILS = {
    "playlist_item_id": "VVVuNE9tWkZNYXNZQmttQ3g2UTJvVUJRLnN5bnRoZXRpYw",
    "video_id": "dQw4w9WgXcQ",
    "title": "Synthetic Sample Video",
    "description": "Synthetic description text for test purposes only.",
    "published_at": "2026-08-10T12:00:00Z",
    "channel_id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
    "channel_title": "Now I Know NIK",
    "position": 0,
    "resource_id": {"kind": "youtube#video", "videoId": "dQw4w9WgXcQ"},
    "status": {"privacyStatus": "public"},
    "video_details": {
        "kind": "youtube#video",
        "etag": "synthetic-etag-value",
        "id": "dQw4w9WgXcQ",
        "snippet": {"title": "Synthetic Sample Video"},
        "contentDetails": {"duration": "PT4M13S"},
        "statistics": {"viewCount": "100", "likeCount": "10"},
        "status": {"privacyStatus": "public"},
    },
}


def _write_snapshot(videos, video_count=None):
    return {
        **GOOD_VIDEO_INVENTORY_SNAPSHOT,
        "videos": videos,
        "video_count": video_count if video_count is not None else len(videos),
    }


# --- validate_video_inventory_snapshot() -- envelope-level ------------

def test_good_video_inventory_snapshot_passes_validation():
    validate_video_inventory_snapshot(GOOD_VIDEO_INVENTORY_SNAPSHOT)  # must not raise


def test_legacy_video_inventory_snapshot_rejected_naming_every_missing_field():
    with pytest.raises(IngestRejected) as exc_info:
        validate_video_inventory_snapshot(LEGACY_VIDEO_INVENTORY_SNAPSHOT)

    message = str(exc_info.value)
    for field in ("snapshot_id", "source", "api_version", "retrieval_metadata"):
        assert field in message, f"expected {field!r} to be named in the rejection message"

    # collection_id is nullable -- its absence must NOT be reported as
    # a missing-field problem (unlike the four genuinely required
    # fields above).
    assert "collection_id" not in message


def test_invalid_snapshot_id_rejected():
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "snapshot_id": "not-a-uuid"}
    with pytest.raises(IngestRejected, match="not a valid UUID"):
        validate_video_inventory_snapshot(doc)


def test_invalid_collection_id_rejected():
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "collection_id": "not-a-uuid"}
    with pytest.raises(IngestRejected, match="not a valid UUID"):
        validate_video_inventory_snapshot(doc)


def test_null_collection_id_is_valid():
    """A standalone-run snapshot with collection_id: null must pass -- nullable, not required."""
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "collection_id": None}
    validate_video_inventory_snapshot(doc)  # must not raise


def test_wrong_snapshot_type_rejected():
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "snapshot_type": "youtube_channel"}
    with pytest.raises(IngestRejected, match="snapshot_type must be 'youtube_video_inventory'"):
        validate_video_inventory_snapshot(doc)


# --- validate_video_inventory_snapshot() -- video_count/videos --------
#
# design doc Sec 11 item 5 (cross-field consistency, no channel_snapshot
# analog) and item 6 (the truthy-trap: every real fixture today has
# video_count == 0, which must NOT be treated as missing).

def test_video_count_zero_is_valid_not_treated_as_missing():
    """
    Regression guard for the exact trap the design doc flags: a
    truthy check (`if not doc.get("video_count")`) would wrongly reject
    every real fixture on disk today, since 0 is falsy in Python. The
    real check must be presence-based ("video_count" not in doc).
    """
    assert GOOD_VIDEO_INVENTORY_SNAPSHOT["video_count"] == 0
    validate_video_inventory_snapshot(GOOD_VIDEO_INVENTORY_SNAPSHOT)  # must not raise


def test_missing_video_count_key_rejected():
    doc = {k: v for k, v in GOOD_VIDEO_INVENTORY_SNAPSHOT.items() if k != "video_count"}
    with pytest.raises(IngestRejected, match="missing required field: 'video_count'"):
        validate_video_inventory_snapshot(doc)


def test_video_count_mismatch_with_len_videos_rejected():
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "videos": [SYNTHETIC_VIDEO_WITH_DETAILS], "video_count": 5}
    with pytest.raises(IngestRejected, match="does not match len\\(videos\\)"):
        validate_video_inventory_snapshot(doc)


def test_missing_videos_key_rejected():
    doc = {k: v for k, v in GOOD_VIDEO_INVENTORY_SNAPSHOT.items() if k != "videos"}
    with pytest.raises(IngestRejected, match="missing required field: 'videos'"):
        validate_video_inventory_snapshot(doc)


def test_videos_not_a_list_rejected():
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "videos": {"not": "a list"}, "video_count": 1}
    with pytest.raises(IngestRejected, match="missing required field: 'videos'"):
        validate_video_inventory_snapshot(doc)


# --- validate_video_inventory_snapshot() -- per-item (Decision 3) -----
#
# Light/tolerant per B2.3.3 Decision 3: each element of 'videos' need
# only be a dict. Must accept {}, {"video_id": "abc"},
# {"video_id": None}, and a dict with video_details -- never require
# the 10 acquisition keys, video_id, or video_details. A non-dict
# element rejects the whole snapshot. These fixtures are synthetic --
# see the module-level note above.

def test_item_with_video_details_is_accepted():
    doc = _write_snapshot([SYNTHETIC_VIDEO_WITH_DETAILS])
    validate_video_inventory_snapshot(doc)  # must not raise


def test_item_without_video_details_is_accepted():
    """Simulates the enrichment-didn't-match case -- video_details absent entirely."""
    item = {k: v for k, v in SYNTHETIC_VIDEO_WITH_DETAILS.items() if k != "video_details"}
    doc = _write_snapshot([item])
    validate_video_inventory_snapshot(doc)  # must not raise


def test_item_with_null_video_id_is_accepted():
    doc = _write_snapshot([{"video_id": None}])
    validate_video_inventory_snapshot(doc)  # must not raise


def test_item_missing_video_id_key_entirely_is_accepted():
    """Empty dict -- no video_id key at all, not even null. Still just needs to be a dict."""
    doc = _write_snapshot([{}])
    validate_video_inventory_snapshot(doc)  # must not raise


def test_item_with_only_video_id_is_accepted():
    doc = _write_snapshot([{"video_id": "abc"}])
    validate_video_inventory_snapshot(doc)  # must not raise


def test_non_dict_item_rejects_whole_snapshot():
    """
    A malformed individual item must reject the entire snapshot, never
    be silently dropped -- must never turn "50 retrieved, 1 malformed"
    into "silently store 49" (Decision 3 founder condition).
    """
    doc = _write_snapshot([SYNTHETIC_VIDEO_WITH_DETAILS, "not-a-video-object"])
    with pytest.raises(IngestRejected, match=r"videos\[1\] must be an object"):
        validate_video_inventory_snapshot(doc)


def test_non_dict_item_names_its_index_even_with_valid_items_around_it():
    doc = _write_snapshot([{"video_id": "a"}, 42, {"video_id": "c"}])
    with pytest.raises(IngestRejected, match=r"videos\[1\] must be an object, got int"):
        validate_video_inventory_snapshot(doc)


# --- map_video_inventory_snapshot() ------------------------------------

def test_map_video_inventory_snapshot_field_by_field():
    row = map_video_inventory_snapshot(
        GOOD_VIDEO_INVENTORY_SNAPSHOT, source_file="data/snapshots/videos/videos_20260812_192336.json"
    )

    assert row["snapshot_id"] == "27869aab-2c6d-440c-b24d-4e9500d30450"
    assert row["collection_id"] == "98321ba3-6bf1-4e50-aa8b-8a223ccd4862"
    assert row["channel_id"] == "UCn4OmZFMasYBkmCx6Q2oUBQ"
    assert row["uploads_playlist_id"] == "UUn4OmZFMasYBkmCx6Q2oUBQ"
    assert row["video_count"] == 0
    assert row["videos"] == []
    assert row["source_file"] == "data/snapshots/videos/videos_20260812_192336.json"


def test_map_video_inventory_snapshot_preserves_videos_and_retrieval_metadata_verbatim():
    doc = _write_snapshot([SYNTHETIC_VIDEO_WITH_DETAILS])
    row = map_video_inventory_snapshot(doc, source_file="x.json")

    assert row["videos"] is doc["videos"]
    assert row["videos"][0]["video_details"]["etag"] == "synthetic-etag-value"
    assert row["retrieval_metadata"] is doc["retrieval_metadata"]
    assert row["retrieval_metadata"]["pagination_completed"] is True


def test_map_video_inventory_snapshot_standalone_run_has_null_collection_id():
    doc = {**GOOD_VIDEO_INVENTORY_SNAPSHOT, "collection_id": None}
    row = map_video_inventory_snapshot(doc, source_file="x.json")

    assert row["collection_id"] is None
