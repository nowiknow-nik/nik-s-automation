import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.discovery import build


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "snapshots"

sys.path.insert(0, str(BASE_DIR / "src"))

from auth import get_credentials


# ---------------------------------------------------------
# CHANNEL
# ---------------------------------------------------------

def get_channel(youtube):
    response = youtube.channels().list(
        part="snippet,statistics,contentDetails,brandingSettings",
        mine=True,
    ).execute()

    items = response.get("items", [])

    if not items:
        raise RuntimeError("No YouTube channel was found for the authenticated account.")

    return items[0]


# ---------------------------------------------------------
# SNAPSHOT
# ---------------------------------------------------------

def build_snapshot(channel):
    snippet = channel.get("snippet", {})
    statistics = channel.get("statistics", {})
    content_details = channel.get("contentDetails", {})
    branding = channel.get("brandingSettings", {})

    return {
        "schema_version": "1.0",
        "snapshot_type": "youtube_channel",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),

        "channel": {
            "channel_id": channel.get("id"),

            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "custom_url": snippet.get("customUrl"),

            "published_at": snippet.get("publishedAt"),
            "country": snippet.get("country"),

            "statistics": {
                "view_count": int(statistics.get("viewCount", 0)),
                "subscriber_count": int(
                    statistics.get("subscriberCount", 0)
                ),
                "video_count": int(
                    statistics.get("videoCount", 0)
                ),
                "hidden_subscriber_count": statistics.get(
                    "hiddenSubscriberCount",
                    False,
                ),
            },

            "uploads_playlist_id": (
                content_details
                .get("relatedPlaylists", {})
                .get("uploads")
            ),

            "branding": branding,
        },
    }


# ---------------------------------------------------------
# SAVE
# ---------------------------------------------------------

def save_snapshot(snapshot):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )

    output_path = DATA_DIR / f"channel_{timestamp}.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            snapshot,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return output_path


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    print("===== NIK YOUTUBE CHANNEL SNAPSHOT =====")

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    channel = get_channel(youtube)

    snapshot = build_snapshot(channel)

    output_path = save_snapshot(snapshot)

    channel_data = snapshot["channel"]
    statistics = channel_data["statistics"]

    print()
    print("SNAPSHOT: SUCCESS")
    print(f"CHANNEL ID: {channel_data['channel_id']}")
    print(f"CHANNEL NAME: {channel_data['title']}")
    print(f"SUBSCRIBERS: {statistics['subscriber_count']}")
    print(f"VIDEOS: {statistics['video_count']}")
    print(f"VIEWS: {statistics['view_count']}")
    print()
    print(f"OUTPUT:")
    print(output_path)
    print()
    print("========================================")


if __name__ == "__main__":
    main()