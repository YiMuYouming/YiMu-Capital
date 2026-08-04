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
import hashlib
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
ATTRIBUTION_CLASSES = {
    "data_source_unavailable",
    "artifact_missing",
    "candidate_evidence_missing",
    "recorded_no_setup",
    "strategy_block",
    "paper_only",
    "executable",
}
REQUIRED_ARTIFACTS = (
    "finalization_report.json",
    "c15_scan_receipt.json",
    "d2_decision_receipt.json",
    "recommendation_snapshot.v1.json",
)
TRACE_ARTIFACTS = (
    "finalization_report.json",
    "c15_scan_receipt.json",
    "c15_signal_ledger.json",
    "c2_board_matrix.json",
    "d1_draft_receipt.json",
    "d2_decision_receipt.json",
    "recommendation_snapshot.v1.json",
    "degraded_acceptance_receipt.json",
    "red_team_receipt.json",
)
SOURCE_UNAVAILABLE_BLOCKERS = {
    "coverage_below_minimum",
    "empty_result",
    "midcap_sector_context_missing",
    "named_entity_missing",
    "pipeline_error",
    "pipeline_confidence_error",
    "pipeline_semantic_degraded",
    "row_shape_mismatch",
    "stale_source",
}


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


def _artifact_trace(day_root: Path) -> List[Dict[str, Any]]:
    trace: List[Dict[str, Any]] = []
    for name in TRACE_ARTIFACTS:
        path = day_root / name
        if not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = None
        trace.append({
            "artifact": name,
            "path": str(path),
            "sha256": digest,
        })
    return trace


def _c15_source_blockers(c15: Optional[Mapping[str, Any]]) -> List[str]:
    if not isinstance(c15, Mapping):
        return []
    blockers = _flatten_strings(c15.get("blockers"))
    for gap in c15.get("source_gaps") or []:
        if isinstance(gap, Mapping):
            blockers.extend(_flatten_strings(gap.get("blockers")))
    return _unique(
        blocker for blocker in blockers if blocker in SOURCE_UNAVAILABLE_BLOCKERS
    )


def _candidate_evidence_gaps(candidate: Mapping[str, Any]) -> List[str]:
    gaps = _flatten_strings(candidate.get("missing_evidence"))
    if "setup" in candidate and not str(candidate.get("setup") or "").strip():
        gaps.append("setup")
    if "trigger" in candidate and not str(candidate.get("trigger") or "").strip():
        gaps.append("trigger")
    if "invalidation" in candidate and not str(candidate.get("invalidation") or "").strip():
        gaps.append("invalidation")
    if candidate.get("score") == 0 or candidate.get("score") == 0.0:
        gaps.append("score_zero")
    return _unique(gaps)


def _classify_candidate(
    candidate: Mapping[str, Any],
    *,
    snapshot_present: bool,
    source_blockers: Sequence[str],
) -> str:
    if not snapshot_present:
        return "artifact_missing"
    decision = str(candidate.get("decision") or candidate.get("final_role") or "").strip().lower()
    disposition = str(candidate.get("disposition") or "").strip().lower()
    blocking_codes = set(_flatten_strings(candidate.get("blocking_codes")))
    evidence_gaps = _candidate_evidence_gaps(candidate)
    if decision in {"exclude", "no_touch"} or blocking_codes:
        return "strategy_block"
    if disposition in EXECUTABLE_DISPOSITIONS and not evidence_gaps and decision not in {"observe", "exclude"}:
        return "executable"
    if evidence_gaps and disposition not in {"paper_only", ""}:
        return "candidate_evidence_missing"
    if disposition == "paper_only" and decision in {"observe", ""}:
        return "recorded_no_setup" if evidence_gaps else "paper_only"
    if disposition == "paper_only":
        return "paper_only"
    if evidence_gaps:
        return "candidate_evidence_missing"
    return "paper_only"


def _day_classification(
    *,
    candidate_decisions: Sequence[Mapping[str, Any]],
    missing_artifacts: Sequence[str],
    source_blockers: Sequence[str],
) -> str:
    if source_blockers:
        return "data_source_unavailable"
    if not candidate_decisions and missing_artifacts:
        return "artifact_missing"
    classes = {item.get("classification") for item in candidate_decisions}
    if "executable" in classes:
        return "executable"
    if "candidate_evidence_missing" in classes:
        return "candidate_evidence_missing"
    if classes and classes <= {"recorded_no_setup"}:
        return "recorded_no_setup"
    if classes and classes <= {"strategy_block"}:
        return "strategy_block"
    if classes and classes <= {"paper_only"}:
        return "paper_only"
    if missing_artifacts:
        return "artifact_missing"
    return "paper_only"


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
    *,
    classification: Optional[str] = None,
    evidence_gaps: Optional[Sequence[str]] = None,
    source_trace: Optional[Sequence[Mapping[str, Any]]] = None,
    evidence_source: str = "recommendation_snapshot.v1.json",
    evidence_diagnosis: Optional[str] = None,
    upstream_decision_reason: Optional[str] = None,
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
        "classification": classification or "paper_only",
        "evidence_gaps": _unique(evidence_gaps or []),
        "source_trace": copy.deepcopy(list(source_trace or [])),
        "evidence_source": evidence_source,
        "evidence_diagnosis": evidence_diagnosis,
        "upstream_decision_reason": upstream_decision_reason,
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
    snapshot_present = isinstance(snapshot, Mapping) and not snapshot_problem
    d2_candidates: List[Mapping[str, Any]] = []
    if isinstance(d2, Mapping) and isinstance(d2.get("decisions"), list):
        d2_candidates = [item for item in d2["decisions"] if isinstance(item, Mapping)]

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

    missing_artifacts = [
        name for name in REQUIRED_ARTIFACTS
        if not (day_root / name).is_file()
    ]
    source_blockers = _c15_source_blockers(c15)
    source_trace = _artifact_trace(day_root)
    attribution_counts = {name: 0 for name in sorted(ATTRIBUTION_CLASSES)}
    d2_by_identity = {
        identity: item
        for item in d2_candidates
        for identity in (
            str(item.get("candidate_id") or "").strip(),
            str(item.get("code") or item.get("代码") or "").strip(),
        )
        if identity
    }

    candidate_inputs: List[Mapping[str, Any]] = candidates
    if not snapshot_present and d2_candidates:
        candidate_inputs = [
            {
                **dict(item),
                "disposition": "paper_only",
                "_artifact_missing": ["recommendation_snapshot.v1.json"],
            }
            for item in d2_candidates
        ]

    candidate_decisions = [
        _candidate_decision(
            date_str,
            candidate,
            typed,
            classification=(
                "artifact_missing"
                if candidate.get("_artifact_missing")
                else _classify_candidate(
                    candidate,
                    snapshot_present=snapshot_present,
                    source_blockers=source_blockers,
                )
            ),
            evidence_gaps=(
                ["recommendation_snapshot.v1.json"]
                if candidate.get("_artifact_missing")
                else _candidate_evidence_gaps(candidate)
            ),
            source_trace=source_trace,
            evidence_source=(
                "d2_decision_receipt.json"
                if candidate.get("_artifact_missing")
                else "recommendation_snapshot.v1.json"
            ),
            evidence_diagnosis=(
                "recommendation_snapshot_missing_after_d2_candidate"
                if candidate.get("_artifact_missing")
                else (
                    "source_recorded_no_setup_or_trigger"
                    if {
                        "setup", "trigger"
                    }.issubset(set(_candidate_evidence_gaps(candidate)))
                    and str(candidate.get("decision") or "").strip().lower() == "observe"
                    else None
                )
            ),
            upstream_decision_reason=(
                d2_by_identity.get(
                    str(candidate.get("candidate_id") or "").strip()
                )
                or d2_by_identity.get(
                    str(candidate.get("code") or candidate.get("代码") or "").strip()
                )
                or {}
            ).get("reason"),
        )
        for candidate in candidate_inputs
    ]
    for decision in candidate_decisions:
        classification = str(decision.get("classification") or "paper_only")
        if classification not in attribution_counts:
            classification = "paper_only"
        attribution_counts[classification] += 1

    day_classification = _day_classification(
        candidate_decisions=candidate_decisions,
        missing_artifacts=missing_artifacts,
        source_blockers=source_blockers,
    )
    day_reasons = list(source_blockers)
    day_reasons.extend(f"missing:{name}" for name in missing_artifacts)
    day_reasons.extend(
        f"candidate:{item['classification']}"
        for item in candidate_decisions
        if item.get("classification")
    )
    standard_count = sum(
        1 for candidate in candidate_inputs
        if str(candidate.get("disposition") or "").strip().lower() == "standard"
    )
    guarded_count = sum(
        1 for candidate in candidate_inputs
        if str(candidate.get("disposition") or "").strip().lower()
        in {"guarded", "guarded_experiment"}
    )
    paper_only_count = sum(
        1 for candidate in candidate_inputs
        if str(candidate.get("disposition") or "").strip().lower() == "paper_only"
    )

    return {
        "date": date_str,
        "workflow_gaps": workflow_gaps,
        "global_hard": typed["global_hard"],
        "side_blocks": typed["side_blocks"],
        "candidate_decisions": candidate_decisions,
        "recommendation_count": len(candidate_inputs),
        "snapshot_recommendation_count": len(candidates),
        "d2_candidate_count": len(d2_candidates),
        "standard_count": standard_count,
        "guarded_count": guarded_count,
        "paper_only_count": paper_only_count,
        "unverifiable": _unique(unverifiable),
        "attribution_counts": attribution_counts,
        "day_attribution": {
            "classification": day_classification,
            "reason_codes": _unique(day_reasons),
            "missing_artifacts": missing_artifacts,
            "source_blockers": source_blockers,
            "source_trace": source_trace,
        },
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
        "attribution_counts": {
            name: sum(day["attribution_counts"].get(name, 0) for day in days)
            for name in sorted(ATTRIBUTION_CLASSES)
        },
        "day_attribution_counts": {
            name: sum(1 for day in days if day["day_attribution"].get("classification") == name)
            for name in sorted(ATTRIBUTION_CLASSES)
        },
        "unverifiable_day_count": sum(1 for day in days if day["unverifiable"]),
        "unverifiable_count": sum(len(day["unverifiable"]) for day in days),
    }
    contract_control = replay_complete_trend_w1_setup()
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
        "contract_control": {
            "name": "synthetic_complete_trend_w1_setup",
            "classification": "executable",
            "not_historical": True,
            "decision": contract_control,
        },
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
