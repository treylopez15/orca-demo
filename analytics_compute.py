"""
In-memory analytics: first staff response after first external message per thread,
and peak message times (7×24 heatmap). No persistence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Set

from zoneinfo import ZoneInfo


def _role(user_id: str, staff_ids: Set[str]) -> str:
    return "staff" if user_id in staff_ids else "external"


def _median_minutes(values_minutes: List[float]) -> float:
    if not values_minutes:
        return 0.0
    s = sorted(values_minutes)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


def _p90_minutes(values_minutes: List[float]) -> float:
    if not values_minutes:
        return 0.0
    s = sorted(values_minutes)
    n = len(s)
    if n == 1:
        return float(s[0])
    idx = int(0.9 * (n - 1))
    return float(s[idx])


def _dow_sunday_zero(local_dt: datetime) -> int:
    """0 = Sunday … 6 = Saturday (matches typical JS getDay())."""
    return (local_dt.weekday() + 1) % 7


def _in_business_window_et(unix_sec: float) -> bool:
    """
    Business window for response-time metrics:
    Monday–Friday, 8:00 AM through 5:59 PM Eastern Time.
    """
    et = ZoneInfo("America/New_York")
    dt = datetime.fromtimestamp(unix_sec, tz=et)
    is_weekday = dt.weekday() <= 4  # Monday=0 ... Friday=4
    is_business_hour = 8 <= dt.hour < 18
    return is_weekday and is_business_hour


def compute_analytics_snapshot(
    messages: List[Dict[str, Any]],
    staff_ids: List[str],
    timezone_name: str,
) -> Dict[str, Any]:
    """
    messages: dicts with message_id, user_id, channel_id, thread_id, timestamp, text
    timestamp: unix seconds (float ok)
    """
    staff_set: Set[str] = set(staff_ids)
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")

    total = len(messages)

    heatmap: List[List[int]] = [[0 for _ in range(24)] for _ in range(7)]
    heatmap_timestamps: List[float] = []
    for m in messages:
        ts = m.get("timestamp")
        if ts is None:
            continue
        try:
            sec = float(ts)
        except (TypeError, ValueError):
            continue
        dt = datetime.fromtimestamp(sec, tz=tz)
        dow = _dow_sunday_zero(dt)
        hour = dt.hour
        heatmap[dow][hour] += 1
        heatmap_timestamps.append(sec)

    by_thread: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for m in messages:
        tid = m.get("thread_id")
        if tid is None:
            continue
        by_thread[str(tid)].append(m)

    response_times_min: List[float] = []

    for tid, arr in by_thread.items():
        rows = sorted(arr, key=lambda x: float(x.get("timestamp") or 0.0))
        rows = [
            r
            for r in rows
            if _in_business_window_et(float(r.get("timestamp") or 0.0))
        ]
        if not rows:
            continue
        first_ext_i = None
        for i, row in enumerate(rows):
            uid = (row.get("user_id") or "").strip()
            if _role(uid, staff_set) == "external":
                first_ext_i = i
                break
        if first_ext_i is None:
            continue
        ext_ts = float(rows[first_ext_i].get("timestamp") or 0.0)
        staff_ts = None
        for j in range(first_ext_i + 1, len(rows)):
            uid = (rows[j].get("user_id") or "").strip()
            if _role(uid, staff_set) == "staff":
                staff_ts = float(rows[j].get("timestamp") or 0.0)
                break
        if staff_ts is None:
            continue
        delta_sec = staff_ts - ext_ts
        if delta_sec < 0:
            continue
        delta_min = delta_sec / 60.0
        response_times_min.append(delta_min)

    follow_up_response_times_min: List[float] = []
    for _tid, arr in by_thread.items():
        rows = sorted(arr, key=lambda x: float(x.get("timestamp") or 0.0))
        rows = [
            r
            for r in rows
            if _in_business_window_et(float(r.get("timestamp") or 0.0))
        ]
        if not rows:
            continue
        first_ext_i: int | None = None
        for i, row in enumerate(rows):
            uid = (row.get("user_id") or "").strip()
            if _role(uid, staff_set) == "external":
                first_ext_i = i
                break
        first_staff_j: int | None = None
        if first_ext_i is not None:
            for j in range(first_ext_i + 1, len(rows)):
                uid = (rows[j].get("user_id") or "").strip()
                if _role(uid, staff_set) == "staff":
                    first_staff_j = j
                    break

        for i, row in enumerate(rows):
            uid_i = (row.get("user_id") or "").strip()
            if _role(uid_i, staff_set) != "external":
                continue
            staff_j: int | None = None
            for j in range(i + 1, len(rows)):
                uid_j = (rows[j].get("user_id") or "").strip()
                if _role(uid_j, staff_set) == "staff":
                    staff_j = j
                    break
            if staff_j is None:
                continue
            if (
                first_ext_i is not None
                and first_staff_j is not None
                and i == first_ext_i
                and staff_j == first_staff_j
            ):
                continue
            ext_ts = float(row.get("timestamp") or 0.0)
            st_ts = float(rows[staff_j].get("timestamp") or 0.0)
            delta_sec = st_ts - ext_ts
            if delta_sec < 0:
                continue
            follow_up_response_times_min.append(delta_sec / 60.0)

    if response_times_min:
        avg = sum(response_times_min) / len(response_times_min)
        med = _median_minutes(response_times_min)
        p90 = _p90_minutes(response_times_min)
    else:
        avg = med = p90 = 0.0

    if follow_up_response_times_min:
        avg_fu = sum(follow_up_response_times_min) / len(follow_up_response_times_min)
        med_fu = _median_minutes(follow_up_response_times_min)
    else:
        avg_fu = med_fu = 0.0

    analytics_messages: List[Dict[str, Any]] = []
    for m in messages:
        uid = (m.get("user_id") or "").strip()
        ts = m.get("timestamp")
        try:
            tsf = float(ts)
        except (TypeError, ValueError):
            continue
        cid = str(m.get("channel_id") or "")
        cname_raw = m.get("channel_name")
        cname = (cname_raw.strip() if isinstance(cname_raw, str) else "") or cid
        tid = m.get("thread_id")
        mid = m.get("message_id")
        analytics_messages.append(
            {
                "channelId": cid,
                "channelName": cname or cid,
                "threadId": tid,
                "userId": uid,
                "timestamp": tsf,
                "role": _role(uid, staff_set),
                "messageId": mid,
            }
        )

    return {
        "avgResponseTime": round(avg, 4),
        "medianResponseTime": round(med, 4),
        "p90ResponseTime": round(p90, 4),
        "avgFollowUpResponseTime": round(avg_fu, 4),
        "medianFollowUpResponseTime": round(med_fu, 4),
        "totalMessages": total,
        "heatmap": heatmap,
        "heatmapTimestamps": heatmap_timestamps,
        "analyticsMessages": analytics_messages,
    }
