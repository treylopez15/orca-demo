"""
Classify Slack message authors as staff vs client using SLACK_STAFF_USER_IDS.

Set SLACK_STAFF_USER_IDS to a comma-separated list of internal Slack user IDs (e.g. U0123ABC).
When this is non-empty:
 - users in the list are treated as staff
  - any other non-empty message user id is treated as a client
When unset or empty, every author is "unknown" (no classification).

Find user IDs: Slack UI → profile → three dots → Copy member ID, or users.lookupByEmail via API.
"""

from __future__ import annotations

import os
from typing import FrozenSet, Literal, Optional

SlackRole = Literal["staff", "client", "unknown"]


def _parse_user_ids(raw: str) -> FrozenSet[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def get_staff_user_ids() -> FrozenSet[str]:
    raw = (os.getenv("SLACK_STAFF_USER_IDS") or "").strip()
    return _parse_user_ids(raw)


def classification_enabled() -> bool:
    return len(get_staff_user_ids()) > 0


def slack_user_role(slack_user_id: Optional[str]) -> SlackRole:
    if not slack_user_id:
        return "unknown"
    staff = get_staff_user_ids()
    if not staff:
        return "unknown"
    if slack_user_id in staff:
        return "staff"
    return "client"


def role_label_for_document(role: SlackRole) -> str:
    """Suffix for ingested thread lines; empty when role is unknown."""
    if role == "staff":
        return "staff"
    if role == "client":
        return "client"
    return ""
