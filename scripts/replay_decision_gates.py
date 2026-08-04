#!/usr/bin/env python3
"""Replay scoped decision-gate outcomes from immutable Market Watch artifacts.

This module is deliberately observation-only.  It reads closure receipts and
recommendation snapshots; it never derives prices, creates candidates, or
turns missing evidence into an executable setup.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from scripts.rule_engine import classify_source_gap
except ImportError:  # pragma: no cover - direct invocation fallback
    from rule_engine import classify_source_gap


ROOT = Path(__file__).resolve().parents[1]
MARKET_WATCH_ROOT = ROOT.parent / "Market_Watch"
CLOSURE_ROOT = MARKET_WATCH_ROOT / "artifacts" / "review-closure" / "2026"
DEFAULT_DATE_FROM = "2026-07-08"
DEFAULT_DATE_TO = "2026-08-04"
SCOPES = {"global", "side", "candidate", "window"}
EXECUTABLE_DISPOSITIONS = {"standard", "guarded", "guarded_experiment"}


def _unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid trading date: {value}") from exc


def trading_days(date_from: str, date_to: str) -> List[str]:
    start = _date(date_from)
    end = _date(date_to)
    if start > end:
        raise ValueError("date_from must not be after date_to")
    days: List[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += dt.timedelta(days=1)
    return days


def _read_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.is_file():
        return None, "missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "invalid"
    if not isinstance(value, dict):
        return None, "invalid"
    return value, None


def _flatten_strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        result: List[str] = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    return []


def classify_replay_gaps(raw_gaps: Iterable[Any]) -> Dict[str, Any]:
    """Classify only explicit typed gaps; leave untyped gaps unverifiable."""
    global_hard: List[str] = []
    side_blocks: Dict[str, List[str]] = {"lianban": [], "trend": []}
    candidate_hard: Dict[str, List[str]] = {}
    unverifiable: List[str] = []

    for raw_value in raw_gaps or []:
        if isinstance(raw_value, Mapping):
            raw = raw_value.get("raw") or raw_value.get("gap") or ""
        else:
            raw = raw_value
        raw = str(raw or "").strip()
        if not raw:
            continue
        gap = classify_source_gap(raw)
        if gap["severity"] == "hard" and gap["scope"] == "global":
            global_hard.append(str(gap["code"]))
        elif (
            gap["severity"] == "hard"
            and gap["scope"] == "side"
            and gap.get("affected_side") in side_blocks
        ):
            side_blocks[str(gap["affected_side"])].append(str(gap["code"]))
        elif (
            gap["severity"] == "hard"
            and gap["scope"] == "candidate"
            and gap.get("affected_candidate")
        ):
            candidate = str(gap["affected_candidate"])
            candidate_hard.setdefault(candidate, []).append(str(gap["code"]))
        else:
            # This includes missing_rule_input:* and advisory/workflow-only
            # strings.  They are evidence gaps, never global hard gates.
            unverifiable.append(raw)

    return {
        "global_hard": _unique(global_hard),
        "side_blocks": {
            side: _unique(codes) for side, codes in side_blocks.items()
        },
        "candidate_hard": {
            candidate: _unique(codes)
            for candidate, codes in candidate_hard.items()
        },
        "unverifiable": _unique(unverifiable),
    }


def evaluate_replay_vector(
    *,
    side: str,
    global_hard: Optional[Sequence[str]] = None,
    side_blocks: Optional[Mapping[str, Sequence[str]]] = None,
    candidate_blocks: Optional[Sequence[str]] = None,
    window_open: bool = True,
    setup_complete: bool = True,
) -> Dict[str, Any]:
    """Evaluate a small explicit vector used by the regression replay test."""
    side_name = str(side or "").strip().lower()
    global_codes = _unique(global_hard or [])
    if global_codes:
        return {
            "allowed": False,
            "scope": "global",
            "blocking_codes": global_codes,
        }

    side_codes = _unique((side_blocks or {}).get(side_name, []))
    if side_codes:
        return {
            "allowed": False,
            "scope": "side",
            "blocking_codes": side_codes,
        }

    candidate_codes = _unique(candidate_blocks or [])
    if candidate_codes:
        return {
            "allowed": False,
            "scope": "candidate",
            "blocking_codes": candidate_codes,
        }

    if not window_open:
        return {
            "allowed": False,
            "scope": "window",
            "blocking_codes": ["WINDOW_CLOSED"],
        }

    if not setup_complete:
        return {
            "allowed": False,
            "scope": "candidate",
            "blocking_codes": ["UNVERIFIABLE_SETUP"],
        }

    return {"allowed": True, "scope": None, "blocking_codes": []}


def replay_complete_trend_w1_setup() -> Dict[str, Any]:
    """Return the explicit synthetic vector proving scoped gates can allow."""
    return evaluate_replay_vector(
        side="trend",
        global_hard=[],
        side_blocks={"trend": [], "lianban": []},
        candidate_blocks=[],
        window_open=True,
        setup_complete=True,
    )


def _candidate_side(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("side") or candidate.get("source") or candidate.get("role")
    text = str(value or "").strip().lower()
    if text in {"trend", "lianban"}:
        return text
    if any(token in text for token in ("trend", "capacity", "趋势", "容量", "中军")):
        return "trend"
    if any(token in text for token in ("lianban", "limit", "连板", "龙头", "高度")):
        return "lianban"
    return ""


def _candidate_decision(
    date_str: str,
    candidate: Mapping[str, Any],
    classified: Mapping[str, Any],
) -> Dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    code = str(candidate.get("code") or candidate.get("代码") or "").strip()
    side = _candidate_side(candidate)
    disposition = str(candidate.get("disposition") or "").strip().lower()
    source_decision = str(candidate.get("decision") or "").strip().lower()
    blocking_codes: List[str] = []

    global_codes = _unique(classified.get("global_hard") or [])
    side_codes = _unique((classified.get("side_blocks") or {}).get(side, []))
    candidate_codes = _unique(
        (classified.get("candidate_hard") or {}).get(candidate_id, [])
        + (classified.get("candidate_hard") or {}).get(code, [])
    )
    candidate_codes.extend(_flatten_strings(candidate.get("blocking_codes")))
    missing_evidence = _flatten_strings(candidate.get("missing_evidence"))
    candidate_codes.extend(missing_evidence)
    candidate_codes = _unique(candidate_codes)

    explicit_allowed = None
    for key in ("allowed", "decision_gate_allowed", "execution_allowed"):
        if isinstance(candidate.get(key), bool):
            explicit_allowed = bool(candidate[key])
            break

    if global_codes:
        allowed = False
        scope = "global"
        blocking_codes = global_codes
    elif side_codes:
        allowed = False
        scope = "side"
        blocking_codes = side_codes
    elif candidate_codes:
        allowed = False
        scope = "candidate"
        blocking_codes = candidate_codes
    elif explicit_allowed is False:
        allowed = False
        scope = "candidate"
        blocking_codes = ["EXPLICIT_CANDIDATE_BLOCK"]
    elif disposition in EXECUTABLE_DISPOSITIONS and source_decision not in {"exclude", "observe"}:
        allowed = True
        scope = None
    else:
        # A paper-only/observe/exclude artifact is a real candidate record but
        # not executable evidence.  Preserve that exact boundary as a scoped
        # candidate reason rather than inventing a global gate.
        allowed = False
        scope = "candidate"
        if disposition == "paper_only":
            blocking_codes = ["PAPER_ONLY_DISPOSITION"]
        elif source_decision == "exclude":
            blocking_codes = ["D2_EXCLUDE"]
        elif missing_evidence:
            blocking_codes = _unique(missing_evidence)
        else:
            blocking_codes = ["UNVERIFIABLE_CANDIDATE_SETUP"]

    return {
        "date": date_str,
        "candidate_id": candidate_id,
        "code": code,
        "side": side or None,
        "disposition": disposition or None,
        "source_decision": source_decision or None,
        "allowed": bool(allowed),
        "scope": scope,
        "blocking_codes": _unique(blocking_codes),
        "missing_evidence": _unique(missing_evidence),
        "evidence_source": "recommendation_snapshot.v1.json",
    }


def _typed_gaps_from_artifacts(
    finalization: Optional[Mapping[str, Any]],
    c15: Optional[Mapping[str, Any]],
    d2: Optional[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> List[str]:
    values: List[str] = []
    for payload in (finalization, c15, d2):
        if not isinstance(payload, Mapping):
            continue
        for key in ("source_gaps", "typed_source_gaps"):
            values.extend(_flatten_strings(payload.get(key)))
    for candidate in candidates:
        values.extend(_flatten_strings(candidate.get("source_gaps")))
    return _unique(values)


def _recommendation_state(
    date_str: str,
    snapshot: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    candidates = snapshot.get("candidates") if isinstance(snapshot, Mapping) else []
    if not isinstance(candidates, list):
        candidates = []
    return {
        "schema_version": "recommendation_state.v1",
        "trading_date": date_str,
        "candidates": copy.deepcopy(candidates),
    }


def build_day_report(
    date_str: str,
    *,
    closure_root: Path = CLOSURE_ROOT,
    workflow_gaps_override: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    day_root = Path(closure_root) / date_str
    finalization, final_problem = _read_json(day_root / "finalization_report.json")
    c15, c15_problem = _read_json(day_root / "c15_scan_receipt.json")
    d2, d2_problem = _read_json(day_root / "d2_decision_receipt.json")
    snapshot, snapshot_problem = _read_json(day_root / "recommendation_snapshot.v1.json")

    candidates: List[Mapping[str, Any]] = []
    if isinstance(snapshot, Mapping) and isinstance(snapshot.get("candidates"), list):
        candidates = [item for item in snapshot["candidates"] if isinstance(item, Mapping)]

    workflow_gaps = _flatten_strings((finalization or {}).get("blockers"))
    workflow_gaps.extend(_flatten_strings(workflow_gaps_override))
    workflow_gaps = _unique(workflow_gaps)

    unverifiable: List[str] = []
    for label, problem in (
        ("finalization_report", final_problem),
        ("c15_scan_receipt", c15_problem),
        ("d2_decision_receipt", d2_problem),
    ):
        if problem:
            unverifiable.append(f"{label}_{problem}")
    if snapshot_problem:
        unverifiable.append(f"recommendation_snapshot_{snapshot_problem}")
    if isinstance(c15, Mapping):
        unverifiable.extend(
            f"c15:{value}" for value in _flatten_strings(c15.get("blockers"))
        )

    typed = classify_replay_gaps(
        _typed_gaps_from_artifacts(finalization, c15, d2, candidates)
    )
    unverifiable.extend(_flatten_strings(typed.get("unverifiable")))

    candidate_decisions = [
        _candidate_decision(date_str, candidate, typed) for candidate in candidates
    ]
    standard_count = sum(
        1 for candidate in candidates
        if str(candidate.get("disposition") or "").strip().lower() == "standard"
    )
    guarded_count = sum(
        1 for candidate in candidates
        if str(candidate.get("disposition") or "").strip().lower()
        in {"guarded", "guarded_experiment"}
    )
    paper_only_count = sum(
        1 for candidate in candidates
        if str(candidate.get("disposition") or "").strip().lower() == "paper_only"
    )

    return {
        "date": date_str,
        "workflow_gaps": workflow_gaps,
        "global_hard": typed["global_hard"],
        "side_blocks": typed["side_blocks"],
        "candidate_decisions": candidate_decisions,
        "recommendation_count": len(candidates),
        "standard_count": standard_count,
        "guarded_count": guarded_count,
        "paper_only_count": paper_only_count,
        "unverifiable": _unique(unverifiable),
        "recommendation_state": _recommendation_state(date_str, snapshot),
    }


def _workflow_override(
    date_to: str, workflow_gap: Optional[str]
) -> Optional[Dict[str, List[str]]]:
    if not workflow_gap:
        return None
    return {date_to: [str(workflow_gap)]}


def build_replay_report(
    date_from: str = DEFAULT_DATE_FROM,
    date_to: str = DEFAULT_DATE_TO,
    *,
    closure_root: Path = CLOSURE_ROOT,
    workflow_gaps_override: Optional[Mapping[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    days: List[Dict[str, Any]] = []
    for date_str in trading_days(date_from, date_to):
        overrides = (workflow_gaps_override or {}).get(date_str)
        days.append(
            build_day_report(
                date_str,
                closure_root=closure_root,
                workflow_gaps_override=overrides,
            )
        )

    decisions = [
        decision
        for day in days
        for decision in day["candidate_decisions"]
    ]
    latest = days[-1] if days else None
    summary = {
        "trading_days": len(days),
        "decision_count": len(decisions),
        "allowed_count": sum(1 for decision in decisions if decision["allowed"]),
        "blocked_count": sum(1 for decision in decisions if not decision["allowed"]),
        "recommendation_count": sum(day["recommendation_count"] for day in days),
        "standard_count": sum(day["standard_count"] for day in days),
        "guarded_count": sum(day["guarded_count"] for day in days),
        "paper_only_count": sum(day["paper_only_count"] for day in days),
        "unverifiable_day_count": sum(1 for day in days if day["unverifiable"]),
        "unverifiable_count": sum(len(day["unverifiable"]) for day in days),
    }
    return {
        "schema_version": "gate_replay.v1",
        "date_from": date_from,
        "date_to": date_to,
        "trading_days": [day["date"] for day in days],
        "days": days,
        "decisions": decisions,
        "recommendation_state": (
            latest["recommendation_state"] if latest else {
                "schema_version": "recommendation_state.v1",
                "trading_date": date_to,
                "candidates": [],
            }
        ),
        "summary": summary,
    }


def replay_fixture(
    workflow_gap: Optional[str] = None,
    *,
    closure_root: Path = CLOSURE_ROOT,
) -> Dict[str, Any]:
    return build_replay_report(
        DEFAULT_DATE_FROM,
        DEFAULT_DATE_TO,
        closure_root=closure_root,
        workflow_gaps_override=_workflow_override(DEFAULT_DATE_TO, workflow_gap),
    )


def validate_report(report: Mapping[str, Any]) -> None:
    for decision in report.get("decisions") or []:
        if decision.get("allowed"):
            continue
        if decision.get("scope") not in SCOPES:
            raise ValueError(f"REPLAY_FALSE_SCOPE_INVALID:{decision}")
        if not _unique(decision.get("blocking_codes") or []):
            raise ValueError(f"REPLAY_FALSE_REASON_EMPTY:{decision}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", default=DEFAULT_DATE_FROM)
    parser.add_argument("--date-to", default=DEFAULT_DATE_TO)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--closure-root",
        default=str(CLOSURE_ROOT),
        help="override the immutable review-closure root for tests",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    report = build_replay_report(
        args.date_from,
        args.date_to,
        closure_root=Path(args.closure_root),
    )
    validate_report(report)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), **report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
