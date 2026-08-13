"""
NIK YouTube quota ledger (Stage B1).

Implements the append-only, two-event-per-call design specified in
NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md v1.1 and governed by
NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md.

Scope: this module is the ledger only. Nothing here is called by
channel_snapshot.py, video_inventory.py, analytics_snapshot.py,
youtube_discovery.py, or collector.py yet, and no API-calling behavior
is changed by this file's existence. Integration is Stage B2, separate,
future work requiring its own approval.

This module does not decide whether to allow or deny a call. It writes
events, and it answers "how much has been used in a window" and "when
was this script last invoked." A future Stage B2 caller compares those
answers against the limits in NIK_YOUTUBE_QUOTA_GOVERNANCE_CONTRACT.md
Sec 5 and decides allow/deny -- this module supplies facts, not policy.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEDGER_SCHEMA_VERSION = "1.1"

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "logs" / "quota_ledger.jsonl"

KNOWN_COST_MODEL = "known"
DYNAMIC_COST_MODEL = "dynamic"
_VALID_COST_MODELS = (KNOWN_COST_MODEL, DYNAMIC_COST_MODEL)

PRE_CALL_EVENT = "pre_call_check"
POST_CALL_EVENT = "post_call_result"

ALLOWED = "allowed"
DENIED = "denied"
_VALID_DECISIONS = (ALLOWED, DENIED)

_VALID_OUTCOMES = ("success", "failure")


class LedgerReadError(Exception):
    """
    Raised when the ledger cannot be read and the reason is NOT simply
    "the file has never been created." Per NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md
    Sec 10.4, a caller implementing enforcement (Stage B2, not this
    module) must treat this as fail-closed: deny the call, rather than
    treat unknown usage as zero usage. This module raises; it does not
    itself deny anything -- see read_entries()'s docstring for exactly
    which failures raise this and which do not.
    """


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_str(dt: datetime) -> str:
    return dt.isoformat()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _append(entry: dict, path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def write_pre_call_event(
    script: str,
    operation: str,
    collection_id: str | None,
    cost_model: str,
    estimated_cost_units: int | None,
    pre_call_check: dict,
    path: Path = LEDGER_PATH,
) -> str:
    """
    Writes a pre_call_check event per NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md
    Sec 6.2, before the API call is made. Returns the new call_id.

    pre_call_check must contain "decision" ("allowed" or "denied"),
    plus either "remaining_budget_before_call" (cost_model == "known")
    or "policy" (cost_model == "dynamic"), per the schema's two shapes.
    This function validates cost_model and decision; it does not
    further validate pre_call_check's shape beyond that, to avoid this
    module being more prescriptive than Stage B2 enforcement design has
    settled yet.

    Callers: for a denied call, this is the only event ever written for
    this call_id -- do not call write_post_call_event afterward
    (Schema Sec 7). For an allowed call, the caller makes the actual
    API call next, then calls write_post_call_event with the returned
    call_id, whether the call succeeded or failed.
    """
    if cost_model not in _VALID_COST_MODELS:
        raise ValueError(f"unknown cost_model: {cost_model!r}")

    decision = pre_call_check.get("decision")
    if decision not in _VALID_DECISIONS:
        raise ValueError(
            f"pre_call_check['decision'] must be 'allowed' or 'denied', "
            f"got {decision!r}"
        )

    call_id = str(uuid.uuid4())
    entry = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "entry_id": str(uuid.uuid4()),
        "call_id": call_id,
        "event_type": PRE_CALL_EVENT,
        "timestamp_utc": _timestamp_str(utc_now()),
        "script": script,
        "operation": operation,
        "collection_id": collection_id,
        "cost_model": cost_model,
        "estimated_cost_units": estimated_cost_units,
        "pre_call_check": pre_call_check,
    }
    _append(entry, path=path)
    return call_id


def write_post_call_event(
    call_id: str,
    outcome: str,
    error: str | None,
    actual_cost_units: int | None = None,
    path: Path = LEDGER_PATH,
) -> None:
    """
    Writes a post_call_result event per NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md
    Sec 6.3, after the API call returns or fails. Must only be called
    for a call_id whose pre_call_check event had decision == "allowed"
    (Schema Sec 7) -- this function does not verify that itself, since
    doing so would require reading the whole ledger on every write;
    callers are responsible for only calling this after actually making
    an allowed API call.

    Must be called on failure as well as success (Schema Sec 6.3): a
    failed call may still have consumed quota, and an honest record
    requires the failure to be recorded, not just successes.

    actual_cost_units defaults to None: whether Google's API responses
    expose actually-consumed quota in a client-visible way has not been
    independently verified (Schema Sec 6.3), so nothing should populate
    this with a guessed value.
    """
    if outcome not in _VALID_OUTCOMES:
        raise ValueError(f"outcome must be 'success' or 'failure', got {outcome!r}")

    entry = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "entry_id": str(uuid.uuid4()),
        "call_id": call_id,
        "event_type": POST_CALL_EVENT,
        "timestamp_utc": _timestamp_str(utc_now()),
        "outcome": outcome,
        "error": error,
        "actual_cost_units": actual_cost_units,
    }
    _append(entry, path=path)


def read_entries(path: Path = LEDGER_PATH) -> list[dict]:
    """
    Read every entry in the ledger, oldest first.

    FLAGGED DESIGN DECISION -- goes beyond schema v1.1's literal text
    (see the human-facing report this module was delivered with): a
    ledger file that has never been created is treated as zero prior
    entries, not as a failure. Schema Sec 10.4 says a "missing" ledger
    should fail closed, grouped together with "unreadable, or otherwise
    inaccessible." Taken completely literally, that would mean the very
    first call this project ever makes, after enforcement exists, is
    permanently denied -- nothing could ever succeed to create the
    first entry, so the file could never stop being "missing." This
    function instead distinguishes "never existed" (safe: legitimately
    zero history, the same true fact a brand-new deployment actually
    has) from "exists but can't be read" (unsafe: real prior usage
    could be silently hidden) -- only the second case raises
    LedgerReadError.

    A malformed FINAL line (e.g. an interrupted append) is skipped, per
    Schema Sec 10.3. A malformed line that is NOT the final line raises
    LedgerReadError instead of being silently skipped -- schema v1.1
    does not explicitly address this case; treating it the same as an
    interrupted final write would risk hiding real corruption in the
    middle of the file, which fail-closed governance should not paper
    over.
    """
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise LedgerReadError(f"could not read ledger at {path}: {exc}") from exc

    entries: list[dict] = []
    last_index = len(raw_lines) - 1
    for i, line in enumerate(raw_lines):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if i == last_index:
                continue
            raise LedgerReadError(
                f"malformed non-final line {i + 1} in {path}: {exc}"
            ) from exc
    return entries


def _in_window(entry: dict, window_start: datetime, window_end: datetime) -> bool:
    ts = _parse_timestamp(entry["timestamp_utc"])
    return window_start <= ts <= window_end


def compute_known_cost_usage(
    entries: list[dict],
    window_start: datetime,
    window_end: datetime,
) -> int:
    """
    Sum estimated_cost_units across pre_call_check events where
    cost_model == "known" and decision == "allowed", timestamped within
    [window_start, window_end].

    Deliberately does not look for a matching post_call_result event --
    per NIK_YOUTUBE_QUOTA_LEDGER_SCHEMA.md Sec 10.1/10.2, an allowed
    pre-call event counts whether or not a post-call event ever
    follows. This is the property that makes the whole two-event design
    worthwhile: an interrupted process cannot make a real, quota-
    consuming API call disappear from quota accounting. There is no
    separate "orphan detection" step -- this is the only accounting
    pass, and it already has this property by construction.

    A "denied" pre-call event is excluded: a denied call consumed no
    real quota, because no API call was made.
    """
    total = 0
    for entry in entries:
        if entry.get("event_type") != PRE_CALL_EVENT:
            continue
        if entry.get("cost_model") != KNOWN_COST_MODEL:
            continue
        if entry.get("pre_call_check", {}).get("decision") != ALLOWED:
            continue
        if not _in_window(entry, window_start, window_end):
            continue
        # Direct indexing, not .get(..., 0): a known-cost, allowed
        # pre-call event is required by the schema to carry a real
        # integer here. A missing or null value is corrupt data, and
        # should raise loudly rather than be silently counted as zero.
        total += entry["estimated_cost_units"]
    return total


def known_cost_usage_last_24h(
    path: Path = LEDGER_PATH, now: datetime | None = None
) -> int:
    """Convenience wrapper: reads the ledger and sums known-cost usage in the trailing rolling 24 hours."""
    now = now or utc_now()
    entries = read_entries(path)
    return compute_known_cost_usage(entries, now - timedelta(hours=24), now)


def compute_analytics_call_count(
    entries: list[dict],
    window_start: datetime,
    window_end: datetime,
    script: str = "analytics_snapshot.py",
) -> int:
    """
    Count pre_call_check events for the given script where
    cost_model == "dynamic" and decision == "allowed", timestamped
    within [window_start, window_end]. Same allowed-pre-call-only
    principle as compute_known_cost_usage -- an orphaned allowed
    Analytics attempt still counts toward the frequency ceiling
    (Quota Governance Contract Sec 5.4), for the same reason.
    """
    count = 0
    for entry in entries:
        if entry.get("event_type") != PRE_CALL_EVENT:
            continue
        if entry.get("script") != script:
            continue
        if entry.get("cost_model") != DYNAMIC_COST_MODEL:
            continue
        if entry.get("pre_call_check", {}).get("decision") != ALLOWED:
            continue
        if not _in_window(entry, window_start, window_end):
            continue
        count += 1
    return count


def analytics_call_count_last_24h(
    path: Path = LEDGER_PATH,
    now: datetime | None = None,
    script: str = "analytics_snapshot.py",
) -> int:
    """Convenience wrapper: reads the ledger and counts allowed Analytics pre-call events in the trailing rolling 24 hours."""
    now = now or utc_now()
    entries = read_entries(path)
    return compute_analytics_call_count(
        entries, now - timedelta(hours=24), now, script=script
    )


def most_recent_invocation_timestamp(
    entries: list[dict], script: str
) -> datetime | None:
    """
    Most recent pre_call_check event's timestamp for the given script,
    regardless of decision (allowed or denied). Returns None if no such
    event exists.

    FLAGGED DESIGN DECISION: including denied attempts is an
    interpretive choice, not something schema v1.1 or the contract
    states explicitly. A denied attempt still means the script was
    invoked, and the contract's Sec 5.3/5.4 cooldown reads as being
    about invocation frequency, not specifically about successful
    calls. This is a building block for a future Stage B2 cooldown
    check, not a cooldown enforcement decision itself -- Stage B1's
    approved scope did not explicitly call for cooldown reading, but it
    is included here as a small, directly-related extension, since
    Sec 5.3/5.4 cooldowns are already-approved policy this ledger
    exists to serve.
    """
    latest: datetime | None = None
    for entry in entries:
        if entry.get("event_type") != PRE_CALL_EVENT:
            continue
        if entry.get("script") != script:
            continue
        ts = _parse_timestamp(entry["timestamp_utc"])
        if latest is None or ts > latest:
            latest = ts
    return latest
