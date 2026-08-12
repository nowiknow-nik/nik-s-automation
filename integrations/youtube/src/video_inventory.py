from pathlib import Path
from datetime import datetime, timezone
import json
import sys
import uuid

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_credentials


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "snapshots" / "videos"

CHANNEL_SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"


def get_latest_channel_snapshot():
    files = sorted(
        CHANNEL_SNAPSHOT_DIR.glob("channel_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            "No channel snapshot found. Run channel_snapshot.py first."
        )

    with files[0].open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_video_inventory(youtube, uploads_playlist_id):
    videos = []
    next_page_token = None

    while True:
        response = youtube.playlistItems().list(
            part="snippet,contentDetails,status",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token,
        ).execute()

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            status = item.get("status", {})

            videos.append(
                {
                    "playlist_item_id": item.get("id"),
                    "video_id": content_details.get("videoId"),
                    "title": snippet.get("title"),
                    "description": snippet.get("description"),
                    "published_at": snippet.get("publishedAt"),
                    "channel_id": snippet.get("channelId"),
                    "channel_title": snippet.get("channelTitle"),
                    "position": snippet.get("position"),
                    "resource_id": snippet.get("resourceId"),
                    "status": status,
                }
            )

        next_page_token = response.get("nextPageToken")

        if not next_page_token:
            break

    return videos


def enrich_video_statistics(youtube, videos):
    if not videos:
        return videos

    video_ids = [
        video["video_id"]
        for video in videos
        if video.get("video_id")
    ]

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]

        response = youtube.videos().list(
            part="snippet,contentDetails,statistics,status",
            id=",".join(batch),
            maxResults=50,
        ).execute()

        by_id = {
            item["id"]: item
            for item in response.get("items", [])
        }

        for video in videos:
            video_id = video.get("video_id")

            if video_id in by_id:
                item = by_id[video_id]

                # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §8): store
                # the untouched videos().list() item rather than a
                # hand-picked subset, so kind/etag/id travel with it too.
                # Strictly more complete than the previous reshaped dict;
                # nothing that read the old four keys is removed.
                video["video_details"] = item

    return videos


def main():
    print("===== NIK YOUTUBE VIDEO INVENTORY =====")

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    channel_snapshot = get_latest_channel_snapshot()

    channel = channel_snapshot["channel"]

    channel_id = channel["channel_id"]
    uploads_playlist_id = channel["uploads_playlist_id"]

    videos = fetch_video_inventory(
        youtube,
        uploads_playlist_id,
    )

    videos = enrich_video_statistics(
        youtube,
        videos,
    )

    snapshot = {
        "schema_version": "1.0",
        "snapshot_type": "youtube_video_inventory",
        "snapshot_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source": "youtube_data_api",
        "api_version": "v3",

        "channel_id": channel_id,

        # Provenance (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md §7). Reaching this
        # point means fetch_video_inventory()'s pagination loop actually
        # ran to completion — there is currently no partial-failure path
        # that continues past a failed page, so True is accurate for any
        # snapshot that gets this far, not an assumption.
        "retrieval_metadata": {
            "retrieved_resources": ["youtube#playlistItem", "youtube#video"],
            "pagination_completed": True,
            "errors": [],
            "warnings": [],
        },

        "uploads_playlist_id": uploads_playlist_id,

        "video_count": len(videos),

        "videos": videos,
    }

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    output_file = (
        OUTPUT_DIR
        / f"videos_{timestamp}.json"
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            snapshot,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("INVENTORY: SUCCESS")
    print("CHANNEL ID:", channel_id)
    print("UPLOADS PLAYLIST:", uploads_playlist_id)
    print("VIDEOS FOUND:", len(videos))
    print()
    print("OUTPUT:")
    print(output_file.resolve())
    print()
    print("========================================")


if __name__ == "__main__":
    main()