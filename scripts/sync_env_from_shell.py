"""
Merge SLACK_BOT_TOKEN, OPENAI_API_KEY, SLACK_CHANNEL_IDS from the current
process environment into ../.env. Does not print secret values.
Preserves SLACK_STAFF_USER_IDS and comments when possible.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

SECRET_KEYS = ("SLACK_BOT_TOKEN", "OPENAI_API_KEY", "SLACK_CHANNEL_IDS")
ALL_KNOWN = ("SLACK_STAFF_USER_IDS",) + SECRET_KEYS


def parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        if k in ALL_KNOWN:
            out[k] = v.strip()
    return out


def main() -> None:
    from_file = parse_env_file(ENV_PATH)
    merged = dict(from_file)
    for key in SECRET_KEYS:
        env_val = (os.environ.get(key) or "").strip()
        if env_val:
            merged[key] = env_val

    lines = [
        "# Braid developers env",
        "# Loaded by python-dotenv in slack_ingest.py (shell variables still win if already set).",
        "",
    ]
    staff = merged.get("SLACK_STAFF_USER_IDS", "").strip()
    if staff:
        lines.append("# Staff Slack user IDs (everyone else with a user id = client when this is set)")
        lines.append(f"SLACK_STAFF_USER_IDS={staff}")
        lines.append("")

    lines.append("# Slack bot (xoxb-...)")
    tok = merged.get("SLACK_BOT_TOKEN", "").strip()
    if tok:
        lines.append(f"SLACK_BOT_TOKEN={tok}")
    else:
        lines.append("# SLACK_BOT_TOKEN=")

    lines.append("")
    lines.append("# OpenAI")
    key = merged.get("OPENAI_API_KEY", "").strip()
    if key:
        lines.append(f"OPENAI_API_KEY={key}")
    else:
        lines.append("# OPENAI_API_KEY=")

    lines.append("")
    lines.append("# Optional: comma-separated Slack channel IDs (empty = all bot-visible channels)")
    ch = merged.get("SLACK_CHANNEL_IDS", "").strip()
    if ch:
        lines.append(f"SLACK_CHANNEL_IDS={ch}")
    else:
        lines.append("# SLACK_CHANNEL_IDS=")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {ENV_PATH} (values from shell merged in where set; otherwise kept from file or left commented).")


if __name__ == "__main__":
    main()
