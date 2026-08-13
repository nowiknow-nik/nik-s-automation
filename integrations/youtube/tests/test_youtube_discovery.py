from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import quota_ledger
import youtube_discovery
from youtube_discovery import QuotaDeniedError


# ---------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------

SAMPLE_CHANNEL_RESPONSE = {
    "items": [
        {
            "id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "snippet": {"title": "Sample Channel"},
            "contentDetails": {
                "relatedPlaylists": {"uploads": "UUsample000000000000000"},
            },
        }
    ]
}

SAMPLE_CHANNEL_RESPONSE_NO_UPLOADS = {
    "items": [
        {
            "id": "UCn4OmZFMasYBkmCx6Q2oUBQ",
            "snippet": {"title": "Sample Channel"},
            "contentDetails": {"relatedPlaylists": {}},
        }
    ]
}

SAMPLE_PLAYLISTS_RESPONSE = {"items": [{"id": "PLsample000000000000000"}]}
SAMPLE_PLAYLIST_ITEMS_RESPONSE = {"items": [{"id": "itemsample0000000000000"}]}
SAMPLE_SEARCH_RESPONSE = {"items": [{"id": {"videoId": "vidsample000000000000"}}]}


def _fake_youtube(channel=None, playlists=None, playlist_items=None, search=None):
    """
    A minimal stand-in for the googleapiclient youtube resource, deep
    enough to support youtube.<resource>().list(...).execute() for all
    four resources this file calls. Each of channel/playlists/
    playlist_items/search is either a dict (used as .execute()'s
    return value) or an Exception instance (used as .execute()'s
    side_effect). None leaves that resource unconfigured -- safe for
    tests that never reach that call.
    """
    youtube = MagicMock()
    for attr, value in (
        ("channels", channel),
        ("playlists", playlists),
        ("playlistItems", playlist_items),
        ("search", search),
    ):
        execute = getattr(youtube, attr).return_value.list.return_value.execute
        if isinstance(value, Exception):
            execute.side_effect = value
        elif value is not None:
            execute.return_value = value
    return youtube


def _seed_known_cost_usage(path, estimated_cost_units, script="other_script.py"):
    """
    Appends one allowed known-cost pre_call_check event carrying an
    arbitrary estimated_cost_units, so compute_known_cost_usage() can
    be pushed to a chosen total without writing many individual
    entries. Defaults to a different script than this file's own, so
    it never contaminates a most_recent_invocation_timestamp lookup
    scoped to "youtube_discovery.py" -- mirrors
    test_channel_snapshot.py's identically-named helper.
    """
    quota_ledger.write_pre_call_event(
        script=script,
        operation="channels.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=estimated_cost_units,
        pre_call_check={
            "remaining_run_ceiling_before_call": 1,
            "remaining_daily_budget_before_call": 1,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )


def _seed_search_usage(path, count, script="other_script.py"):
    """
    Appends `count` allowed search.list pre_call_check events, to push
    compute_search_usage() to a chosen total. Defaults to a different
    script than this file's own for the same reason as
    _seed_known_cost_usage above -- compute_search_usage() is not
    script-scoped (it counts the operation globally, matching Google's
    own per-project allocation model), but
    most_recent_invocation_timestamp() is, so seeding under a
    different script name keeps this helper from also poisoning a
    cooldown lookup for "youtube_discovery.py".
    """
    for _ in range(count):
        quota_ledger.write_pre_call_event(
            script=script,
            operation="search.list",
            collection_id=None,
            cost_model=quota_ledger.KNOWN_COST_MODEL,
            estimated_cost_units=1,
            pre_call_check={
                "remaining_run_ceiling_before_call": 1,
                "remaining_search_allocation_before_call": 1,
                "cooldown_ok": True,
                "binding": None,
                "decision": quota_ledger.ALLOWED,
            },
            path=path,
        )


def _patch_main_environment(monkeypatch, tmp_path, youtube):
    """
    Redirects every external touchpoint main() has to tmp_path / the
    given fake youtube resource: the ledger, the output file location,
    credentials, and the googleapiclient build() call. Returns
    (ledger_path, output_file).
    """
    ledger_path = tmp_path / "quota_ledger.jsonl"
    log_dir = tmp_path / "logs"
    output_file = log_dir / "youtube_capability_discovery.json"

    monkeypatch.setattr(quota_ledger, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr(youtube_discovery, "LOG_DIR", log_dir)
    monkeypatch.setattr(youtube_discovery, "OUTPUT_FILE", output_file)
    monkeypatch.setattr(youtube_discovery, "get_credentials", lambda: MagicMock())
    monkeypatch.setattr(youtube_discovery, "build", lambda *a, **kw: youtube)

    return ledger_path, output_file


# ---------------------------------------------------------------------
# _compute_invocation_cooldown_ok
# ---------------------------------------------------------------------

def test_cooldown_ok_when_no_prior_invocation(tmp_path):
    path = tmp_path / "ledger.jsonl"

    assert youtube_discovery._compute_invocation_cooldown_ok(path, quota_ledger.utc_now()) is True


def test_cooldown_not_ok_when_last_invocation_too_recent(tmp_path):
    path = tmp_path / "ledger.jsonl"
    quota_ledger.write_pre_call_event(
        script="youtube_discovery.py",
        operation="channels.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check={
            "remaining_run_ceiling_before_call": 49,
            "remaining_daily_budget_before_call": 999,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )

    assert youtube_discovery._compute_invocation_cooldown_ok(path, quota_ledger.utc_now()) is False


def test_cooldown_ok_when_last_invocation_old_enough(tmp_path):
    path = tmp_path / "ledger.jsonl"
    old_time = datetime(2026, 8, 13, 6, 0, 0, tzinfo=timezone.utc)
    with patch("quota_ledger.utc_now", return_value=old_time):
        quota_ledger.write_pre_call_event(
            script="youtube_discovery.py",
            operation="channels.list",
            collection_id=None,
            cost_model=quota_ledger.KNOWN_COST_MODEL,
            estimated_cost_units=1,
            pre_call_check={
                "remaining_run_ceiling_before_call": 49,
                "remaining_daily_budget_before_call": 999,
                "cooldown_ok": True,
                "binding": None,
                "decision": quota_ledger.ALLOWED,
            },
            path=path,
        )

    now = old_time + timedelta(hours=1)
    assert youtube_discovery._compute_invocation_cooldown_ok(path, now) is True


def test_cooldown_ignores_other_scripts(tmp_path):
    """
    A recent invocation of a *different* script must not hold this
    script's own cooldown down -- most_recent_invocation_timestamp()
    is script-scoped by design.
    """
    path = tmp_path / "ledger.jsonl"
    quota_ledger.write_pre_call_event(
        script="channel_snapshot.py",
        operation="channels.list",
        collection_id=None,
        cost_model=quota_ledger.KNOWN_COST_MODEL,
        estimated_cost_units=1,
        pre_call_check={
            "remaining_run_ceiling_before_call": 49,
            "remaining_daily_budget_before_call": 999,
            "cooldown_ok": True,
            "binding": None,
            "decision": quota_ledger.ALLOWED,
        },
        path=path,
    )

    assert youtube_discovery._compute_invocation_cooldown_ok(path, quota_ledger.utc_now()) is True


# ---------------------------------------------------------------------
# _evaluate_known_cost_pre_call_check
# ---------------------------------------------------------------------

def test_known_cost_allowed_baseline(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = youtube_discovery._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert result == {
        "remaining_run_ceiling_before_call": 50,
        "remaining_daily_budget_before_call": 1000,
        "cooldown_ok": True,
        "binding": None,
        "decision": "allowed",
    }


def test_known_cost_denied_run_ceiling(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = youtube_discovery._evaluate_known_cost_pre_call_check(
        run_ceiling_used=50, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"
    assert result["remaining_run_ceiling_before_call"] == 0


def test_known_cost_denied_daily_budget(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(path, estimated_cost_units=1000)

    result = youtube_discovery._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "daily_budget"
    assert result["remaining_daily_budget_before_call"] == 0


def test_known_cost_denied_cooldown(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = youtube_discovery._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, cooldown_ok=False, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "cooldown"
    assert result["cooldown_ok"] is False


def test_known_cost_run_ceiling_checked_before_daily_budget(tmp_path):
    """Contract Sec 6 lists the run ceiling (a) before the daily budget (b)."""
    path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(path, estimated_cost_units=1000)

    result = youtube_discovery._evaluate_known_cost_pre_call_check(
        run_ceiling_used=50, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"


def test_known_cost_unaffected_by_search_usage(tmp_path):
    """
    Ledger Schema Sec 10.1 / Contract Sec 2: search.list usage must
    never bleed into the shared known-cost pool's accounting.
    """
    path = tmp_path / "ledger.jsonl"
    _seed_search_usage(path, count=100)

    result = youtube_discovery._evaluate_known_cost_pre_call_check(
        run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert result["decision"] == "allowed"
    assert result["remaining_daily_budget_before_call"] == 1000


# ---------------------------------------------------------------------
# _evaluate_search_pre_call_check
# ---------------------------------------------------------------------

def test_search_allowed_baseline(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = youtube_discovery._evaluate_search_pre_call_check(
        run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert result == {
        "remaining_run_ceiling_before_call": 50,
        "remaining_search_allocation_before_call": 100,
        "cooldown_ok": True,
        "binding": None,
        "decision": "allowed",
    }


def test_search_denied_run_ceiling(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = youtube_discovery._evaluate_search_pre_call_check(
        run_ceiling_used=50, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"


def test_search_denied_search_allocation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed_search_usage(path, count=100)

    result = youtube_discovery._evaluate_search_pre_call_check(
        run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "search_allocation"
    assert result["remaining_search_allocation_before_call"] == 0


def test_search_denied_cooldown(tmp_path):
    path = tmp_path / "ledger.jsonl"

    result = youtube_discovery._evaluate_search_pre_call_check(
        run_ceiling_used=0, cooldown_ok=False, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "cooldown"


def test_search_run_ceiling_checked_before_search_allocation(tmp_path):
    """Contract Sec 6 lists the run ceiling (a) before the search allocation (b)."""
    path = tmp_path / "ledger.jsonl"
    _seed_search_usage(path, count=100)

    result = youtube_discovery._evaluate_search_pre_call_check(
        run_ceiling_used=50, cooldown_ok=True, path=path
    )

    assert result["decision"] == "denied"
    assert result["binding"] == "run_ceiling"


def test_search_unaffected_by_daily_budget_exhaustion(tmp_path):
    """
    Contract Sec 6: "search.list must never be checked against the
    daily budget in Sec 5.2 -- checking it there would be exactly the
    silent conflation Sec 2 prohibits." Exhausting the known-cost
    shared pool must not deny search.list.
    """
    path = tmp_path / "ledger.jsonl"
    _seed_known_cost_usage(path, estimated_cost_units=1000)

    result = youtube_discovery._evaluate_search_pre_call_check(
        run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert result["decision"] == "allowed"
    assert "remaining_daily_budget_before_call" not in result


# ---------------------------------------------------------------------
# discover_channel
# ---------------------------------------------------------------------

def test_discover_channel_allowed_executes_and_returns_response_and_incremented_counter(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=SAMPLE_CHANNEL_RESPONSE)

    response, run_ceiling_used = youtube_discovery.discover_channel(
        youtube, run_ceiling_used=0, cooldown_ok=True, path=path
    )

    assert response == SAMPLE_CHANNEL_RESPONSE
    assert run_ceiling_used == 1
    youtube.channels.return_value.list.return_value.execute.assert_called_once()


def test_discover_channel_denied_does_not_execute(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=SAMPLE_CHANNEL_RESPONSE)

    with pytest.raises(QuotaDeniedError):
        youtube_discovery.discover_channel(
            youtube, run_ceiling_used=50, cooldown_ok=True, path=path
        )

    youtube.channels.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=path)
    assert len(entries) == 1
    assert entries[0]["pre_call_check"]["decision"] == "denied"
    assert entries[0]["pre_call_check"]["binding"] == "run_ceiling"


def test_discover_channel_pre_call_write_failure_prevents_execute(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=SAMPLE_CHANNEL_RESPONSE)

    def _raise(*args, **kwargs):
        raise OSError("simulated pre-call ledger write failure")

    monkeypatch.setattr(youtube_discovery.quota_ledger, "write_pre_call_event", _raise)

    with pytest.raises(OSError):
        youtube_discovery.discover_channel(
            youtube, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    youtube.channels.return_value.list.return_value.execute.assert_not_called()


def test_discover_channel_success_writes_success_post_call_event(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=SAMPLE_CHANNEL_RESPONSE)

    youtube_discovery.discover_channel(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    post = next(e for e in entries if e["event_type"] == "post_call_result")

    assert len(entries) == 2
    assert post["call_id"] == pre["call_id"]
    assert post["outcome"] == "success"
    assert post["error"] is None


def test_discover_channel_api_failure_writes_failure_post_call_event_and_reraises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=RuntimeError("simulated API failure"))

    with pytest.raises(RuntimeError, match="simulated API failure"):
        youtube_discovery.discover_channel(
            youtube, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")

    assert post["outcome"] == "failure"
    assert "simulated API failure" in post["error"]


def test_discover_channel_collection_id_passthrough(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=SAMPLE_CHANNEL_RESPONSE)

    youtube_discovery.discover_channel(
        youtube, run_ceiling_used=0, cooldown_ok=True, collection_id="a-collection-run-id", path=path
    )

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")

    assert pre["collection_id"] == "a-collection-run-id"


def test_discover_channel_query_parameters_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(channel=SAMPLE_CHANNEL_RESPONSE)

    youtube_discovery.discover_channel(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    youtube.channels.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,statistics,brandingSettings",
        id="UCn4OmZFMasYBkmCx6Q2oUBQ",
    )


# ---------------------------------------------------------------------
# discover_playlists
# ---------------------------------------------------------------------

def test_discover_playlists_allowed_executes_and_increments_counter(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlists=SAMPLE_PLAYLISTS_RESPONSE)

    response, run_ceiling_used = youtube_discovery.discover_playlists(
        youtube, run_ceiling_used=1, cooldown_ok=True, path=path
    )

    assert response == SAMPLE_PLAYLISTS_RESPONSE
    assert run_ceiling_used == 2
    youtube.playlists.return_value.list.return_value.execute.assert_called_once()


def test_discover_playlists_denied_does_not_execute(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlists=SAMPLE_PLAYLISTS_RESPONSE)

    with pytest.raises(QuotaDeniedError):
        youtube_discovery.discover_playlists(
            youtube, run_ceiling_used=0, cooldown_ok=False, path=path
        )

    youtube.playlists.return_value.list.return_value.execute.assert_not_called()


def test_discover_playlists_success_writes_success_post_call_event(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlists=SAMPLE_PLAYLISTS_RESPONSE)

    youtube_discovery.discover_playlists(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "success"


def test_discover_playlists_api_failure_writes_failure_post_call_event_and_reraises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlists=RuntimeError("simulated API failure"))

    with pytest.raises(RuntimeError, match="simulated API failure"):
        youtube_discovery.discover_playlists(
            youtube, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "failure"


def test_discover_playlists_query_parameters_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlists=SAMPLE_PLAYLISTS_RESPONSE)

    youtube_discovery.discover_playlists(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    youtube.playlists.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,status",
        channelId="UCn4OmZFMasYBkmCx6Q2oUBQ",
        maxResults=50,
    )


# ---------------------------------------------------------------------
# discover_playlist_items
# ---------------------------------------------------------------------

def test_discover_playlist_items_allowed_executes_and_increments_counter(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE)

    response, run_ceiling_used = youtube_discovery.discover_playlist_items(
        youtube, "UUsample000000000000000", run_ceiling_used=2, cooldown_ok=True, path=path
    )

    assert response == SAMPLE_PLAYLIST_ITEMS_RESPONSE
    assert run_ceiling_used == 3
    youtube.playlistItems.return_value.list.return_value.execute.assert_called_once()


def test_discover_playlist_items_denied_does_not_execute(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE)

    with pytest.raises(QuotaDeniedError):
        youtube_discovery.discover_playlist_items(
            youtube, "UUsample000000000000000", run_ceiling_used=50, cooldown_ok=True, path=path
        )

    youtube.playlistItems.return_value.list.return_value.execute.assert_not_called()


def test_discover_playlist_items_success_writes_success_post_call_event(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE)

    youtube_discovery.discover_playlist_items(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "success"


def test_discover_playlist_items_api_failure_writes_failure_post_call_event_and_reraises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=RuntimeError("simulated API failure"))

    with pytest.raises(RuntimeError, match="simulated API failure"):
        youtube_discovery.discover_playlist_items(
            youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
        )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "failure"


def test_discover_playlist_items_query_parameters_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE)

    youtube_discovery.discover_playlist_items(
        youtube, "UUsample000000000000000", run_ceiling_used=0, cooldown_ok=True, path=path
    )

    youtube.playlistItems.return_value.list.assert_called_once_with(
        part="snippet,contentDetails,status",
        playlistId="UUsample000000000000000",
        maxResults=50,
    )


# ---------------------------------------------------------------------
# discover_search_results
# ---------------------------------------------------------------------

def test_discover_search_results_allowed_executes_and_increments_counter(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(search=SAMPLE_SEARCH_RESPONSE)

    response, run_ceiling_used = youtube_discovery.discover_search_results(
        youtube, run_ceiling_used=3, cooldown_ok=True, path=path
    )

    assert response == SAMPLE_SEARCH_RESPONSE
    assert run_ceiling_used == 4
    youtube.search.return_value.list.return_value.execute.assert_called_once()


def test_discover_search_results_denied_does_not_execute(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(search=SAMPLE_SEARCH_RESPONSE)
    _seed_search_usage(path, count=100)

    with pytest.raises(QuotaDeniedError):
        youtube_discovery.discover_search_results(
            youtube, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    youtube.search.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=path)
    denial = [e for e in entries if e["operation"] == "search.list" and e["pre_call_check"]["decision"] == "denied"]
    assert len(denial) == 1
    assert denial[0]["pre_call_check"]["binding"] == "search_allocation"


def test_discover_search_results_success_writes_success_post_call_event(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(search=SAMPLE_SEARCH_RESPONSE)

    youtube_discovery.discover_search_results(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "success"


def test_discover_search_results_api_failure_writes_failure_post_call_event_and_reraises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(search=RuntimeError("simulated API failure"))

    with pytest.raises(RuntimeError, match="simulated API failure"):
        youtube_discovery.discover_search_results(
            youtube, run_ceiling_used=0, cooldown_ok=True, path=path
        )

    entries = quota_ledger.read_entries(path=path)
    post = next(e for e in entries if e["event_type"] == "post_call_result")
    assert post["outcome"] == "failure"


def test_discover_search_results_query_parameters_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(search=SAMPLE_SEARCH_RESPONSE)

    youtube_discovery.discover_search_results(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    youtube.search.return_value.list.assert_called_once_with(
        part="snippet",
        channelId="UCn4OmZFMasYBkmCx6Q2oUBQ",
        type="video",
        maxResults=10,
    )


def test_discover_search_results_operation_recorded_as_known_cost_model(tmp_path):
    """search.list is cost_model 'known' (Contract Sec 4.1) even though it is excluded from the shared pool."""
    path = tmp_path / "ledger.jsonl"
    youtube = _fake_youtube(search=SAMPLE_SEARCH_RESPONSE)

    youtube_discovery.discover_search_results(youtube, run_ceiling_used=0, cooldown_ok=True, path=path)

    entries = quota_ledger.read_entries(path=path)
    pre = next(e for e in entries if e["event_type"] == "pre_call_check")
    assert pre["cost_model"] == "known"
    assert pre["estimated_cost_units"] == 1


# ---------------------------------------------------------------------
# main() -- full invocation integration
# ---------------------------------------------------------------------

def test_main_all_four_calls_succeed_without_self_denying_on_cooldown(tmp_path, monkeypatch):
    """
    Regression test for the B2.2d Sec 5.1 finding: this is the first
    script in the codebase to make more than one governed call per
    invocation. If cooldown_ok were (re-)derived fresh inside each
    call's own pre-call check -- the channel_snapshot.py/
    analytics_snapshot.py pattern -- call 2 would see call 1's own
    just-written pre-call event, milliseconds old, and spuriously deny
    itself on cooldown grounds. This exercises all four real calls in
    sequence, with real ledger writes landing between them (nothing
    about quota_ledger itself is mocked), and asserts every one
    succeeds and is recorded as cooldown_ok.
    """
    youtube = _fake_youtube(
        channel=SAMPLE_CHANNEL_RESPONSE,
        playlists=SAMPLE_PLAYLISTS_RESPONSE,
        playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE,
        search=SAMPLE_SEARCH_RESPONSE,
    )
    ledger_path, output_file = _patch_main_environment(monkeypatch, tmp_path, youtube)

    youtube_discovery.main()

    for mock in (
        youtube.channels.return_value.list.return_value.execute,
        youtube.playlists.return_value.list.return_value.execute,
        youtube.playlistItems.return_value.list.return_value.execute,
        youtube.search.return_value.list.return_value.execute,
    ):
        mock.assert_called_once()

    assert output_file.exists()

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    assert len(pre_call_events) == 4
    assert all(e["pre_call_check"]["decision"] == "allowed" for e in pre_call_events)
    assert all(e["pre_call_check"]["cooldown_ok"] is True for e in pre_call_events)


def test_main_run_ceiling_threads_correctly_across_all_four_calls(tmp_path, monkeypatch):
    youtube = _fake_youtube(
        channel=SAMPLE_CHANNEL_RESPONSE,
        playlists=SAMPLE_PLAYLISTS_RESPONSE,
        playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE,
        search=SAMPLE_SEARCH_RESPONSE,
    )
    ledger_path, output_file = _patch_main_environment(monkeypatch, tmp_path, youtube)

    youtube_discovery.main()

    entries = quota_ledger.read_entries(path=ledger_path)
    pre_call_events = [e for e in entries if e["event_type"] == "pre_call_check"]
    remaining_by_operation = {
        e["operation"]: e["pre_call_check"]["remaining_run_ceiling_before_call"]
        for e in pre_call_events
    }

    assert remaining_by_operation == {
        "channels.list": 50,
        "playlists.list": 49,
        "playlistItems.list": 48,
        "search.list": 47,
    }


def test_main_skips_playlist_items_when_no_uploads_playlist(tmp_path, monkeypatch):
    """Preserves the pre-existing conditional behavior: playlistItems.list only runs if an uploads playlist id was found."""
    youtube = _fake_youtube(
        channel=SAMPLE_CHANNEL_RESPONSE_NO_UPLOADS,
        playlists=SAMPLE_PLAYLISTS_RESPONSE,
        search=SAMPLE_SEARCH_RESPONSE,
    )
    ledger_path, output_file = _patch_main_environment(monkeypatch, tmp_path, youtube)

    youtube_discovery.main()

    youtube.playlistItems.return_value.list.return_value.execute.assert_not_called()

    entries = quota_ledger.read_entries(path=ledger_path)
    operations = [e["operation"] for e in entries if e["event_type"] == "pre_call_check"]
    assert operations == ["channels.list", "playlists.list", "search.list"]

    result = __import__("json").loads(output_file.read_text(encoding="utf-8"))
    assert result["uploads_playlist_id"] is None
    assert result["capabilities_tested"]["uploads_playlist"] is False


def test_main_denial_on_last_call_discards_entire_run(tmp_path, monkeypatch):
    """
    Sec 5.6: all four results are combined into one dict, written once
    at the end. A denial on the fourth call (search.list) must discard
    the entire run -- including the three results that already
    succeeded moments earlier -- not just skip search's own output.
    """
    youtube = _fake_youtube(
        channel=SAMPLE_CHANNEL_RESPONSE,
        playlists=SAMPLE_PLAYLISTS_RESPONSE,
        playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE,
        search=SAMPLE_SEARCH_RESPONSE,
    )
    ledger_path, output_file = _patch_main_environment(monkeypatch, tmp_path, youtube)

    # Exhausts the rolling-24h search allocation before main() runs,
    # under a different script name so it doesn't also poison this
    # invocation's own cooldown lookup.
    _seed_search_usage(ledger_path, count=100)

    with pytest.raises(QuotaDeniedError):
        youtube_discovery.main()

    youtube.search.return_value.list.return_value.execute.assert_not_called()
    assert not output_file.exists()

    # The first three calls did happen and succeed -- the discard is
    # about the combined result never being written, not about the
    # earlier calls being skipped.
    youtube.channels.return_value.list.return_value.execute.assert_called_once()
    youtube.playlists.return_value.list.return_value.execute.assert_called_once()
    youtube.playlistItems.return_value.list.return_value.execute.assert_called_once()


def test_main_api_failure_on_last_call_also_discards_entire_run(tmp_path, monkeypatch):
    """Same as above, but the failure is an API exception rather than a governance denial -- Sec 7.3/Sec 10 cover both."""
    youtube = _fake_youtube(
        channel=SAMPLE_CHANNEL_RESPONSE,
        playlists=SAMPLE_PLAYLISTS_RESPONSE,
        playlist_items=SAMPLE_PLAYLIST_ITEMS_RESPONSE,
        search=RuntimeError("simulated API failure"),
    )
    ledger_path, output_file = _patch_main_environment(monkeypatch, tmp_path, youtube)

    with pytest.raises(RuntimeError, match="simulated API failure"):
        youtube_discovery.main()

    assert not output_file.exists()
