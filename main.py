import os
import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orca_config import is_demo_mode
from db import init_db, get_channel_name_map
from slack_ingest import (
    ingest_slack_messages,
    list_broadcast_channels,
    send_broadcast_message,
    get_token_scopes,
)
from rag import answer_question
from slack_roles import get_staff_user_ids
from analytics_collect import collect_normalized_messages_for_analytics
from analytics_compute import compute_analytics_snapshot
from insights_compute import compute_insights_snapshot


app = FastAPI()

DEMO_SIMULATED_MSG = "Demo mode: action simulated successfully."


class AskRequest(BaseModel):
    question: str


class BroadcastSendRequest(BaseModel):
    channel_ids: list[str]
    message: str
    as_announcement: bool = False


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/config")
def api_config() -> Dict[str, Any]:
    """Public UI bootstrap flags (no secrets)."""
    return {"demoMode": is_demo_mode()}


@app.get("/health")
def health() -> Dict[str, Any]:
    """Load balancer / ops probe; no secrets."""
    return {"status": "ok", "demoMode": is_demo_mode()}


@app.post("/ingest")
def ingest() -> Dict[str, Any]:
    """
    Trigger Slack ingestion. Pulls newest messages and stores them with embeddings.
    """
    if is_demo_mode():
        return {
            "status": "ok",
            "success": True,
            "message": DEMO_SIMULATED_MSG,
            "summary": {
                "total_threads_seen": 0,
                "total_inserted": 0,
                "total_skipped": 0,
                "demo": True,
            },
        }
    try:
        summary = ingest_slack_messages()
        return {"status": "ok", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/roles/status")
def roles_status() -> Dict[str, Any]:
    """
    Whether staff vs client classification is active (SLACK_STAFF_USER_IDS set).
    Does not return raw user IDs.
    """
    if is_demo_mode():
        return {
            "classification_enabled": True,
            "staff_user_id_count": 2,
            "demo": True,
        }
    staff = get_staff_user_ids()
    return {
        "classification_enabled": len(staff) > 0,
        "staff_user_id_count": len(staff),
    }


@app.get("/api/broadcast/channels")
def broadcast_channels() -> Dict[str, Any]:
    """
    List channels available to the bot for broadcast targeting.
    """
    if is_demo_mode():
        return {
            "channels": [
                {"id": "C_APEX", "name": "#apex-pay-api"},
                {"id": "C_NORTH", "name": "#northstar-fin-support"},
                {"id": "C_HORIZ", "name": "#horizon-labs-integration"},
                {"id": "C_VERT", "name": "#vertex-treasury-dev"},
                {"id": "C_BLUE", "name": "#bluepeak-capital-ops"},
                {"id": "C_MAK", "name": "#makeba-support"},
                {"id": "C_NUV", "name": "#nuvion-braid"},
            ],
            "source": "demo",
            "demo": True,
        }
    try:
        channels = list_broadcast_channels()
        return {"channels": channels, "source": "slack_api"}
    except Exception as e:
        # Fallback: if read scopes are missing, still allow broadcast using configured IDs.
        raw = (os.getenv("SLACK_CHANNEL_IDS") or "").strip()
        fallback_ids = [c.strip() for c in raw.split(",") if c.strip()]
        fallback_ids = list(dict.fromkeys(fallback_ids))
        if fallback_ids:
            name_map = get_channel_name_map(fallback_ids)
            fallback_channels = []
            for cid in fallback_ids:
                channel_name = (name_map.get(cid) or "").strip()
                label = f"#{channel_name}" if channel_name else cid
                fallback_channels.append({"id": cid, "name": label})
            return {
                "channels": fallback_channels,
                "source": "env_fallback",
                "warning": (
                    "Could not load channel names from Slack API. Add channels:read/groups:read "
                    "scopes for name lookup, or continue using configured channel IDs."
                ),
                "error": str(e),
            }
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/broadcast/preflight")
def broadcast_preflight() -> Dict[str, Any]:
    """
    Return token scope readiness for broadcast posting.
    """
    if is_demo_mode():
        return {
            "ok": True,
            "has_chat_write": True,
            "has_chat_write_public": True,
            "scopes": ["chat:write", "chat:write.public"],
            "demo": True,
        }
    try:
        scope_info = get_token_scopes()
        scopes = set(scope_info.get("scopes", []))
        return {
            "ok": True,
            "has_chat_write": "chat:write" in scopes,
            "has_chat_write_public": "chat:write.public" in scopes,
            "scopes": sorted(scopes),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/broadcast/send")
def broadcast_send(body: BroadcastSendRequest) -> Dict[str, Any]:
    """
    Send one message to multiple channels via chat.postMessage.
    """
    if is_demo_mode():
        channel_ids = [c.strip() for c in body.channel_ids if isinstance(c, str) and c.strip()]
        channel_ids = list(dict.fromkeys(channel_ids))
        return {
            "attempted": len(channel_ids),
            "success_count": len(channel_ids),
            "failure_count": 0,
            "results": [
                {"channel_id": cid, "success": True, "ts": "demo", "demo": True} for cid in channel_ids
            ],
            "success": True,
            "message": DEMO_SIMULATED_MSG,
            "demo": True,
        }
    channel_ids = [c.strip() for c in body.channel_ids if isinstance(c, str) and c.strip()]
    channel_ids = list(dict.fromkeys(channel_ids))
    if not channel_ids:
        raise HTTPException(status_code=400, detail="Select at least one channel")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message must not be empty")

    prefix = "📢 " if body.as_announcement else ""
    final_message = f"{prefix}{message}"
    if len(final_message) > 40000:
        raise HTTPException(status_code=400, detail="Message is too long for Slack")

    results: list[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    delay_seconds = 0.4

    for idx, channel_id in enumerate(channel_ids):
        if idx > 0:
            time.sleep(delay_seconds)
        try:
            resp = send_broadcast_message(channel_id=channel_id, text=final_message)
            results.append(
                {
                    "channel_id": channel_id,
                    "success": True,
                    "ts": resp.get("ts"),
                }
            )
            success_count += 1
        except Exception as e:
            results.append(
                {
                    "channel_id": channel_id,
                    "success": False,
                    "error": str(e),
                }
            )
            failure_count += 1

    return {
        "attempted": len(channel_ids),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }


@app.get("/api/analytics/summary")
def analytics_summary() -> Dict[str, Any]:
    """
    First response time (per thread) and peak message heatmap from live Slack fetch.
    Timezone: ANALYTICS_TIMEZONE (IANA). Slack sample — see analytics_collect env vars (defaults scan all bot channels).
    """
    if is_demo_mode():
        from data.demo_dataset import get_demo_bundles

        out, _ = get_demo_bundles()
        merged = dict(out)
        merged["demo"] = True
        return merged
    messages, scan_meta = collect_normalized_messages_for_analytics()
    staff = list(get_staff_user_ids())
    tz = (os.getenv("ANALYTICS_TIMEZONE") or "America/New_York").strip() or "America/New_York"
    try:
        out = compute_analytics_snapshot(messages, staff, tz)
        out["channelsScanned"] = scan_meta["channels_scanned"]
        out["channelsFromSlack"] = scan_meta["channels_from_slack"]
        out["channelsAvailable"] = scan_meta.get("channels_available", scan_meta["channels_scanned"])
        out["channelsOmitted"] = scan_meta.get("channels_omitted", 0)
        out["channelsCapped"] = scan_meta.get("channels_capped", False)
        out["channelsExcludedFromAnalytics"] = scan_meta.get(
            "channels_excluded_from_analytics", 0
        )
        out["slackChannelFilterEntries"] = scan_meta["slack_channel_filter_entries"]
        out["staffIdsConfigured"] = len(staff) > 0
        out["threadsExpanded"] = scan_meta["threads_expanded"]
        out["threadsExpandedCap"] = scan_meta["threads_expanded_cap"]
        out["threadsPerChannelCap"] = scan_meta.get("threads_per_channel_cap", 8)
        out["threadsCapped"] = scan_meta["threads_capped"]
        out["historyDaysConfig"] = scan_meta["history_days_config"]
        out["historyWindowActive"] = scan_meta["history_window_active"]
        out["historyPages"] = scan_meta.get("history_pages", 1)
        out["historyPageLimit"] = scan_meta.get("history_page_limit", 200)
        out["analyticsTimezoneApplied"] = tz
        out["analyticsScannedChannels"] = scan_meta.get("scanned_channels", [])
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/insights/summary")
def insights_summary() -> Dict[str, Any]:
    """
    Repeated questions, ALL_CAPS error-like tokens, and high-friction topics from the
    same Slack sample as analytics (see analytics_collect env vars).
    """
    if is_demo_mode():
        from data.demo_dataset import get_demo_bundles

        _, ins = get_demo_bundles()
        merged = dict(ins)
        merged["demo"] = True
        return merged
    messages, scan_meta = collect_normalized_messages_for_analytics()
    staff = list(get_staff_user_ids())
    try:
        out = compute_insights_snapshot(messages, staff)
        out["messagesScanned"] = len(messages)
        out["channelsScanned"] = scan_meta["channels_scanned"]
        out["staffIdsConfigured"] = len(staff) > 0
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask")
def ask(body: AskRequest) -> Dict[str, Any]:
    """
    Answer a user question using RAG over Slack history.
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty")

    if is_demo_mode():
        return {
            "answer": DEMO_SIMULATED_MSG,
            "success": True,
            "message": DEMO_SIMULATED_MSG,
            "demo": True,
        }

    try:
        answer = answer_question(body.question)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/companies")
def companies_summary() -> Dict[str, Any]:
    """
    Optional partner-style company rollup for demos. Empty when not in DEMO_MODE.
    """
    if is_demo_mode():
        from data.demo_companies import DEMO_COMPANIES

        return {"companies": DEMO_COMPANIES, "demo": True}
    return {"companies": [], "demo": False}


ui_dir = os.path.join(os.path.dirname(__file__), "ui")
if not os.path.isdir(ui_dir):
    os.makedirs(ui_dir, exist_ok=True)

app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")


@app.get("/", response_class=HTMLResponse)
def root() -> Any:
    return HTMLResponse(
        '<!doctype html><html><head><meta http-equiv="refresh" content="0; url=/ui/index.html" /></head><body></body></html>'
    )
