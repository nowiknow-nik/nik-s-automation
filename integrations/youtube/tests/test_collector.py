from pathlib import Path
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from collector import find_latest_snapshot


def write_snapshot(directory, filename, snapshot_id):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        json.dumps({"snapshot_id": snapshot_id}),
        encoding="utf-8",
    )
    return path


def test_find_latest_snapshot_returns_none_when_no_files_match(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir()

    snapshot_id, path = find_latest_snapshot(directory, "channel_*.json", root=tmp_path)

    assert snapshot_id is None
    assert path is None


def test_find_latest_snapshot_picks_newest_by_mtime(tmp_path):
    directory = tmp_path / "snapshots"

    older = write_snapshot(directory, "channel_20260101_000000.json", "older-id")
    newer = write_snapshot(directory, "channel_20260102_000000.json", "newer-id")

    # mtime, not filename, decides "newest" -- set it explicitly so the
    # test doesn't depend on how fast these two writes happened to run.
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    snapshot_id, path = find_latest_snapshot(directory, "channel_*.json", root=tmp_path)

    assert snapshot_id == "newer-id"
    assert path == str(newer.relative_to(tmp_path))


def test_find_latest_snapshot_handles_unparseable_file_without_raising(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    bad_file = directory / "channel_20260101_000000.json"
    bad_file.write_text("not valid json", encoding="utf-8")

    snapshot_id, path = find_latest_snapshot(directory, "channel_*.json", root=tmp_path)

    assert snapshot_id is None
    assert path == str(bad_file.relative_to(tmp_path))
