from pathlib import Path
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import get_credentials
from googleapiclient.discovery import build


CHANNEL_ID = "UCn4OmZFMasYBkmCx6Q2oUBQ"

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
OUTPUT_FILE = LOG_DIR / "youtube_capability_discovery.json"


def main():
    print("===== NIK YOUTUBE CAPABILITY DISCOVERY =====")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    # --------------------------------------------------
    # CHANNEL
    # --------------------------------------------------

    channel_response = youtube.channels().list(
        part="snippet,contentDetails,statistics,brandingSettings",
        id=CHANNEL_ID,
    ).execute()

    channel = channel_response.get("items", [])

    # --------------------------------------------------
    # PLAYLISTS
    # --------------------------------------------------

    playlist_response = youtube.playlists().list(
        part="snippet,contentDetails,status",
        channelId=CHANNEL_ID,
        maxResults=50,
    ).execute()

    playlists = playlist_response.get("items", [])

    # --------------------------------------------------
    # UPLOADS PLAYLIST
    # --------------------------------------------------

    uploads_playlist_id = None

    if channel:
        uploads_playlist_id = (
            channel[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )

    videos = []

    if uploads_playlist_id:
        playlist_items_response = youtube.playlistItems().list(
            part="snippet,contentDetails,status",
            playlistId=uploads_playlist_id,
            maxResults=50,
        ).execute()

        videos = playlist_items_response.get("items", [])

    # --------------------------------------------------
    # SEARCH CAPABILITY
    # --------------------------------------------------

    search_response = youtube.search().list(
        part="snippet",
        channelId=CHANNEL_ID,
        type="video",
        maxResults=10,
    ).execute()

    search_results = search_response.get("items", [])

    # --------------------------------------------------
    # RESULT
    # --------------------------------------------------

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel_id": CHANNEL_ID,

        "capabilities_tested": {
            "channel": True,
            "playlists": True,
            "uploads_playlist": bool(uploads_playlist_id),
            "videos": True,
            "search": True,
        },

        "channel": channel,
        "playlists": playlists,
        "uploads_playlist_id": uploads_playlist_id,
        "videos": videos,
        "search_results": search_results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print()
    print("DISCOVERY: SUCCESS")
    print("CHANNEL FOUND:", bool(channel))
    print("PLAYLISTS:", len(playlists))
    print("VIDEOS FOUND:", len(videos))
    print("SEARCH RESULTS:", len(search_results))
    print()
    print("OUTPUT:")
    print(OUTPUT_FILE)
    print()
    print("============================================")


if __name__ == "__main__":
    main()