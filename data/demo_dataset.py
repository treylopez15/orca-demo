"""
Synthetic Slack-like messages and API traffic for DEMO_MODE.

Shapes match analytics_collect normalization + analytics_compute / insights_compute.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from analytics_compute import compute_analytics_snapshot
from insights_compute import compute_insights_snapshot

ET = ZoneInfo("America/New_York")
STAFF = "U_STAFF_DEMO"
CLIENT = "U_CLIENT_DEMO"

# Channel ids + Slack-style names (UI may mask sensitive names in demo)
CHANNELS: List[Tuple[str, str]] = [
    ("C_APEX", "apex-pay-api"),
    ("C_NORTH", "northstar-fin-support"),
    ("C_HORIZ", "horizon-labs-integration"),
    ("C_VERT", "vertex-treasury-dev"),
    ("C_BLUE", "bluepeak-capital-ops"),
    ("C_MAK", "makeba-support"),
    ("C_NUV", "nuvion-braid"),
]


def _ts(dt: datetime) -> float:
    return dt.timestamp()


def _msg(
    channel_id: str,
    channel_name: str,
    thread_id: str,
    dt: datetime,
    user_id: str,
    text: str = "",
) -> Dict[str, Any]:
    stamp = _ts(dt)
    return {
        "message_id": f"{channel_id}:{stamp:.6f}",
        "user_id": user_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "thread_id": thread_id,
        "timestamp": stamp,
        "text": text,
    }


def _weekday_slots() -> List[datetime]:
    """Roughly two weeks of weekday 9–16 ET slots (May 4–22, 2026)."""
    out: List[datetime] = []
    d0 = datetime(2026, 5, 4, 9, 5, tzinfo=ET)
    for i in range(18):
        d = d0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        for hour in (9, 11, 14, 16):
            out.append(d.replace(hour=hour, minute=10, second=0, microsecond=0))
    return out


def _build_messages() -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []
    slots = _weekday_slots()
    si = 0

    def next_slot() -> datetime:
        nonlocal si
        s = slots[si % len(slots)]
        si += 1
        return s

    # --- Vertex: many repeats of the same question (high repeated-question signal) ---
    vert_q = "What is error INVALID_ROUTING and how do we fix routing table mismatch?"
    for t in range(14):
        base = next_slot()
        tid = f"vert-r{t}"
        msgs.append(_msg("C_VERT", "vertex-treasury-dev", tid, base, CLIENT, vert_q))
        msgs.append(
            _msg(
                "C_VERT",
                "vertex-treasury-dev",
                tid,
                base + timedelta(minutes=9 + (t % 4)),
                STAFF,
                "Check routing config and retry settlement batch.",
            )
        )

    # --- Horizon: strong follow-up delays ---
    for t in range(10):
        base = next_slot()
        tid = f"horiz-fu{t}"
        msgs.append(_msg("C_HORIZ", "horizon-labs-integration", tid, base, CLIENT, "Webhook retries failing?"))
        msgs.append(
            _msg(
                "C_HORIZ",
                "horizon-labs-integration",
                tid,
                base + timedelta(minutes=7),
                STAFF,
                "We are looking.",
            )
        )
        msgs.append(
            _msg(
                "C_HORIZ",
                "horizon-labs-integration",
                tid,
                base + timedelta(minutes=40),
                CLIENT,
                "Still failing after redeploy.",
            )
        )
        msgs.append(
            _msg(
                "C_HORIZ",
                "horizon-labs-integration",
                tid,
                base + timedelta(minutes=40 + 85 + (t % 3) * 12),
                STAFF,
                "Increase timeout on partner endpoint and replay DLQ.",
            )
        )

    # --- General traffic for remaining channels (first + occasional follow-up) ---
    generic_q = "Can you confirm sandbox credentials rotation window?"
    for cid, cname in CHANNELS:
        if cid in ("C_VERT", "C_HORIZ"):
            continue
        for t in range(8):
            base = next_slot()
            tid = f"{cid}-th{t}"
            msgs.append(_msg(cid, cname, tid, base, CLIENT, generic_q if t % 3 else "Status on batch posting?"))
            msgs.append(
                _msg(
                    cid,
                    cname,
                    tid,
                    base + timedelta(minutes=6 + (t % 5)),
                    STAFF,
                    "Credentials rotate Sunday 02:00 ET; no downtime expected.",
                )
            )
            if t % 4 == 0:
                msgs.append(
                    _msg(
                        cid,
                        cname,
                        tid,
                        base + timedelta(minutes=25),
                        CLIENT,
                        "Thanks — follow up on idempotency key TTL?",
                    )
                )
                msgs.append(
                    _msg(
                        cid,
                        cname,
                        tid,
                        base + timedelta(minutes=35),
                        STAFF,
                        "TTL is 24h for sandbox.",
                    )
                )

    # --- Error-like tokens for insights ---
    msgs.append(
        _msg(
            "C_BLUE",
            "bluepeak-capital-ops",
            "blue-err",
            next_slot(),
            CLIENT,
            "Seeing PAYMENT_REJECTED and SETTLEMENT_TIMEOUT in logs — ideas?",
        )
    )
    msgs.append(
        _msg(
            "C_BLUE",
            "bluepeak-capital-ops",
            "blue-err",
            next_slot(),
            STAFF,
            "PAYMENT_REJECTED maps to insufficient hold; SETTLEMENT_TIMEOUT is partner side.",
        )
    )

    return msgs


def _build_traffic() -> List[Dict[str, Any]]:
    """Synthetic API hits per channel; shapes UI getApiTrafficActivityRows()."""
    rows: List[Dict[str, Any]] = []
    endpoints = ["/v1/transfers", "/v1/accounts", "/v1/settlements", "/v1/webhooks"]
    base = datetime(2026, 5, 4, 10, 0, tzinfo=ET)

    for day in range(14):
        d = base + timedelta(days=day)
        if d.weekday() >= 5:
            continue
        # ApexPay: low early, strong spike in last ~4 weekdays
        n_apex = 6 + (day % 3) if day < 9 else 48 + day * 2
        # Northstar: busy early, quiet later (stalled / drop-off)
        n_north = 44 - day * 3 if day < 10 else max(2, 5 - day // 3)
        # Others: moderate steady volume
        n_mid = 14 + (day % 4)

        for i in range(max(1, n_apex)):
            dt = d.replace(hour=10, minute=min(55, 10 + i), second=0)
            rows.append(
                {
                    "channel_id": "C_APEX",
                    "timestamp": _ts(dt),
                    "endpoint": endpoints[i % len(endpoints)],
                }
            )
        for i in range(max(1, n_north)):
            dt = d.replace(hour=13, minute=min(55, 12 + i), second=0)
            rows.append(
                {
                    "channel_id": "C_NORTH",
                    "timestamp": _ts(dt),
                    "endpoint": endpoints[(i + 1) % len(endpoints)],
                }
            )
        for cid in ("C_HORIZ", "C_VERT", "C_BLUE", "C_MAK", "C_NUV"):
            for i in range(n_mid):
                dt = d.replace(hour=15, minute=min(55, 8 + i), second=0)
                rows.append(
                    {
                        "channel_id": cid,
                        "timestamp": _ts(dt),
                        "endpoint": endpoints[(i + day) % len(endpoints)],
                    }
                )
    return rows


_demo_bundles: Tuple[Dict[str, Any], Dict[str, Any]] | None = None


def get_demo_bundles() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    global _demo_bundles
    if _demo_bundles is None:
        _demo_bundles = build_demo_analytics_and_insights()
    return _demo_bundles


def build_demo_analytics_and_insights() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    messages = _build_messages()
    traffic = _build_traffic()
    staff = [STAFF]
    tz = (os.getenv("ANALYTICS_TIMEZONE") or "America/New_York").strip() or "America/New_York"

    snap = compute_analytics_snapshot(messages, staff, tz)
    ins = compute_insights_snapshot(messages, staff)

    scanned = [{"channelId": cid, "channelName": nm} for cid, nm in CHANNELS]
    meta: Dict[str, Any] = {
        "channelsScanned": len(scanned),
        "channelsFromSlack": len(scanned),
        "channelsAvailable": len(scanned),
        "channelsOmitted": 0,
        "channelsCapped": False,
        "channelsExcludedFromAnalytics": 0,
        "slackChannelFilterEntries": 0,
        "staffIdsConfigured": True,
        "threadsExpanded": min(120, len(messages)),
        "threadsExpandedCap": 2000,
        "threadsPerChannelCap": 32,
        "threadsCapped": False,
        "historyDaysConfig": 14,
        "historyWindowActive": True,
        "historyPages": 1,
        "historyPageLimit": 200,
        "analyticsTimezoneApplied": tz,
        "analyticsScannedChannels": scanned,
        "apiTrafficActivity": traffic,
    }
    snap.update(meta)

    ins.update(
        {
            "messagesScanned": len(messages),
            "channelsScanned": len(scanned),
            "staffIdsConfigured": True,
        }
    )
    return snap, ins
