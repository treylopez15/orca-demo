import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).resolve().parent / ".env")

from db import init_db, insert_thread, get_latest_thread_ts, composite_thread_id
from rag import generate_embedding
from slack_roles import slack_user_role, role_label_for_document


SLACK_BOT_TOKEN = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
SLACK_READ_TOKEN = (os.getenv("SLACK_READ_TOKEN") or SLACK_BOT_TOKEN).strip()


def _extract_slack_channel_id(token: str) -> str | None:
    """Accept bare C…/G… IDs, <#C…|label>, or archive URLs."""
    t = token.strip()
    if not t:
        return None
    if t.startswith("<#"):
        inner = t[2:].split(">", 1)[0]
        inner = inner.split("|", 1)[0].strip()
        return inner or None
    m = re.search(r"/archives/([A-Z0-9]{9,})", t, re.I)
    if m:
        return m.group(1).upper()
    compact = re.sub(r"\s+", "", t)
    m = re.match(r"^([CG][A-Z0-9]{8,})$", compact, re.I)
    if m:
        return m.group(1).upper()
    return compact


def _parse_slack_channel_ids_env() -> List[str]:
    raw = (os.getenv("SLACK_CHANNEL_IDS") or "").strip()
    if not raw:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for piece in raw.split(","):
        cid = _extract_slack_channel_id(piece)
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _parse_staff_user_names_env() -> Dict[str, str]:
    """
    Optional manual mapping:
      SLACK_STAFF_USER_NAMES=U123:Alice,U456:Bob
    """
    raw = (os.getenv("SLACK_STAFF_USER_NAMES") or "").strip()
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for piece in raw.split(","):
        p = piece.strip()
        if not p or ":" not in p:
            continue
        uid, name = p.split(":", 1)
        uid = uid.strip()
        name = name.strip()
        if uid and name:
            out[uid] = name
    return out


SLACK_CHANNEL_IDS = _parse_slack_channel_ids_env()
SLACK_STAFF_USER_NAMES = _parse_staff_user_names_env()

SLACK_API_BASE_URL = "https://slack.com/api"


def _get_headers(token_kind: str = "read") -> Dict[str, str]:
    if token_kind == "write":
        token = SLACK_BOT_TOKEN
        env_name = "SLACK_BOT_TOKEN"
    else:
        token = SLACK_READ_TOKEN
        env_name = "SLACK_READ_TOKEN (or SLACK_BOT_TOKEN)"
    if not token:
        raise RuntimeError(f"{env_name} environment variable is not set")
    return {"Authorization": f"Bearer {token}"}


def _slack_get(method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Slack Web API GET with retries on HTTP 429 and transient ok:false errors.
    Analytics + ingest can burst many conversations.replies calls; rate limits are common.
    """
    url = f"{SLACK_API_BASE_URL}/{method}"
    max_attempts = 10
    for attempt in range(max_attempts):
        resp = requests.get(url, headers=_get_headers("read"), params=params or {}, timeout=60)
        if resp.status_code == 429:
            try:
                wait = float(resp.headers.get("Retry-After", str(1 + attempt * 2)))
            except (TypeError, ValueError):
                wait = 1.0 + attempt * 2.0
            time.sleep(min(max(wait, 1.0), 120.0))
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data
        err = data.get("error") or "unknown_error"
        if err in ("ratelimited", "service_unavailable", "internal_error"):
            time.sleep(min(1.0 + attempt * 2.0, 60.0))
            continue
        needed = str(data.get("needed") or "").strip()
        provided = str(data.get("provided") or "").strip()
        scope_hint = (
            f" (needed: {needed}; provided: {provided})" if needed or provided else ""
        )
        raise RuntimeError(f"Slack API error calling {method}: {err}{scope_hint}")
    raise RuntimeError(f"Slack API still rate limited after {max_attempts} attempts ({method})")


def _slack_post(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Slack Web API POST with retries on HTTP 429 and transient ok:false errors.
    """
    url = f"{SLACK_API_BASE_URL}/{method}"
    max_attempts = 10
    for attempt in range(max_attempts):
        resp = requests.post(url, headers=_get_headers("write"), json=payload, timeout=60)
        if resp.status_code == 429:
            try:
                wait = float(resp.headers.get("Retry-After", str(1 + attempt * 2)))
            except (TypeError, ValueError):
                wait = 1.0 + attempt * 2.0
            time.sleep(min(max(wait, 1.0), 120.0))
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data
        err = data.get("error") or "unknown_error"
        if err in ("ratelimited", "service_unavailable", "internal_error"):
            time.sleep(min(1.0 + attempt * 2.0, 60.0))
            continue
        needed = str(data.get("needed") or "").strip()
        provided = str(data.get("provided") or "").strip()
        scope_hint = (
            f" (needed: {needed}; provided: {provided})" if needed or provided else ""
        )
        raise RuntimeError(f"Slack API error calling {method}: {err}{scope_hint}")
    raise RuntimeError(f"Slack API still rate limited after {max_attempts} attempts ({method})")


def get_workspace_identity() -> Tuple[str, str]:
    """
    Return (workspace_domain, team_id) for building URLs and tagging rows.
    """
    data = _slack_get("auth.test")
    url = data.get("url", "")
    team_id = data.get("team_id", "")
    workspace = url.split("https://")[-1].split(".slack.com")[0] if ".slack.com" in url else data.get("team", "")
    return workspace, team_id


def get_token_scopes() -> Dict[str, Any]:
    """
    Inspect token scopes using auth.test response headers.
    """
    url = f"{SLACK_API_BASE_URL}/auth.test"
    resp = requests.get(url, headers=_get_headers("write"), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        err = data.get("error") or "unknown_error"
        raise RuntimeError(f"Slack API error calling auth.test: {err}")

    raw_scopes = str(resp.headers.get("x-oauth-scopes") or "")
    raw_accepted = str(resp.headers.get("x-accepted-oauth-scopes") or "")
    scopes = [s.strip() for s in raw_scopes.split(",") if s.strip()]
    accepted_scopes = [s.strip() for s in raw_accepted.split(",") if s.strip()]
    return {"scopes": scopes, "accepted_scopes": accepted_scopes}


def list_channels() -> List[Dict[str, Any]]:
    """
    List all channels accessible to the bot, handling pagination.
    """
    channels: List[Dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: Dict[str, Any] = {
            "limit": 200,
            # Default API behavior is public_channel only; include private so ingest + analytics see member channels.
            "types": "public_channel,private_channel",
        }
        if cursor:
            params["cursor"] = cursor
        data = _slack_get("conversations.list", params=params)
        channels.extend(data.get("channels", []))
        cursor = data.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    return channels


def list_broadcast_channels() -> List[Dict[str, str]]:
    """
    Return broadcast-safe channel list (id + display name) for UI.
    """
    out: List[Dict[str, str]] = []
    for ch in list_channels():
        channel_id = str(ch.get("id") or "").strip()
        if not channel_id:
            continue
        name = str(ch.get("name") or "").strip()
        display_name = f"#{name}" if name else channel_id
        out.append({"id": channel_id, "name": display_name})
    out.sort(key=lambda r: r["name"].lower())
    return out


def send_broadcast_message(channel_id: str, text: str) -> Dict[str, Any]:
    """
    Send one message to a Slack channel via chat.postMessage.
    """
    return _slack_post(
        "chat.postMessage",
        {
            "channel": channel_id,
            "text": text,
        },
    )


def resolve_user_display_names(user_ids: List[str]) -> Dict[str, str]:
    """
    Best-effort user_id -> display name resolution.
    Uses optional env map first, then Slack users.info (requires users:read).
    """
    out: Dict[str, str] = {}
    wanted = []
    for uid in user_ids:
        u = str(uid or "").strip()
        if not u:
            continue
        if u in out:
            continue
        if u in SLACK_STAFF_USER_NAMES:
            out[u] = SLACK_STAFF_USER_NAMES[u]
        else:
            wanted.append(u)

    if not wanted:
        return out

    # Try live lookup. If users:read is missing, stop gracefully.
    for uid in wanted:
        try:
            resp = requests.get(
                f"{SLACK_API_BASE_URL}/users.info",
                headers=_get_headers("read"),
                params={"user": uid},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                err = str(data.get("error") or "")
                if err == "missing_scope":
                    break
                continue
            user = data.get("user") or {}
            profile = user.get("profile") or {}
            display = (
                str(profile.get("display_name") or "").strip()
                or str(profile.get("real_name") or "").strip()
                or str(user.get("real_name") or "").strip()
                or str(user.get("name") or "").strip()
            )
            if display:
                out[uid] = display
        except Exception:
            continue
    return out


def fetch_channel_history_latest_page(
    channel_id: str,
    oldest: str | None = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Single conversations.history page (no cursor pagination). For fast analytics.
    """
    lim = max(1, min(int(limit), 200))
    params: Dict[str, Any] = {"channel": channel_id, "limit": lim}
    if oldest:
        params["oldest"] = oldest
    data = _slack_get("conversations.history", params=params)
    return data.get("messages", [])


def fetch_channel_messages(channel_id: str, oldest: str | None = None) -> List[Dict[str, Any]]:
    """
    Fetch messages from a Slack channel using conversations.history.
    Simple implementation: fetches a single page (latest messages).
    If oldest is provided, Slack will return messages newer than that timestamp.
    """
    params: Dict[str, Any] = {
        "channel": channel_id,
        "limit": 100,
    }
    if oldest:
        params["oldest"] = oldest
    data = _slack_get("conversations.history", params=params)
    return data.get("messages", [])


def fetch_channel_history_all_pages(
    channel_id: str,
    oldest: str | None = None,
    max_pages: int | None = None,
) -> List[Dict[str, Any]]:
    """
    Paginated conversations.history for a channel (newest page first per Slack).
    Used for analytics; not tied to ingest cursors.

    oldest: optional Unix timestamp string — only messages newer than this.
    max_pages: stop after this many pages (200 msgs/page) to avoid unbounded scans.
    """
    out: List[Dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: Dict[str, Any] = {"channel": channel_id, "limit": 200}
        if oldest:
            params["oldest"] = oldest
        if cursor:
            params["cursor"] = cursor
        data = _slack_get("conversations.history", params=params)
        out.extend(data.get("messages", []))
        pages += 1
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if max_pages is not None and pages >= max_pages:
            break
        if not cursor:
            break
    return out


def is_thread_root(message: Dict[str, Any]) -> bool:
    ts = message.get("ts")
    thread_ts = message.get("thread_ts")
    return ts is not None and thread_ts is not None and ts == thread_ts


def fetch_thread(channel_id: str, thread_ts: str) -> List[Dict[str, Any]]:
    params = {"channel": channel_id, "ts": thread_ts}
    data = _slack_get("conversations.replies", params=params)
    return data.get("messages", [])


def build_thread_document(messages: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for msg in messages:
        uid = msg.get("user")
        user = uid or msg.get("username") or "unknown"
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        label = role_label_for_document(slack_user_role(uid if uid else None))
        if label:
            lines.append(f"{user} ({label}): {text}")
        else:
            lines.append(f"{user}: {text}")
    return "\n".join(lines)


def _thread_source_url(workspace: str, channel_id: str, thread_ts: str) -> str:
    safe_ts = thread_ts.replace(".", "")
    return f"https://{workspace}.slack.com/archives/{channel_id}/p{safe_ts}"


def _ingest_one_channel(workspace: str, channel_id: str, channel_name: str) -> Dict[str, Any]:
    latest_ts = get_latest_thread_ts(channel_id)
    messages = fetch_channel_messages(channel_id, oldest=latest_ts)

    seen_thread_ids: set[str] = set()
    inserted = 0
    skipped = 0

    for msg in messages:
        if not is_thread_root(msg):
            continue
        thread_ts = msg.get("thread_ts") or msg.get("ts")
        if not thread_ts or thread_ts in seen_thread_ids:
            continue
        seen_thread_ids.add(thread_ts)

        thread_messages = fetch_thread(channel_id, thread_ts)
        doc_text = build_thread_document(thread_messages)
        if not doc_text:
            continue

        url = _thread_source_url(workspace, channel_id, thread_ts)

        embedding = generate_embedding(doc_text)
        thread_id = composite_thread_id(workspace, channel_id, thread_ts)

        if insert_thread(
            thread_id=thread_id,
            workspace=workspace,
            channel_id=channel_id,
            channel_name=channel_name,
            thread_ts=thread_ts,
            text=doc_text,
            embedding=embedding,
            url=url,
        ):
            inserted += 1
        else:
            skipped += 1

    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "threads_seen": len(seen_thread_ids),
        "inserted": inserted,
        "skipped": skipped,
    }


def ingest_slack_messages() -> Dict[str, Any]:
    """
    Initialize DB, fetch Slack threads (one or many channels), embed and store them.
    Uses SLACK_CHANNEL_IDS (comma-separated) if set; otherwise all channels returned by conversations.list.
    """
    if not SLACK_READ_TOKEN:
        raise RuntimeError("SLACK_READ_TOKEN (or SLACK_BOT_TOKEN) environment variable is not set")

    init_db()
    workspace, _team_id = get_workspace_identity()

    all_channels = list_channels()
    if SLACK_CHANNEL_IDS:
        wanted = set(SLACK_CHANNEL_IDS)
        channels = [c for c in all_channels if c.get("id") in wanted]
    else:
        channels = all_channels

    results: List[Dict[str, Any]] = []
    total_threads = 0
    total_inserted = 0
    total_skipped = 0

    for ch in channels:
        cid = ch.get("id")
        name = ch.get("name") or ""
        if not cid:
            continue
        summary = _ingest_one_channel(workspace, cid, name)
        results.append(summary)
        total_threads += summary["threads_seen"]
        total_inserted += summary["inserted"]
        total_skipped += summary["skipped"]

    return {
        "workspace": workspace,
        "channels": results,
        "total_threads_seen": total_threads,
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
    }


if __name__ == "__main__":
    summary = ingest_slack_messages()
    print(summary)

