from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import sys

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_credentials


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "analytics"


def get_channel_id():
    snapshot_dir = BASE_DIR / "data" / "snapshots"

    files = sorted(
        snapshot_dir.glob("channel_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            "No channel snapshot found. Run channel_snapshot.py first."
        )

    with files[0].open("r", encoding="utf-8") as f:
        data = json.load(f)

    return data["channel"]["channel_id"]


def get_date_range():
    """
    Analytics reports require a start and end date.

    We use the previous 7 complete calendar days so that
    the initial snapshot has a stable reporting window.
    """

    today = datetime.now(timezone.utc).date()

    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=6)

    return (
        start_date.isoformat(),
        end_date.isoformat(),
    )


def fetch_channel_analytics(youtube_analytics, channel_id, start_date, end_date):
    metrics = ",".join(
        [
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "subscribersGained",
            "subscribersLost",
            "likes",
            "comments",
            "shares",
        ]
    )

    response = (
        youtube_analytics.reports()
        .query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics=metrics,
        )
        .execute()
    )

    return response


def main():
    print("===== NIK YOUTUBE ANALYTICS SNAPSHOT =====")

    credentials = get_credentials()

    youtube_analytics = build(
        "youtubeAnalytics",
        "v2",
        credentials=credentials,
    )

    channel_id = get_channel_id()

    start_date, end_date = get_date_range()

    analytics_response = fetch_channel_analytics(
        youtube_analytics,
        channel_id,
        start_date,
        end_date,
    )

    snapshot = {
        "schema_version": "1.0",
        "snapshot_type": "youtube_channel_analytics",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),

        "channel_id": channel_id,

        "reporting_period": {
            "start_date": start_date,
            "end_date": end_date,
        },

        "metrics_requested": [
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "subscribersGained",
            "subscribersLost",
            "likes",
            "comments",
            "shares",
        ],

        "analytics": analytics_response,
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
        / f"channel_analytics_{timestamp}.json"
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
    print("ANALYTICS: SUCCESS")
    print("CHANNEL ID:", channel_id)
    print("PERIOD:", start_date, "to", end_date)

    rows = analytics_response.get("rows", [])

    if rows:
        print("ANALYTICS ROW:", rows[0])
    else:
        print("ANALYTICS ROWS: 0")

    print()
    print("OUTPUT:")
    print(output_file.resolve())
    print()
    print("============================================")


if __name__ == "__main__":
    main()