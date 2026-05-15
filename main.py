import os
import re
import time
from typing import Any, Dict, List, Tuple

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

# Shown when demo Ask cannot match indexed mock context with enough confidence.
DEMO_ANSWER_UNAVAILABLE = (
    "This is a demo: ORCA doesn’t have relevant indexed context for that question yet, "
    "so a reliable answer isn’t available."
)

# Minimum best match score for the generic demo retrieval path (intents bypass this).
DEMO_RETRIEVAL_MIN_SCORE = 8


class AskRequest(BaseModel):
    question: str


_STOPWORDS = frozenset(
    "a an the and or but if is are was were be been being to for of in on at by "
    "with from as it its this that these those what which who whom whose when where "
    "why how all any both each few more most other some such no nor not only same so "
    "than too very can could should would may might must shall will do does did doing "
    "done we you your they them their our my me i he she his her has have had having "
    "there here about into through during before after above below out up down any "
    "just than then once".split()
)

# Lightweight synonym expansion for retrieval scoring (no extra mock data).
_SYNEXPAND = [
    (["ach", "bank transfer", "batch processing"], "ach reconciliation settlement batch ledger"),
    (
        ["api", "endpoint", "integration", "service", "microservice"],
        "api endpoint contract integration service microservice",
    ),
    (["wire", "routing number", "swift"], "wire routing swift remittance beneficiary"),
    (
        ["error", "failure", "failures", "fail", "incident", "issue"],
        "error failure failures incident deploy rollback 429",
    ),
]


def _query_matches_topic_term(ql: str, term: str) -> bool:
    """Match phrase or whole token (avoids e.g. 'api' matching inside 'capital')."""
    t = term.strip().lower()
    if not t:
        return False
    if " " in t:
        return t in ql
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", ql))


def _enriched_query_for_scoring(q: str) -> str:
    ql = q.lower()
    parts = [ql]
    for keys, blob in _SYNEXPAND:
        if any(_query_matches_topic_term(ql, k) for k in keys):
            parts.append(blob)
    return " ".join(parts)


_ROOT_CAUSE_MARKERS = (
    "caused by",
    "due to",
    "root cause",
    "missing",
    "failed because",
    "because",
    "confirmed",
)


def _intent_definition(ql: str) -> str | None:
    if not (
        "what is" in ql
        or "what're" in ql
        or ("what does" in ql and "mean" in ql)
        or ql.startswith("define ")
        or " define " in ql
        or ql.startswith("explain ")
        or " explain " in ql
    ):
        return None

    def hits(keys: list[str]) -> bool:
        return any(_query_matches_topic_term(ql, k) for k in keys)

    if hits(["ach", "bank transfer", "batch processing"]):
        return (
            "Based on Slack discussions in #ops, ACH (Automated Clearing House) is a batch-based bank transfer "
            "network. Recent internal discussions noted delays due to reconciliation edge cases."
        )
    if hits(["api", "endpoint", "integration", "service", "microservice"]):
        return (
            "Based on Slack discussions in #engineering, an API (Application Programming Interface) is a "
            "contract that allows systems to communicate with each other."
        )
    if hits(["wire", "wire transfer", "swift"]):
        return (
            "Based on Slack discussions in #payments, a wire transfer is a real-time bank transfer method "
            "used to send funds directly between financial institutions. Recent discussions highlighted failures "
            "caused by missing routing details."
        )
    return None


def _intent_status_health(ql: str) -> str | None:
    if (
        "any issues" in ql
        or "system issues" in ql
        or ("issues" in ql and "system" in ql)
        or "system status" in ql
        or "errors today" in ql
        or ql.strip() in ("alerts", "alert")
    ):
        return (
            "Based on Slack discussions in #alerts, recent discussions indicate elevated error rates following "
            "a deploy, with investigation pointing to configuration issues."
        )
    return None


def _troubleshooting_retrieve(ql: str, rows: List[Dict[str, str]]) -> str | None:
    """Shared retrieval + summarization for troubleshooting-style questions."""
    qe = _enriched_query_for_scoring(ql)

    def has_root_language(m: Dict[str, str]) -> bool:
        t = m["text"].lower()
        return any(marker in t for marker in _ROOT_CAUSE_MARKERS)

    rc_rows = [m for m in rows if has_root_language(m)]

    if "error" in ql or "errors" in ql or "failure" in ql or "failures" in ql:
        err_focus = [
            m
            for m in rows
            if "error" in m["text"].lower()
            or m["channel"] == "#alerts"
            or "elevated" in m["text"].lower()
            or "incident" in m["text"].lower()
        ]
        pool = err_focus if err_focus else rows
        pref = [m for m in pool if "elevated" in m["text"].lower() or "error rates" in m["text"].lower()]
        if pref:
            pool = pref
    else:
        pool = rc_rows if rc_rows else rows

    matches, _ = _pick_best_messages(qe, pool, limit=2)
    if not matches:
        return None
    return _summarize_mock_matches(matches)


def _routing_wire_troubleshooting_bridge(ql: str, rows: List[Dict[str, str]]) -> str | None:
    """
    If the user ties routing numbers to wire/failure language, run troubleshooting
    against wire/routing-heavy lines (avoids missed paths like 'why did routing number fail').
    """
    if "routing number" not in ql:
        return None
    if not (("wire" in ql) or ("fail" in ql) or ("failed" in ql)):
        return None
    qe = _enriched_query_for_scoring(ql)
    narrow = [
        m
        for m in rows
        if ("routing" in m["text"].lower() or "wire" in m["text"].lower())
    ]
    pool = narrow if narrow else rows
    matches, _ = _pick_best_messages(qe, pool, limit=2)
    if matches:
        return _summarize_mock_matches(matches)
    return _troubleshooting_retrieve(ql, rows)


def _intent_troubleshooting(ql: str, rows: List[Dict[str, str]]) -> str | None:
    if not any(
        w in ql
        for w in (
            "why",
            "failed",
            "fail",
            "error",
            "errors",
            "issue",
            "problem",
            "wrong",
            "incident",
            "seeing",
        )
    ):
        return None
    return _troubleshooting_retrieve(ql, rows)


def _mock_slack_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "mock_slack.txt")


_mock_slack_cache: List[Dict[str, str]] | None = None


def _parse_mock_slack() -> List[Dict[str, str]]:
    global _mock_slack_cache
    if _mock_slack_cache is not None:
        return _mock_slack_cache
    path = _mock_slack_path()
    out: List[Dict[str, str]] = []
    if not os.path.isfile(path):
        _mock_slack_cache = []
        return _mock_slack_cache
    channel = "#general"
    line_re = re.compile(
        r"^\[\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*\]\s+([^:]+):\s*(.+)\s*$"
    )
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                channel = line.split()[0] if line.split() else channel
                continue
            m = line_re.match(line)
            if not m:
                continue
            out.append(
                {
                    "channel": channel,
                    "when": m.group(1).strip(),
                    "speaker": m.group(2).strip(),
                    "text": m.group(3).strip(),
                }
            )
    _mock_slack_cache = out
    return _mock_slack_cache


def _question_tokens(q: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", q.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _score_message(question_l: str, msg: Dict[str, str]) -> int:
    text_l = msg["text"].lower()
    score = 0
    # Strong anchors when the question names a topic explicitly
    anchors = [
        ("api", ("api", "endpoint", "contract", "service")),
        ("wire", ("wire", "routing", "swift")),
        ("ach", ("ach", "reconciliation", "batch", "settlement")),
        ("onboard", ("onboard", "sandbox", "integration", "repo", "checklist")),
        ("error", ("error", "fail", "500", "429", "unexpected")),
        ("alert", ("alert", "pager", "incident", "spike", "elevated")),
        ("system", ("error", "incident", "database", "timeout", "deploy", "elevated")),
    ]
    for qword, needles in anchors:
        if _query_matches_topic_term(question_l, qword):
            if any(n in text_l for n in needles):
                score += 12
    if ("why" in question_l or "fail" in question_l) and _query_matches_topic_term(
        question_l, "wire"
    ):
        if "missing" in text_l and "routing" in text_l:
            score += 25
    if _query_matches_topic_term(question_l, "routing") and _query_matches_topic_term(
        question_l, "wire"
    ):
        if "routing" in text_l:
            score += 15
    for tok in _question_tokens(question_l):
        if tok in text_l:
            score += 3 if len(tok) > 4 else 2
    bridges: List[Tuple[Tuple[str, ...], Tuple[str, ...]]] = [
        (
            ("wire", "routing", "swift", "remittance", "beneficiary", "bounce"),
            ("wire", "routing", "swift", "reject"),
        ),
        (
            ("ach", "reconciliation", "settlement", "batch", "ledger"),
            ("ach", "reconciliation", "settlement", "batch"),
        ),
        (
            ("api", "endpoint", "request", "integration", "rate", "contract", "version"),
            ("api", "endpoint", "429", "timeout", "json"),
        ),
        (
            ("error", "fail", "failure", "bug", "500", "broken", "wrong"),
            ("error", "fail", "bug", "500", "429", "unexpected"),
        ),
        (
            ("alert", "pager", "incident", "outage", "downtime", "spike", "elevated", "monitor", "system"),
            ("alert", "pager", "incident", "spike", "deploy", "latency", "database", "elevated"),
        ),
        (
            ("onboard", "setup", "sandbox", "key", "credential", "checklist"),
            ("onboard", "sandbox", "key", "integration", "checklist", "repo"),
        ),
        (
            ("system", "issue", "problem", "seeing", "happen"),
            ("error", "incident", "elevated", "deploy", "database", "timeout", "spike"),
        ),
        (
            ("delay", "slow", "timing", "cut-off", "same-day", "when"),
            ("delay", "slow", "timing", "cut", "batch", "sla", "ach"),
        ),
    ]
    for q_syns, t_syns in bridges:
        if any(_query_matches_topic_term(question_l, s) for s in q_syns) and any(
            s in text_l for s in t_syns
        ):
            score += 4
    return score


def _pick_best_messages(
    question: str, rows: List[Dict[str, str]], limit: int = 3
) -> Tuple[List[Dict[str, str]], int]:
    q_low = (question or "").lower()
    scored: List[Tuple[int, Dict[str, str]]] = []
    for msg in rows:
        s = _score_message(q_low, msg)
        if s > 0:
            scored.append((s, msg))
    scored.sort(key=lambda x: (-x[0], x[1]["text"]))
    best_score = scored[0][0] if scored else 0
    seen_txt: set[str] = set()
    out: List[Dict[str, str]] = []
    for _s, msg in scored:
        key = msg["text"][:160]
        if key in seen_txt:
            continue
        seen_txt.add(key)
        out.append(msg)
        if len(out) >= limit:
            break
    return out, best_score


def _summarize_mock_matches(matches: List[Dict[str, str]]) -> str:
    """Return full user-visible answer: channel-grounded + analysis-style summary."""
    if not matches:
        return DEMO_ANSWER_UNAVAILABLE
    channel = matches[0]["channel"]
    summary = _synthesize_analysis_clause(matches)
    return f"Based on Slack discussions in {channel}, {summary}"


def _lc_sentence(text: str) -> str:
    """Lowercase sentence lead for readability after '..., ' (preserve common acronyms)."""
    t = text.strip().rstrip(".")
    if not t:
        return t
    first = t.split(maxsplit=1)[0]
    if first in ("APIs", "API", "ACH", "SLA", "SQL", "KPIs", "JSON"):
        return t
    return t[0].lower() + t[1:] if len(t) > 1 else t.lower()


def _synthesize_analysis_clause(matches: List[Dict[str, str]]) -> str:
    """Turn 1–2 retrieved messages into one polished clause (no leading prefix)."""
    for m in matches:
        tl = m["text"].lower()
        if "apis are how" in tl or ("think of it" in tl and "menu" in tl):
            return (
                "the team frames APIs as the contract through which services communicate, "
                "with contract-first design as the rule."
            )
    if matches:
        ta0 = matches[0]["text"].lower()
        if "ach rollout delayed" in ta0 or (
            "ach" in ta0 and "reconciliation" in ta0 and "delayed" in ta0
        ):
            return (
                "the ACH rollout was delayed due to reconciliation edge cases in overnight batching, "
                "with stronger validation planned before release."
            )

    if len(matches) == 1:
        t = matches[0]["text"]
        tl = t.lower()
        if "missing" in tl and "routing" in tl and "wire" in tl:
            return "the wire failure was caused by a missing routing number that upfront validation did not catch."
        if "apis are how" in tl or ("api" in tl and "communicate" in tl):
            return (
                "the team frames APIs as the contract through which services communicate, "
                "with contract-first design as the rule."
            )
        if "ach rollout delayed" in tl or ("ach" in tl and "reconciliation" in tl):
            return (
                "the ACH rollout was delayed due to reconciliation edge cases in overnight batching, "
                "with stronger validation planned before release."
            )
        if "elevated error" in tl or ("error rates" in tl and "transaction api" in tl):
            return (
                "monitoring showed elevated error rates on the transaction API (likely deploy-related); "
                "the team mitigated with rollback and timeout adjustments."
            )
        if "onboarding" in tl and ("repo" in tl or "stack" in tl):
            return (
                "onboarding walks new hires through the repo, local stack setup, and sandbox keys before production work."
            )
        if "database connection pool" in tl or "pool exhausted" in tl:
            return (
                "operations addressed database connection pool exhaustion on the auth service and improved alerting."
            )
        return f"{_lc_sentence(t)}."

    a, b = matches[0], matches[1]
    ta, tb = a["text"].lower(), b["text"].lower()
    if ("wire" in ta or "routing" in ta) and ("validation" in tb or "catch" in tb):
        return "the wire failure was caused by a missing routing number that validation did not catch before the payment left the queue."
    if "ach" in ta and "reconciliation" in ta and ("validation" in tb or "release" in tb or "freeze" in tb):
        return (
            "the ACH delay stemmed from reconciliation edge cases; the team is tightening validation "
            "and coordinating a controlled cutover window."
        )
    if ("error" in ta or "spiking" in ta or "elevated" in ta) and (
        "deploy" in tb or "rollback" in tb or "resolved" in tb or "config" in tb
    ):
        return (
            "the team traced elevated errors to deploy and configuration issues, used rollback where needed, "
            "and restored stable behavior on payment routes."
        )
    if ("database" in ta or "index" in ta or "batch" in ta) and (
        "incident" in tb or "resolved" in tb or "config" in tb or "timeout" in tb
    ):
        return (
            "operations improved batch performance (for example via indexing) while incident response focused on "
            "bad deploy config affecting payment-route timeouts."
        )
    if "api" in ta and ("retry" in tb or "429" in tb or "backoff" in tb):
        return (
            "engineering addressed transaction API load issues with client backoff, retries, and clearer rate-limit guidance."
        )
    body_a, body_b = _lc_sentence(a["text"]), _lc_sentence(b["text"])
    return f"{body_a}, and further discussion noted that {body_b}."


def _demo_api_ask_answer(question: str) -> str:
    rows = _parse_mock_slack()
    if not rows:
        return DEMO_ANSWER_UNAVAILABLE
    ql = (question or "").strip().lower()

    ans = _intent_definition(ql)
    if ans:
        return ans

    ans = _routing_wire_troubleshooting_bridge(ql, rows)
    if ans:
        return ans

    ans = _intent_status_health(ql)
    if ans:
        return ans

    ans = _intent_troubleshooting(ql, rows)
    if ans:
        return ans

    qe = _enriched_query_for_scoring(question)
    matches, best_score = _pick_best_messages(qe, rows, limit=2)
    if not matches or best_score < DEMO_RETRIEVAL_MIN_SCORE:
        return DEMO_ANSWER_UNAVAILABLE
    return _summarize_mock_matches(matches)


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


@app.post("/api/ingest")
def api_ingest_demo() -> Dict[str, Any]:
    """Demo-only: fake ingest success for /api/* clients."""
    if not is_demo_mode():
        raise HTTPException(status_code=404, detail="Available in demo mode only")
    return {
        "status": "success",
        "channels": ["#payments", "#engineering", "#ops", "#support", "#alerts", "#dev"],
        "messagesIndexed": 1287,
    }


@app.post("/api/ask")
def api_ask_demo(body: AskRequest) -> Dict[str, Any]:
    """Demo-only: keyword-based simulated answer; body must include \"question\"."""
    if not is_demo_mode():
        raise HTTPException(status_code=404, detail="Available in demo mode only")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty")
    return {"answer": _demo_api_ask_answer(body.question)}


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
            "answer": _demo_api_ask_answer(body.question),
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
