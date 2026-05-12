"""Static demo company profiles (no Slack; for /api/companies when DEMO_MODE)."""

from __future__ import annotations

from typing import Any, Dict, List

DEMO_COMPANIES: List[Dict[str, Any]] = [
    {
        "company_id": "apex-pay",
        "company_name": "ApexPay",
        "slack_channels": ["apex-pay-api"],
        "bank_partner": "Demo Bank North",
        "integration_status": "Active Integration",
        "analytics": {
            "total_messages": 184,
            "avg_first_response_time": 12.4,
            "avg_follow_up_response_time": 22.1,
            "api_call_count": 11840,
            "traffic_status": "Traffic Spike",
        },
        "notes": "Recent launch testing drove a sharp API traffic spike vs prior baseline.",
    },
    {
        "company_id": "northstar-financial",
        "company_name": "Northstar Financial",
        "slack_channels": ["northstar-fin-support"],
        "bank_partner": "Demo Bank East",
        "integration_status": "Needs Help",
        "analytics": {
            "total_messages": 96,
            "avg_first_response_time": 35.2,
            "avg_follow_up_response_time": 28.0,
            "api_call_count": 420,
            "traffic_status": "Traffic Drop-off",
        },
        "notes": "API volume trailed off after UAT freeze; integration activity appears stalled.",
    },
    {
        "company_id": "horizon-labs",
        "company_name": "Horizon Labs",
        "slack_channels": ["horizon-labs-integration"],
        "bank_partner": "Demo Bank West",
        "integration_status": "Needs Help",
        "analytics": {
            "total_messages": 142,
            "avg_first_response_time": 14.0,
            "avg_follow_up_response_time": 118.6,
            "api_call_count": 2100,
            "traffic_status": "Stable Activity",
        },
        "notes": "First responses are quick, but follow-up engineering replies are consistently slow.",
    },
    {
        "company_id": "vertex-treasury",
        "company_name": "Vertex Treasury",
        "slack_channels": ["vertex-treasury-dev"],
        "bank_partner": "Demo Bank Central",
        "integration_status": "Active Integration",
        "analytics": {
            "total_messages": 210,
            "avg_first_response_time": 18.5,
            "avg_follow_up_response_time": 31.2,
            "api_call_count": 5600,
            "traffic_status": "Stable Activity",
        },
        "notes": "Same routing question appears in many threads; likely documentation gap.",
    },
    {
        "company_id": "bluepeak-capital",
        "company_name": "BluePeak Capital",
        "slack_channels": ["bluepeak-capital-ops"],
        "bank_partner": "Demo Bank South",
        "integration_status": "Active Integration",
        "analytics": {
            "total_messages": 88,
            "avg_first_response_time": 21.0,
            "avg_follow_up_response_time": 24.0,
            "api_call_count": 1800,
            "traffic_status": "Stable Activity",
        },
        "notes": "Steady cadence across API traffic and Slack support threads.",
    },
]
