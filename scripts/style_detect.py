#!/usr/bin/env python3
"""Compatibility adapter for the Market Watch canonical D0 style result.

This module intentionally contains no scoring logic.  Market Watch is the sole
producer; live-dashboard only validates and translates its 30/40/30 result.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


EXPECTED_WEIGHTS = {"量能": 30, "连板生态": 40, "趋势赚钱效应": 30}
EXPECTED_SCHEMA = "review-style-detect.v1"
EXPECTED_FORMULA = "piecewise_linear_v1"
MARKET_WATCH_SCRIPT = (
    Path.home() / "Documents/YM_Capital/Market_Watch/scripts/style_detect.py"
)


def validate_canonical(report):
    errors = []
    if not isinstance(report, dict):
        return ["canonical report must be an object"]
    if report.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("schema_version must be review-style-detect.v1")
    if report.get("dimension_weights") != EXPECTED_WEIGHTS:
        errors.append("dimension_weights must be 30/40/30")
    if report.get("formula_version") != EXPECTED_FORMULA:
        errors.append("formula_version must be piecewise_linear_v1")
    allocation = report.get("allocation")
    if report.get("status") == "ready":
        if report.get("total_score") is None:
            errors.append("ready report requires total_score")
        lb = allocation.get("连板资金占比") if isinstance(allocation, dict) else None
        trend = allocation.get("趋势资金占比") if isinstance(allocation, dict) else None
        if lb is None or trend is None:
            errors.append("ready report requires both allocation values")
        else:
            try:
                if round(float(lb) + float(trend), 6) != 100.0:
                    errors.append("allocation values must sum to 100")
            except (TypeError, ValueError):
                errors.append("allocation values must be numeric")
    elif not report.get("source_gaps"):
        errors.append("non-ready report requires source_gaps")
    return errors


def load_canonical_report(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_canonical(report)
    if errors:
        raise ValueError("; ".join(errors))
    return report


def run_market_watch(review_path):
    result = subprocess.run(
        [sys.executable, str(MARKET_WATCH_SCRIPT), "--review-note", str(review_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Market Watch style producer failed")
    report = json.loads(result.stdout)
    errors = validate_canonical(report)
    if errors:
        raise ValueError("; ".join(errors))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--canonical-report")
    source.add_argument("--review", help="delegate production to Market Watch")
    parser.add_argument("--json", action="store_true", help="retained for CLI compatibility")
    args = parser.parse_args(argv)
    try:
        report = (
            load_canonical_report(args.canonical_report)
            if args.canonical_report
            else run_market_watch(args.review)
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"style adapter blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
