from __future__ import annotations

import json
import subprocess
import sys
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


def run_component(name: str, script: Path) -> dict:
    started_at = utc_now()

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
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

    collection_started = utc_now()

    components = [
        ("channel_snapshot", CHANNEL_SCRIPT),
        ("video_inventory", VIDEO_SCRIPT),
        ("analytics_snapshot", ANALYTICS_SCRIPT),
    ]

    results = []

    for name, script in components:
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
            result = run_component(name, script)

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
    print(f"OUTPUT: {output}")
    print()

    return 0 if overall_success else 1


if __name__ == "__main__":
    raise SystemExit(main())