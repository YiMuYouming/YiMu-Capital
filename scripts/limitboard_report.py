"""Load the optional post-close limit-board report consumed by W21.

The report is an independent enrichment layer. It must never mutate or replace
the intraday hot-list and confirmed limit-up caches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LATEST_REPORT_PATH = ROOT / "data" / "limitboard_reports" / "latest.json"
SCHEMA_VERSION = "limitboard-report.v1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_limitboard_report(path: str | Path) -> dict[str, Any]:
    """Return a validated post-close v1 report, or an empty mapping."""
    report_path = Path(path)
    if not report_path.is_file():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") != SCHEMA_VERSION:
        return {}
    if payload.get("market_phase") != "post_close":
        return {}
    if not _DATE_RE.match(str(payload.get("date") or "")):
        return {}
    if not isinstance(payload.get("limit_up_stocks"), list):
        return {}
    if payload.get("summary") is not None and not isinstance(payload.get("summary"), dict):
        return {}
    if payload.get("quality") is not None and not isinstance(payload.get("quality"), dict):
        return {}
    if payload.get("sources") is not None and not isinstance(payload.get("sources"), list):
        return {}
    return payload


def load_latest_limitboard_report() -> dict[str, Any]:
    """Load the latest locally synced report without raising into API paths."""
    return load_limitboard_report(LATEST_REPORT_PATH)
