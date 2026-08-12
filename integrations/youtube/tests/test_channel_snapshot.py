from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from channel_snapshot import build_snapshot


SAMPLE_CHANNEL = {
    "kind": "youtube#channel",
    "etag": "sample-etag",
    "id": "UCsample000000000000000",
    "snippet": {
        "title": "Sample Channel",
        "description": "A sample description.",
        "customUrl": "@sample",
        "publishedAt": "2026-01-01T00:00:00Z",
        "country": "US",
    },
    "statistics": {
        "viewCount": "42",
        "subscriberCount": "7",
        "videoCount": "3",
        "hiddenSubscriberCount": False,
    },
    "contentDetails": {
        "relatedPlaylists": {
            "uploads": "UUsample000000000000000",
            "likes": "LL",
        },
    },
    "brandingSettings": {
        "channel": {"title": "Sample Channel"},
    },
}


def test_build_snapshot_has_required_metadata_fields():
    snapshot = build_snapshot(SAMPLE_CHANNEL)

    assert snapshot["schema_version"] == "1.0"
    assert snapshot["snapshot_type"] == "youtube_channel"
    assert snapshot["snapshot_id"]
    assert snapshot["generated_at_utc"]
    assert snapshot["source"] == "youtube_data_api"
    assert snapshot["api_version"] == "v3"
    assert snapshot["channel_id"] == "UCsample000000000000000"


def test_build_snapshot_collection_id_defaults_to_none():
    """
    Standalone runs (outside collector.py) never set NIK_COLLECTION_ID,
    so build_snapshot's default must stay None rather than, say, an
    empty string -- None is how this codebase already distinguishes
    "not applicable" from a real value (see pagination_completed).
    """
    snapshot = build_snapshot(SAMPLE_CHANNEL)

    assert snapshot["collection_id"] is None


def test_build_snapshot_collection_id_passthrough():
    snapshot = build_snapshot(SAMPLE_CHANNEL, collection_id="a-collection-run-id")

    assert snapshot["collection_id"] == "a-collection-run-id"


def test_build_snapshot_snapshot_id_is_unique_per_call():
    first = build_snapshot(SAMPLE_CHANNEL)
    second = build_snapshot(SAMPLE_CHANNEL)

    assert first["snapshot_id"] != second["snapshot_id"]


def test_build_snapshot_retrieval_metadata_shape():
    snapshot = build_snapshot(SAMPLE_CHANNEL)
    retrieval_metadata = snapshot["retrieval_metadata"]

    assert retrieval_metadata["retrieved_resources"] == ["youtube#channel"]
    assert retrieval_metadata["pagination_completed"] is None
    assert retrieval_metadata["errors"] == []
    assert retrieval_metadata["warnings"] == []


def test_build_snapshot_preserves_raw_response_as_evidence():
    snapshot = build_snapshot(SAMPLE_CHANNEL)
    raw = snapshot["evidence"]["raw_response"]

    assert raw is SAMPLE_CHANNEL
    # Fields the reshaped "channel" view below doesn't carry forward
    # are still recoverable from the preserved raw response.
    assert raw["etag"] == "sample-etag"
    assert raw["contentDetails"]["relatedPlaylists"]["likes"] == "LL"


def test_build_snapshot_existing_channel_view_unchanged():
    """
    The pre-existing reshaped "channel" block is untouched by this
    change, including its known missing-vs-zero limitation (see the
    next test) — this pass adds provenance fields alongside it and
    does not modify it.
    """
    snapshot = build_snapshot(SAMPLE_CHANNEL)
    channel = snapshot["channel"]

    assert channel["channel_id"] == "UCsample000000000000000"
    assert channel["title"] == "Sample Channel"
    assert channel["statistics"]["view_count"] == 42
    assert channel["statistics"]["subscriber_count"] == 7
    assert channel["statistics"]["video_count"] == 3
    assert channel["uploads_playlist_id"] == "UUsample000000000000000"


def test_build_snapshot_missing_statistics_field_still_defaults_to_zero():
    """
    Characterization test, not an endorsement. Documents CURRENT,
    known behavior: a statistics field absent from the API response
    is silently recorded as an observed 0, indistinguishable from a
    real zero. This is the exact gap the inspection report flagged in
    build_snapshot() and this pass deliberately does not fix it (the
    founder's own instruction: preserve it as a future data-quality
    validation/test requirement, don't hotfix it here). This test is
    the concrete anchor for that future fix — when the missing-vs-zero
    distinction is implemented, this assertion is expected to change.
    """
    channel_missing_view_count = {
        **SAMPLE_CHANNEL,
        "statistics": {
            "subscriberCount": "7",
            "videoCount": "3",
            # viewCount deliberately absent, not just zero
        },
    }

    snapshot = build_snapshot(channel_missing_view_count)

    assert snapshot["channel"]["statistics"]["view_count"] == 0
