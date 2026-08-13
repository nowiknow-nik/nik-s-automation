from pathlib import Path
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collector
from collector import find_latest_snapshot


def write_snapshot(directory, filename, snapshot_id):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        json.dumps({"snapshot_id": snapshot_id}),
        encoding="utf-8",
    )
    return path


def write_fake_script(directory, filename, body):
    # B2.2f (test-only stage): a stand-in for a real API-calling child
    # script, so run_component()/main() can be exercised through a
    # real subprocess without touching the network or real quota.
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(body, encoding="utf-8")
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


# ---------------------------------------------------------
# B2.2f (test-only stage): collector.py is not modified anywhere in
# this file. These tests prove behavior the existing orchestration
# code already has -- none of them exist to make a test pass by
# changing production code. Sec 9.3's quota_denied field is explicitly
# out of scope here (see the last test below, which asserts it is
# absent) -- that remains separate, future, gated work.
# ---------------------------------------------------------

def test_main_continues_through_siblings_after_a_failure_and_reports_overall_failure(
    tmp_path, monkeypatch
):
    """
    Verification points 1-2: a non-zero-exit child -- standing in for
    any child-process failure, including an uncaught QuotaDeniedError,
    since collector.py treats every child failure identically by
    design (point 4 below) -- must (a) make main() report overall
    failure rather than a silently-successful partial collection, and
    (b) not prevent the remaining components from being attempted.
    """
    fake_root = tmp_path
    scripts_dir = fake_root / "fake_scripts"

    ok_script = write_fake_script(scripts_dir, "ok.py", "import sys\nsys.exit(0)\n")
    fail_script = write_fake_script(
        scripts_dir,
        "fail.py",
        "import sys\nprint('simulated denial', file=sys.stderr)\nsys.exit(1)\n",
    )

    monkeypatch.setattr(collector, "ROOT", fake_root)
    monkeypatch.setattr(collector, "LOGS", fake_root / "logs")
    monkeypatch.setattr(collector, "CHANNEL_SCRIPT", ok_script)
    monkeypatch.setattr(collector, "VIDEO_SCRIPT", fail_script)
    monkeypatch.setattr(collector, "ANALYTICS_SCRIPT", ok_script)

    exit_code = collector.main()

    assert exit_code == 1

    log_files = list((fake_root / "logs").glob("collection_*.json"))
    assert len(log_files) == 1
    report = json.loads(log_files[0].read_text(encoding="utf-8"))

    assert report["success"] is False

    by_component = {c["component"]: c for c in report["components"]}
    assert set(by_component) == {
        "channel_snapshot",
        "video_inventory",
        "analytics_snapshot",
    }
    assert by_component["channel_snapshot"]["success"] is True
    assert by_component["video_inventory"]["success"] is False
    assert by_component["video_inventory"]["return_code"] == 1
    # The component scheduled after the failing one still ran --
    # collector.py does not abort the loop early on a sibling's
    # failure.
    assert by_component["analytics_snapshot"]["success"] is True


def test_run_component_propagates_collection_id_to_child_env(tmp_path, monkeypatch):
    """
    Verification point 3: NIK_COLLECTION_ID must reach the child
    process's real environment, not just be constructed correctly in
    Python. Uses a real subprocess, not a mock of subprocess.run, so
    this proves the value actually crosses the process boundary.
    """
    monkeypatch.setattr(collector, "ROOT", tmp_path)
    script = write_fake_script(
        tmp_path,
        "echo_collection_id.py",
        "import os\nprint(os.environ.get('NIK_COLLECTION_ID', 'MISSING'))\n",
    )

    result = collector.run_component("fake_component", script, "test-collection-id-123")

    assert result["success"] is True
    assert result["stdout"].strip() == "test-collection-id-123"


def test_collector_module_has_no_quota_accounting_or_ledger_dependency():
    """
    Verification point 4 (Contract Sec 5.1: the per-run/daily ceilings
    are enforced independently inside each of the three governed
    scripts, never aggregated across collector.py's subprocesses --
    "no single ceiling shared across its three subprocesses"). This is
    a regression guard, not a behavioral test: it fails loudly if
    collector.py ever grows a quota_ledger import or its own copy of
    the ceiling constants, which would silently reintroduce the
    duplicate-accounting risk Sec 5.1 rules out.
    """
    source = Path(collector.__file__).read_text(encoding="utf-8")

    assert "quota_ledger" not in source
    assert "QuotaDeniedError" not in source
    assert "RUN_CEILING_UNITS" not in source
    assert "DAILY_BUDGET_UNITS" not in source


def test_main_writes_collection_log_with_expected_shape_and_no_quota_denied_field(
    tmp_path, monkeypatch
):
    """
    Verification point 5 (existing collection-log behavior stays
    intact) plus an explicit, checked record of this stage's own
    boundary: Contract Sec 9.3's quota_denied field is deliberately
    NOT implemented in this test-only stage -- asserting its absence
    means a future stage that does add it must consciously update this
    test, rather than the boundary drifting silently.
    """
    fake_root = tmp_path
    scripts_dir = fake_root / "fake_scripts"
    script = write_fake_script(scripts_dir, "ok.py", "import sys\nsys.exit(0)\n")

    monkeypatch.setattr(collector, "ROOT", fake_root)
    monkeypatch.setattr(collector, "LOGS", fake_root / "logs")
    monkeypatch.setattr(collector, "CHANNEL_SCRIPT", script)
    monkeypatch.setattr(collector, "VIDEO_SCRIPT", script)
    monkeypatch.setattr(collector, "ANALYTICS_SCRIPT", script)

    exit_code = collector.main()

    assert exit_code == 0

    log_files = list((fake_root / "logs").glob("collection_*.json"))
    assert len(log_files) == 1
    report = json.loads(log_files[0].read_text(encoding="utf-8"))

    assert report["success"] is True
    assert report["schema_version"] == "1.0"
    assert report["collection_type"] == "youtube_full_collection"
    assert "collection_id" in report
    assert len(report["components"]) == 3

    for component in report["components"]:
        assert component["success"] is True
        assert "produced_snapshot_id" in component
        assert "produced_snapshot_path" in component
        assert "quota_denied" not in component
