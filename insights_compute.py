"""
Simple in-memory insights from Slack message text: repeated questions, error-like
tokens, and high-friction topics (frequency + follow-up response time). No embeddings.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Set

from analytics_compute import _role

_QUESTION_START = re.compile(r"^\s*(how|why|what|where)\b", re.IGNORECASE)
_ERROR_TOKEN = re.compile(r"\b[A-Z_]{5,}\b")


def preprocess_text(text: str) -> str:
    low = (text or "").lower()
    no_punct = re.sub(r"[^a-z0-9\s]", "", low)
    return re.sub(r"\s+", " ", no_punct).strip()


def _is_question_like(raw: str) -> bool:
    s = (raw or "").strip()
    if not s:
        return False
    low = s.lower()
    if low.endswith("?"):
        return True
    return bool(_QUESTION_START.match(low))


def _follow_up_minutes_by_thread(
    messages: List[Dict[str, Any]], staff_set: Set[str]
) -> Dict[str, List[float]]:
    by_thread: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for m in messages:
        tid = m.get("thread_id")
        if tid is None:
            continue
        by_thread[str(tid)].append(m)

    out: Dict[str, List[float]] = defaultdict(list)
    for tid, arr in by_thread.items():
        rows = sorted(arr, key=lambda x: float(x.get("timestamp") or 0.0))
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
            out[tid].append(delta_sec / 60.0)
    return out


def compute_insights_snapshot(
    messages: List[Dict[str, Any]], staff_ids: List[str]
) -> Dict[str, Any]:
    staff_set: Set[str] = set(staff_ids)

    question_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    topic_threads: Dict[str, Set[str]] = defaultdict(set)

    for m in messages:
        raw = (m.get("text") or "").strip()
        if not raw:
            continue
        tid = m.get("thread_id")
        tid_s = str(tid) if tid is not None else ""

        if _is_question_like(raw):
            key = preprocess_text(raw)
            if key:
                question_counter[key] += 1
                if tid_s:
                    topic_threads[key].add(tid_s)

        for tok in _ERROR_TOKEN.findall(raw):
            error_counter[tok] += 1

    top_questions: List[Dict[str, Any]] = [
        {"topic": t, "count": c} for t, c in question_counter.most_common(10)
    ]
    top_errors: List[Dict[str, Any]] = [
        {"token": t, "count": c} for t, c in error_counter.most_common(10)
    ]

    fu_by_thread = _follow_up_minutes_by_thread(messages, staff_set)
    thread_avg_fu: Dict[str, float] = {}
    for tid, vals in fu_by_thread.items():
        if vals:
            thread_avg_fu[tid] = float(statistics.mean(vals))

    baseline_list = list(thread_avg_fu.values())
    baseline = float(statistics.median(baseline_list)) if baseline_list else 0.0

    high_friction_topics: List[Dict[str, Any]] = []
    for topic, occ in question_counter.most_common(25):
        tids = topic_threads.get(topic, set())
        avgs = [thread_avg_fu[t] for t in tids if t in thread_avg_fu]
        avg_fu = float(statistics.mean(avgs)) if avgs else 0.0
        n_data = len(avgs)
        # Frequent exact-repeat questions + follow-up slower than typical thread in sample.
        if baseline > 0:
            high = bool(
                occ >= 3
                and n_data >= 1
                and avg_fu >= 45.0
                and avg_fu > baseline
            )
        else:
            high = bool(occ >= 3 and n_data >= 1 and avg_fu >= 60.0)
        if high:
            high_friction_topics.append(
                {
                    "topic": topic,
                    "occurrences": occ,
                    "threadsWithFollowUpData": n_data,
                    "avgFollowUpMinutes": round(avg_fu, 2),
                    "highFriction": True,
                }
            )
        if len(high_friction_topics) >= 10:
            break

    return {
        "topQuestions": top_questions,
        "topErrors": top_errors,
        "highFrictionTopics": high_friction_topics,
        "followUpBaselineMinutes": round(baseline, 2),
    }
