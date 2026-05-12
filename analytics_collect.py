"""
Fetch Slack channel + thread messages and normalize for analytics_compute.

By default scans every channel the bot can see (after SLACK_CHANNEL_IDS filter),
one history page per channel, with thread-expansion limits that scale up with
channel count. Override with env vars if Slack is large or slow.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set, Tuple

from slack_ingest import (
    SLACK_CHANNEL_IDS,
    fetch_channel_history_latest_page,
    fetch_thread,
    list_channels,
)


def _int_env(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _int_env_unset_means(name: str, computed_default: int) -> int:
    """If env is unset or blank, use computed_default; if invalid, use computed_default."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return computed_default
    try:
        v = int(str(raw).strip())
    except ValueError:
        return computed_default
    if v <= 0:
        return computed_default
    return v


def _parse_csv_ids(s: str) -> Set[str]:
    return {p.strip() for p in (s or "").split(",") if p.strip()}


def _analytics_exclude_channel_name_set() -> Set[str]:
    """
    Lowercased Slack channel names to skip in analytics only (not ingest).
    If ANALYTICS_EXCLUDE_CHANNEL_NAMES is unset, defaults to excluding apptech-braid.
    Set to empty in .env to disable: ANALYTICS_EXCLUDE_CHANNEL_NAMES=
    """
    raw = os.getenv("ANALYTICS_EXCLUDE_CHANNEL_NAMES")
    if raw is None:
        return {"apptech-braid", "apptech braid"}
    if not str(raw).strip():
        return set()
    return {p.strip().lower() for p in str(raw).split(",") if p.strip()}


def _analytics_exclude_channel_id_set() -> Set[str]:
    """Comma-separated Slack channel IDs (C…) to skip in analytics."""
    return _parse_csv_ids(os.getenv("ANALYTICS_EXCLUDE_CHANNEL_IDS") or "")


def _channel_allowed_for_analytics(
    ch: Dict[str, Any], excl_ids: Set[str], excl_names: Set[str]
) -> bool:
    cid = str(ch.get("id") or "").strip()
    if cid and cid in excl_ids:
        return False
    cname = (ch.get("name") or "").strip().lower()
    if cname and cname in excl_names:
        return False
    return True


def _normalize_slack_message(
    msg: Dict[str, Any],
    channel_id: str,
    channel_name: str = "",
) -> Dict[str, Any] | None:
    ts = msg.get("ts")
    if not ts:
        return None
    uid = (msg.get("user") or "").strip()
    text = (msg.get("text") or "").strip()
    thread_ts = msg.get("thread_ts")
    thread_id = str(thread_ts) if thread_ts else None
    try:
        stamp = float(ts)
    except (TypeError, ValueError):
        return None
    return {
        "message_id": f"{channel_id}:{ts}",
        "user_id": uid,
        "channel_id": channel_id,
        "channel_name": (channel_name or "").strip(),
        "thread_id": thread_id,
        "timestamp": stamp,
        "text": text,
    }


def collect_normalized_messages_for_analytics() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Pull a bounded sample from Slack (same channel filter rules as ingest).

    Defaults: all matching channels, one history page each, thread caps scale with
    channel count (~12–64 threads/channel, ~500–20k thread fetches total).
    Env: ANALYTICS_MAX_CHANNELS (0 or unset = all), ANALYTICS_HISTORY_DAYS,
    ANALYTICS_MAX_THREADS_PER_CHANNEL, ANALYTICS_MAX_THREAD_FETCHES_TOTAL,
    ANALYTICS_HISTORY_PAGE_LIMIT,
    ANALYTICS_EXCLUDE_CHANNEL_NAMES, ANALYTICS_EXCLUDE_CHANNEL_IDS.
    """
    all_channels = list_channels()
    filter_entries = len(SLACK_CHANNEL_IDS)
    if SLACK_CHANNEL_IDS:
        wanted = set(SLACK_CHANNEL_IDS)
        channels = [c for c in all_channels if c.get("id") in wanted]
    else:
        channels = all_channels

    excl_ids = _analytics_exclude_channel_id_set()
    excl_names = _analytics_exclude_channel_name_set()
    n_before_exclude = len(channels)
    channels = [c for c in channels if _channel_allowed_for_analytics(c, excl_ids, excl_names)]
    channels_excluded_from_analytics = n_before_exclude - len(channels)

    max_channels = _int_env("ANALYTICS_MAX_CHANNELS", 0)
    if max_channels > 0:
        channels_to_scan = channels[:max_channels]
    else:
        channels_to_scan = list(channels)

    n_scan = len(channels_to_scan)
    default_per_ch = max(12, min(64, 800 // max(n_scan, 1)))
    default_thread_total = max(500, min(20000, 150 * max(n_scan, 1)))

    history_days = _int_env("ANALYTICS_HISTORY_DAYS", 14)
    oldest: str | None = None
    if history_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=history_days)
        oldest = f"{cutoff.timestamp():.6f}"

    page_limit = _int_env("ANALYTICS_HISTORY_PAGE_LIMIT", 200)
    if page_limit <= 0:
        page_limit = 200

    per_ch_cap = _int_env_unset_means(
        "ANALYTICS_MAX_THREADS_PER_CHANNEL", default_per_ch
    )
    global_cap = _int_env_unset_means(
        "ANALYTICS_MAX_THREAD_FETCHES_TOTAL", default_thread_total
    )

    meta: Dict[str, Any] = {
        "channels_scanned": len(channels_to_scan),
        "channels_excluded_from_analytics": channels_excluded_from_analytics,
        "channels_available": len(channels),
        "channels_from_slack": len(all_channels),
        "channels_omitted": max(0, len(channels) - len(channels_to_scan)),
        "channels_capped": len(channels_to_scan) < len(channels),
        "slack_channel_filter_entries": filter_entries,
        "history_days_config": history_days,
        "history_window_active": oldest is not None,
        "history_pages": 1,
        "history_page_limit": page_limit,
        "threads_per_channel_cap": per_ch_cap,
        "threads_expanded_cap": global_cap,
        "threads_expanded": 0,
        "scanned_channels": [
            {
                "channelId": str(ch.get("id") or ""),
                "channelName": (str(ch.get("name") or "").strip() or str(ch.get("id") or "")),
            }
            for ch in channels_to_scan
            if ch.get("id")
        ],
    }

    collected: List[Dict[str, Any]] = []
    thread_expansions = 0

    for ch in channels_to_scan:
        cid = ch.get("id")
        if not cid:
            continue
        ch_name = ch.get("name") or ""
        history = fetch_channel_history_latest_page(cid, oldest=oldest, limit=page_limit)
        seen_threads: Set[str] = set()
        threads_this_channel = 0

        for msg in history:
            if thread_expansions >= global_cap:
                break
            ts = msg.get("ts")
            if not ts:
                continue
            thread_ts = msg.get("thread_ts")
            parent = str(thread_ts) if thread_ts else str(ts)
            try:
                reply_count = int(float(msg.get("reply_count") or 0))
            except (TypeError, ValueError):
                reply_count = 0

            if reply_count > 0:
                if parent not in seen_threads:
                    if threads_this_channel >= per_ch_cap:
                        continue
                    if thread_expansions >= global_cap:
                        break
                    seen_threads.add(parent)
                    for m in fetch_thread(cid, parent):
                        n = _normalize_slack_message(m, cid, ch_name)
                        if n:
                            collected.append(n)
                    threads_this_channel += 1
                    thread_expansions += 1
                continue

            if thread_ts and str(thread_ts) in seen_threads:
                continue

            if not thread_ts:
                n = _normalize_slack_message(msg, cid, ch_name)
                if n:
                    collected.append(n)
                continue

            if parent not in seen_threads:
                seen_threads.add(parent)
                n = _normalize_slack_message(msg, cid, ch_name)
                if n:
                    collected.append(n)

        if thread_expansions >= global_cap:
            break

    meta["threads_expanded"] = thread_expansions
    meta["threads_capped"] = thread_expansions >= global_cap

    return collected, meta
