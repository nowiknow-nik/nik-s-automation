from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
LOGS = ROOT / "logs"

CHANNEL_SCRIPT = SRC / "channel_snapshot.py"
VIDEO_SCRIPT = SRC / "video_inventory.py"
ANALYTICS_SCRIPT = SRC / "analytics_snapshot.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_latest_snapshot(
    directory: Path, pattern: str, root: Path = ROOT
) -> tuple[str | None, str | None]:
    """
    Provenance lookup (NIK_YOUTUBE_SNAPSHOT_SCHEMA.md, collection
    linkage pass): after a component subprocess reports success, find
    the snapshot file it just wrote and read back its snapshot_id, so
    the collection log records exactly which snapshot resulted, not
    just that "something" succeeded.

    Same glob-newest-file-by-mtime pattern already used inside
    video_inventory.py and analytics_snapshot.py to find the latest
    channel snapshot. Not foolproof -- it assumes nothing else wrote a
    matching file in the interim, true today but not guaranteed. If no
    matching file is found, or the newest one can't be parsed, this
    returns None for the id rather than raising -- a failed provenance
    lookup should not fail the collection run.
    """
    files = sorted(
        directory.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        return None, None

    try:
        with files[0].open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("snapshot_id"), str(files[0].relative_to(root))
    except (json.JSONDecodeError, OSError):
        return None, str(files[0].relative_to(root))


def run_component(name: str, script: Path, collection_id: str) -> dict:
    started_at = utc_now()

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "NIK_COLLECTION_ID": collection_id},
    )

    finished_at = utc_now()

    return {
        "component": name,
        "script": str(script.relative_to(ROOT)),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "return_code": result.returncode,
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    print("===== NIK YOUTUBE COLLECTION =====")
    print()

    LOGS.mkdir(parents=True, exist_ok=True)

    collection_id = str(uuid.uuid4())
    collection_started = utc_now()

    # (name, script, output_dir, output_glob) -- output_dir/output_glob
    # is where find_latest_snapshot looks for the snapshot each
    # component produces, to read its snapshot_id back into this log
    # (provenance linkage pass, NIK_YOUTUBE_SNAPSHOT_SCHEMA.md).
    components = [
        (
            "channel_snapshot",
            CHANNEL_SCRIPT,
            ROOT / "data" / "snapshots",
            "channel_*.json",
        ),
        (
            "video_inventory",
            VIDEO_SCRIPT,
            ROOT / "data" / "snapshots" / "videos",
            "videos_*.json",
        ),
        (
            "analytics_snapshot",
            ANALYTICS_SCRIPT,
            ROOT / "data" / "analytics",
            "channel_analytics_*.json",
        ),
    ]

    results = []

    for name, script, output_dir, output_glob in components:
        print(f"COLLECTING: {name}")

        if not script.exists():
            result = {
                "component": name,
                "script": str(script.relative_to(ROOT)),
                "started_at_utc": utc_now(),
                "finished_at_utc": utc_now(),
                "return_code": None,
                "success": False,
                "stdout": "",
                "stderr": "Required collector script does not exist.",
            }
        else:
            result = run_component(name, script, collection_id)

        if result["success"]:
            produced_snapshot_id, produced_snapshot_path = find_latest_snapshot(
                output_dir, output_glob
            )
        else:
            produced_snapshot_id, produced_snapshot_path = None, None

        result["produced_snapshot_id"] = produced_snapshot_id
        result["produced_snapshot_path"] = produced_snapshot_path

        results.append(result)

        if result["success"]:
            print(f"RESULT: SUCCESS")
        else:
            print(f"RESULT: FAILED")

        print()

    collection_finished = utc_now()

    overall_success = all(item["success"] for item in results)

    report = {
        "schema_version": "1.0",
        "collection_type": "youtube_full_collection",
        "collection_id": collection_id,
        "collection_started_at_utc": collection_started,
        "collection_finished_at_utc": collection_finished,
        "success": overall_success,
        "components": results,
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = LOGS / f"collection_{timestamp}.json"

    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("================================")
    print()
    print(f"COLLECTION SUCCESS: {overall_success}")
    print(f"COLLECTION ID: {collection_id}")
    print(f"OUTPUT: {output}")
    print()

    return 0 if overall_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
