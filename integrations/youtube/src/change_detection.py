import json
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"
OUTPUT_DIR = BASE_DIR / "data" / "snapshots" / "changes"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_latest_snapshots(snapshot_type: str):
    matches = []

    for path in SNAPSHOT_DIR.rglob("*.json"):
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue

        if data.get("snapshot_type") == snapshot_type:
            timestamp = data.get("generated_at_utc")
            if timestamp:
                matches.append((parse_timestamp(timestamp), path, data))

    matches.sort(key=lambda item: item[0])

    return matches


def compare_numeric(previous, current):
    if previous is None or current is None:
        return {
            "change_type": "UNAVAILABLE",
            "absolute_change": None,
            "percentage_change": None,
        }

    absolute_change = current - previous

    if previous == 0:
        percentage_change = None
    else:
        percentage_change = (absolute_change / previous) * 100

    if absolute_change == 0:
        change_type = "UNCHANGED"
    else:
        change_type = "CHANGED"

    return {
        "change_type": change_type,
        "absolute_change": absolute_change,
        "percentage_change": percentage_change,
    }


def compare_channel(previous_data, current_data):
    previous_channel = previous_data.get("channel", {})
    current_channel = current_data.get("channel", {})

    previous_stats = previous_channel.get("statistics", {})
    current_stats = current_channel.get("statistics", {})

    metrics = [
        "subscriber_count",
        "view_count",
        "video_count",
    ]

    changes = []

    for metric in metrics:
        previous_value = previous_stats.get(metric)
        current_value = current_stats.get(metric)

        result = compare_numeric(previous_value, current_value)

        changes.append(
            {
                "entity_type": "channel",
                "entity_id": current_channel.get("channel_id"),
                "metric": metric,
                "previous_value": previous_value,
                "current_value": current_value,
                **result,
                "evidence_class": "DERIVED",
            }
        )

    return changes


def build_change_record(previous_entry, current_entry):
    previous_timestamp, previous_path, previous_data = previous_entry
    current_timestamp, current_path, current_data = current_entry

    changes = compare_channel(previous_data, current_data)

    return {
        "schema_version": "1.0",
        "snapshot_type": "youtube_change_detection",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "previous_snapshot": {
            "path": str(previous_path),
            "generated_at_utc": previous_timestamp.isoformat(),
        },
        "current_snapshot": {
            "path": str(current_path),
            "generated_at_utc": current_timestamp.isoformat(),
        },
        "entity_type": "channel",
        "changes": changes,
    }


def save_change_record(record):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"change_{timestamp}.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    return output_path


def main():
    print("===== NIK YOUTUBE CHANGE DETECTION =====")
    print()

    snapshots = get_latest_snapshots("youtube_channel")

    if len(snapshots) < 2:
        print("CHANGE DETECTION: UNAVAILABLE")
        print("REASON: Fewer than two channel snapshots found")
        print()
        print("========================================")
        return 1

    previous_entry = snapshots[-2]
    current_entry = snapshots[-1]

    print("PREVIOUS:")
    print(previous_entry[1])
    print()

    print("CURRENT:")
    print(current_entry[1])
    print()

    record = build_change_record(previous_entry, current_entry)
    output_path = save_change_record(record)

    print("CHANGE DETECTION: SUCCESS")
    print("CHANGES FOUND:", len(record["changes"]))
    print()
    print("OUTPUT:")
    print(output_path)
    print()
    print("========================================")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())