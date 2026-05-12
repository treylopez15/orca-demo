"""Central ORCA flags (read from environment only)."""

from __future__ import annotations

import os


def is_demo_mode() -> bool:
    v = (os.getenv("DEMO_MODE") or "").strip().lower()
    return v in ("1", "true", "yes")
